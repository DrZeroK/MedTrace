"""Development-only phase-one experiment. Only public CMB-Clin can reach the configured API.

Run with an absolute --directory. All phases share one 120+180 request journal.
Clinical acceptance and promotion are intentionally not automated.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

from medtrace.config import Config, load_config
from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger
from medtrace.llm import BudgetExceeded, CallStats, LLMClient, LLMError
from medtrace.note import ParseError, official_schema_errors, parse_json_object, to_record
from medtrace.pipeline import Pipeline, prompt_fingerprint
from medtrace.verify import measurement_coverage
from eval.experiment import RequestBudget, fingerprint, write_new
from eval.run_external import gold_diagnoses, name_hit

ROOT = Path(__file__).resolve().parents[1]
SEED_INSTRUCTION = "按临床问题组织记录：先概括关键阳性、鉴别性阴性和资料空缺；拟诊讨论逐一关联支持证据、反对证据及待明确问题；计划按检查、处理、观察对应每个问题。仅改进组织方式，遵守后文固定事实约束和JSON协议，不引入病例外事实。"


def keep(path: Path, value):
    if path.exists():
        if json.loads(path.read_text("utf-8")) != value:
            raise ValueError(f"immutable artifact differs: {path.name}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, value)


def load_public_data():
    # Byte-identical 74-case release of the frozen phase-one round; the live standardized
    # corpus was filtered by the 2026-11-18 admission-input review without changing this protocol.
    directory = ROOT / "eval/frozen/cmb_clin_74_20261118"
    cases = json.loads((directory / "cases.json").read_text("utf-8"))
    refs = json.loads((directory / "references.json").read_text("utf-8"))
    # CMB-Clin has no timestamped trajectory. T0 is a symbolic admission cutoff, not an invented date.
    by_id = {c["case_id"]: {**c, "record_cutoff": c.get("record_cutoff") or "T0"} for c in cases}
    if len(by_id) != len(cases) or len(refs) != 74:
        raise ValueError("expected the frozen 74-case CMB-Clin release")
    groups = {split: sorted([r["case_id"] for r in refs if r["split"] == split]) for split in ("dev", "test")}
    if len(groups["dev"]) != 26 or len(groups["test"]) != 30:
        raise ValueError("CMB-Clin split counts changed")
    dev = list(groups["dev"])
    random.Random(42).shuffle(dev)
    splits = {"proposal": dev[:18], "selection": dev[18:], "confirmation": groups["test"]}
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (directory / "cases.json", directory / "references.json")}
    return {r["case_id"]: (by_id[r["case_id"]], r) for r in refs}, {"seed": 42, "dataset": "CMB-Clin", "sources": sources,
                                                               "null_cutoff_normalization": "T0 (symbolic)", **splits}


def program_identity():
    paths = list((ROOT / "medtrace").glob("*.py")) + [ROOT / p for p in (
        "eval/phase1.py", "eval/experiment.py", "eval/optimize_prompt.py", "eval/run_external.py",
        "eval/judge_dx.py", "eval/blind_review.py", "data_pipeline/cdee_negation.py")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


class Experiment:
    def __init__(self, directory: Path, cfg: Config):
        if not cfg.development or (not cfg.endpoint and cfg.api_base.startswith("mock")):
            raise ValueError("real experiment requires explicit development configuration and a real endpoint")
        self.items, self.splits = load_public_data()
        self.cfg = copy.deepcopy(cfg)
        self.cfg.pipeline, self.cfg.prompt_version = "A2", "v2"
        self.cfg.context_mode, self.cfg.prompt_candidate_path, self.cfg.kb_path = "legacy", "", ""
        self.cfg.max_retries, self.cfg.max_calls_per_case, self.cfg.repair_call, self.cfg.workers = 0, 2, False, 1
        self.cfg.temperature, self.cfg.seed = 0, 42
        self.cfg.output_protocol = "official"
        public = self.cfg.public()
        for key in ("input_path", "output_path", "log_dir", "api_key"):
            public.pop(key, None)
        for key in ("api_base", "endpoint"):
            public[key] = fingerprint(public[key])
        # Tokens belong in api_key, never in URLs/provider passthrough configuration.
        if any(k.lower() in ("api_key", "authorization", "headers", "api_base", "endpoint", "model", "messages") for k in self.cfg.extra_body):
            raise ValueError("provider body contains routing/credential overrides")
        self.directory = directory
        import os
        self.judge_model = os.environ.get("JUDGE_MODEL") or self.cfg.model
        self.budget = RequestBudget(directory, {"config": public, "data": self.splits, "program": program_identity(),
                                               "base_prompt": prompt_fingerprint("v2"), "optimizer": "dspy==3.5.0",
                                               "judge_model": self.judge_model})
        try:
            keep(directory / "splits.json", self.splits)
            for name in ("cache", "candidates", "errors"):
                (directory / name).mkdir(exist_ok=True)
        except BaseException:
            self.budget.close()
            raise

    def close(self):
        self.budget.close()

    def candidate(self, instruction):
        if not isinstance(instruction, str) or not 0 < len(instruction.strip()) <= 1600 or "<<" in instruction or ">>" in instruction:
            raise ValueError("organization instruction must be 1-1600 characters, without template markers")
        digest = hashlib.sha256(instruction.encode()).hexdigest()
        path = self.directory / "candidates" / f"{digest}.json"
        keep(path, {"schema_version": 1, "instruction": instruction, "instruction_sha256": digest,
                    "base_prompt": prompt_fingerprint("v2")})
        return path

    def generate(self, case_id, context_mode, instruction=None):
        allowed = self.splits["confirmation"] if self.budget.stage == "confirmation" else self.splits["selection"]
        if case_id not in allowed:
            raise ValueError("case is outside the current experiment partition")
        raw, ref = self.items[case_id]
        key = {"case_id": case_id, "context_mode": context_mode, "instruction": instruction,
               "data_sha256": fingerprint(raw)}
        path = self.directory / "cache" / f"{fingerprint(key)}.json"
        if path.exists():
            saved = json.loads(path.read_text("utf-8"))
            if saved["key"] != key or saved["result_sha256"] != fingerprint(saved["result"]):
                raise ValueError("cached generation failed identity/hash validation")
            return saved["result"]
        if self.budget.used(self.budget.stage) >= self.budget.LIMITS[self.budget.stage]:
            raise BudgetExceeded("generation stage budget exhausted")
        cfg = copy.copy(self.cfg)
        cfg.context_mode = context_mode
        cfg.prompt_candidate_path = str(self.candidate(instruction)) if instruction else ""
        transport_cfg = copy.copy(cfg)
        transport_cfg.output_protocol = "legacy"  # development provider auth; output validation remains official
        client = LLMClient(transport_cfg, transport=self.budget.post)
        case = parse_case(raw, 0, cfg.cutoff_mode)
        previous = self.budget.purpose
        self.budget.purpose = "generation"
        try:
            result = Pipeline(cfg, client).run_case(case)
        finally:
            self.budget.purpose = previous
        if "BudgetExceeded" in result.log.get("error", ""):
            raise BudgetExceeded("generation was interrupted by the shared request budget")
        if result.log.get("llm_errors") and result.status != "ok":
            keep(self.directory / "errors" / f"service_{self.budget.used():03d}.json", {"key": key, "log": result.log})
            raise LLMError("development service failed; attempt retained, stop before spending further requests")
        flat = to_record(result.note, case, transport_cfg)
        valid = result.status == "ok" and not official_schema_errors(result.record, {s.raw_id for s in case.sources})
        if not valid:
            flat.update(case_features="生成失败：无有效记录，不能进行临床内容评分。", diagnostic_discussion="", treatment_plan="",
                        evidence=[], review_items=[{"type": "verify", "description": "生成失败，按技术失败单独统计。", "source_ids": []}])
        hits, total = measurement_coverage(result.note, build_ledger(case))
        coverage = (hits / total if total else 1.0) if valid else 0.0
        dx_hit = int(any(name_hit(g, flat["diagnostic_discussion"]) for g in gold_diagnoses(ref))) if ref["derived"]["dx_metric_eligible"] else None
        score = (statistics.mean([coverage, dx_hit]) if dx_hit is not None else coverage) if valid else 0.0
        data = {"record": flat, "official_record": result.record, "log": result.log,
                "metrics": {"score": score, "valid": valid, "measurement_coverage": coverage, "dx_hit": dx_hit,
                            "high_findings": result.log["findings_final"]["high"], "latency": result.log["latency"],
                            "omitted_critical_flags": sum(f.code == "omitted_critical" for f in result.final_findings),
                            "invalid_reference_flags": sum(f.code == "invalid_ref" for f in result.initial_findings),
                            "http_attempts": result.log["http_attempts"], "failed": result.status != "ok"}}
        keep(path, {"key": key, "result": data, "result_sha256": fingerprint(data)})
        print(f"{self.budget.stage} {case_id} context={context_mode} score={score:.3f} requests={self.budget.used()}", flush=True)
        return data

    def evaluate(self, mode, instruction=None, case_ids=None):
        ids = case_ids or self.splits["selection"]
        rows = [self.generate(case_id, mode, instruction) for case_id in ids]
        dx = [r["metrics"]["dx_hit"] for r in rows if r["metrics"]["dx_hit"] is not None]
        return {"cases": len(rows), "score": statistics.mean(r["metrics"]["score"] for r in rows),
                "valid_records": sum(r["metrics"]["valid"] for r in rows),
                "measurement_coverage": statistics.mean(r["metrics"]["measurement_coverage"] for r in rows),
                "dx_hit_rate": statistics.mean(dx) if dx else None, "dx_eligible": len(dx),
                "notes_with_high_findings": sum(r["metrics"]["high_findings"] > 0 for r in rows),
                "failed_records": sum(r["metrics"]["failed"] for r in rows),
                "omitted_critical_flags": sum(r["metrics"]["omitted_critical_flags"] for r in rows),
                "invalid_reference_flags": sum(r["metrics"]["invalid_reference_flags"] for r in rows),
                "generation_http_attempts": sum(r["metrics"]["http_attempts"] for r in rows),
                "latency_mean_s": statistics.mean(r["metrics"]["latency"] for r in rows)}

    def develop(self):
        if (self.directory / "selection.json").exists():
            return json.loads((self.directory / "selection.json").read_text())
        from eval.optimize_prompt import optimize
        a = self.evaluate("legacy")
        b = self.evaluate("zh_context_v1")
        instruction = optimize(self)
        c = self.evaluate("zh_context_v1", instruction)
        winner = "C" if c["score"] > b["score"] else "B"
        selection = {"schema_version": 1, "A": a, "B": b, "C": c, "winner": winner,
                     "instruction": instruction if winner == "C" else None,
                     "promotion": "candidate_only_clinical_review_pending"}
        keep(self.directory / "selection.json", selection)
        return selection

    def judge(self, label, case_id, record):
        path = self.directory / "cache" / f"judge_{label}_{case_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        cfg = copy.copy(self.cfg)
        cfg.model = self.judge_model
        cfg.max_calls_per_case, cfg.output_protocol, cfg.extra_body = 1, "legacy", {}
        from eval.judge_dx import SYSTEM, PROMPT
        stats = CallStats()
        self.budget.purpose = "diagnosis_judge"
        try:
            raw = LLMClient(cfg, transport=self.budget.post).chat(SYSTEM, PROMPT.format(
                gold="\n".join(gold_diagnoses(self.items[case_id][1])), disc=record["diagnostic_discussion"][:4000]), stats)
            rows = parse_json_object(raw).get("judgements")
            if not isinstance(rows, list) or len(rows) != len(gold_diagnoses(self.items[case_id][1])) or any(
                    not isinstance(r, dict) or r.get("label") not in ("primary", "differential", "absent") for r in rows):
                raise ValueError("invalid diagnosis judge response")
            verdict = {"model": cfg.model, "same_as_generator": cfg.model == self.cfg.model, "verdicts": rows}
        except BudgetExceeded:
            raise
        except (LLMError, ParseError, ValueError) as e:
            verdict = {"model": cfg.model, "error": type(e).__name__, "verdicts": None}
        finally:
            self.budget.purpose = "generation"
        keep(path, verdict)
        return verdict

    def confirm(self):
        if (self.directory / "confirmation/summary.json").exists():
            return json.loads((self.directory / "confirmation/summary.json").read_text("utf-8"))
        selection = json.loads((self.directory / "selection.json").read_text())
        self.budget.stage = "confirmation"
        winner = selection["winner"]
        arms = {"A": ("legacy", None), winner: ("zh_context_v1", selection["instruction"])}
        summary = {label: self.evaluate(*settings, case_ids=self.splits["confirmation"]) for label, settings in arms.items()}
        run = self.directory / "confirmation"
        run.mkdir(exist_ok=True)
        cases = [{"case": self.items[cid][0], "annotation": {"split": "test", "gold": {"diagnoses": gold_diagnoses(self.items[cid][1])}}}
                 for cid in self.splits["confirmation"]]
        keep(run / "cases_used.json", cases)
        verdicts = {}
        for label, settings in arms.items():
            records = []
            for cid in self.splits["confirmation"]:
                rec = self.generate(cid, *settings)["record"]
                records.append(rec)
                if self.items[cid][1]["derived"]["dx_metric_eligible"]:
                    verdicts[f"{label}|{cid}"] = self.judge(label, cid, rec)
            keep(run / f"outputs_{label}.json", records)
        keep(run / "judge_proxy.json", verdicts)
        from eval.blind_review import export
        if not (run / "review").exists():
            export(run, ["R1", "R2"], 42)
        keep(run / "summary.json", {"arms": summary, "clinical_review": "pending", "budget": self.budget.summary()})
        return summary

    def report(self):
        report = {"budget": self.budget.summary(), "official_default_changed": False, "clinical_review": "pending"}
        for name in ("selection.json", "confirmation/summary.json", "context_report.json"):
            path = self.directory / name
            if path.exists():
                report[name] = json.loads(path.read_text())
        # Each report is a snapshot; earlier reports are never overwritten during resume.
        path = self.directory / f"report_{self.budget.used():03d}_{fingerprint(report)[:12]}.json"
        keep(path, report)
        markdown = path.with_suffix(".md")
        if not markdown.exists():
            lines = ["# MedTrace 第一阶段实验", "", "正式默认流程未改变；候选待临床盲评。", "",
                     f"实际 HTTP 请求：{self.budget.used()}/300；开发 {self.budget.used('development')}/120，确认 {self.budget.used('confirmation')}/180。",
                     "费用未知：未配置经过核验的服务单价。诊断命中、模型评审、规则告警均为代理指标，不是临床正确率。", "",
                     "CMB-Clin dev26：seed42 提议18、选择8；冻结后 test30 仅作一次确认。曾使用的 validation17 不作独立验证集。",
                     "CHIP-CDEE 仅输出汇总统计，不分发原文。预算在发送前记账，断点重启不重置。", ""]
            for section in ("selection.json", "confirmation/summary.json", "context_report.json"):
                if section in report:
                    lines += [f"## {section}", "", "```json", json.dumps(report[section], ensure_ascii=False, indent=2), "```", ""]
            with markdown.open("x", encoding="utf-8") as f:
                f.write("\n".join(lines))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("develop", "confirm", "report", "rules"))
    ap.add_argument("--directory", required=True, type=Path)
    args = ap.parse_args(argv)
    cfg = load_config(development=True)
    experiment = Experiment(args.directory, cfg)
    try:
        if args.action == "develop":
            experiment.develop()
        elif args.action == "confirm":
            experiment.confirm()
        elif args.action == "rules":
            from data_pipeline.cdee_negation import compare_context, RAW
            result = {split: compare_context(json.loads((RAW / f"CHIP-CDEE_{split}.json").read_text())) for split in ("train", "dev")}
            keep(args.directory / "context_report.json", result)
        experiment.report()
        return 0
    except (BudgetExceeded, LLMError) as e:
        print(f"experiment stopped: {type(e).__name__}: {e}", file=sys.stderr)
        experiment.report()
        return 2
    finally:
        experiment.close()


if __name__ == "__main__":
    raise SystemExit(main())
