"""Score official-protocol outputs against the competition rubric (guide Appendix 2), caps included.

    python -m eval.rubric_judge --input input.json --outputs runA/output.json runB/output.json \
        [--refs refs.json] --out eval/results/<name>

Per case a judge model scores the five clinical dimensions 0-10 and lists major errors with quotes. The rubric's
rules are then applied in code, not left to the judge:
    no record / failed / any empty narrative section        -> 0
    harmful recommendation or serious omission              -> 0
    fabricated key fact, or a key number/chronology error   -> total capped at 50%
Every major error is then re-checked by an independent adjudication call (the rubric zeroes a case only "经第三位医学
专家复核后"); only confirmed errors trigger the zero or the cap. The first-pass judge marked standard care as harmful
(fasting with gastric decompression in cholecystitis), so a single unreviewed verdict must not zero a case.
JUDGE_ADJUDICATE=0 disables the re-check; JUDGE_ADJ_THINKING=0 turns its thinking mode off (default on).
`refs.json` ({case_id: ["reference point", ...]}) holds clinician-written scoring points, the way the official
judges work; without it the judge scores against the rubric alone. Judge settings: JUDGE_ENDPOINT / JUDGE_MODEL
(default: the development ENDPOINT / MODEL_NAME), JUDGE_THINKING=1 to enable thinking. Keep competition and
practice cases on local or designated endpoints only.

This is a development proxy. Calibrate it against two-person clinician scoring before trusting small differences.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

from medtrace.config import load_config
from medtrace.llm import CallStats, LLMClient, LLMError
from medtrace.note import ParseError, parse_json_object
from .run_ablation import md_table

DIMS = ("fidelity", "discussion", "plan", "structure", "attribution")
ZERO_ERRORS = {"harmful", "serious_omission"}
CAP_ERRORS = {"fabricated_key_fact", "key_number_or_chronology"}
SECTIONS = ("case_features", "diagnostic_discussion", "plan")

SYSTEM = "你是一名严谨的临床医学评审专家，按竞赛评分标准独立评分。只输出一个JSON对象，不要输出其他内容。"
PROMPT = """请对照入院资料，评审下面这份算法生成的首次病程记录。

<入院资料 截止时间="{cutoff}">
{sources}
</入院资料>

<首次病程记录>
{note}
</首次病程记录>
{refs}
按以下五个维度各打0-10分（10分为无可挑剔）：
1. fidelity 事实准确与忠实性：关键症状、体征、数值及单位、时间顺序、阴性与缺失信息是否与资料一致；有无资料中没有的内容；有无把“未提供”写成“正常/否认”。
2. discussion 拟诊讨论：初步判断是否有具体依据；鉴别诊断是否针对本例（2-3个方向并说明理由，而非通用清单）；信息不足时是否如实写明待查而非强下结论。
3. plan 诊疗计划：检查、处理、观察是否对应当前问题；是否用“拟/建议/复查”区分计划与已完成事项；是否写明观察哪些症状、复查哪些指标。
4. structure 结构与个体化：三部分完整、重点突出（重要阳性、相关阴性、病程），体现本例特点、不是可套用于他例的模板。
5. attribution 来源与待核：evidence条目能对应真实资料编号，fact与inference区分正确；review_items清楚列出缺失、矛盾和需医生确认的事项。

另列出全部重大错误（没有则为空列表），类型只能是：
- "fabricated_key_fact"：编造关键事实（资料中没有的症状、病史、检查、数值或治疗）。
- "key_number_or_chronology"：关键数值或时间顺序错误，足以影响临床判断。
- "harmful"：基于资料的建议可能造成严重伤害（如使用已记录过敏的药物）。
- "serious_omission"：严重遗漏（如漏掉资料中危及生命的情况）。
每条须引用记录原文和资料原文；措辞不同但含义正确不算错误，不要因篇幅长短加减分。

输出：{{"scores": {{"fidelity": 0, "discussion": 0, "plan": 0, "structure": 0, "attribution": 0}},
"major_errors": [{{"type": "...", "note_quote": "...", "source_quote": "...", "reason": "不超过40字"}}],
"comments": "不超过80字"}}"""


ADJ_SYSTEM = "你是第三位医学复核专家，负责复核另一位评审提出的重大错误是否成立。独立判断，不受原评审结论影响。只输出一个JSON对象。"
ADJ_PROMPT = """另一位评审认为下面这份首次病程记录存在一项重大错误。请对照入院资料独立复核该错误是否成立。

<入院资料 截止时间="{cutoff}">
{sources}
</入院资料>

<首次病程记录>
{note}
</首次病程记录>

<待复核错误>
类型：{type}（{meaning}）
记录原文：{note_quote}
资料原文：{source_quote}
原评审理由：{reason}
</待复核错误>

复核标准（不满足即判为不成立）：
1. 记录原文确实出现在首次病程记录中，且结合上下文意思与原评审所述一致；断章取义、忽略同句已写明的前提条件或备选方案，不成立。
2. harmful：该建议按公认指南或教科书属于禁忌或明显违背标准处理，且结合本例资料可能造成严重伤害才成立。属于该情境下的常规处理或可接受方案（即使不是唯一或最优方案），或已附合理前提条件的，不成立。
3. serious_omission：遗漏的必须是资料明确提示、危及生命或有时间窗的紧急处理（如再灌注评估、抗休克、紧急手术指征、致命鉴别）才成立；鉴别诊断不够全面、非紧急检查未列出、措辞不够完整，不成立。
4. fabricated_key_fact：内容在入院资料中确实不存在、且属于影响判断的关键事实才成立；合理的临床归纳、同义改写、资料已有内容或明确标为推断的内容，不成立。
5. key_number_or_chronology：数值、单位或时间顺序与资料不符，且足以影响临床判断才成立；四舍五入前后一致或仅格式差异，不成立。

只输出：{{"confirmed": true或false, "reason": "不超过60字，说明依据"}}"""
ADJ_MEANING = {"harmful": "可能造成严重伤害的建议", "serious_omission": "严重遗漏",
               "fabricated_key_fact": "编造关键事实", "key_number_or_chronology": "关键数值或时序错误"}


def confirmed_errors(judgement: dict) -> list[dict]:
    """Major errors that count: confirmed by adjudication, or not adjudicated (adjudication off or its call failed)."""
    return [e for e in judgement.get("major_errors") or [] if (e.get("adjudication") or {}).get("confirmed", True) is not False]


def note_text(rec: dict) -> str:
    m = rec["medical_record"]
    ev = "\n".join(f"- [{e.get('kind')}] {e.get('statement')} ({'、'.join(e.get('source_ids') or [])})" for e in m.get("evidence") or [])
    rv = "\n".join(f"- {r}" for r in m.get("review_items") or [])
    return (f"【病例特点】{m['case_features']}\n【拟诊讨论】{m['diagnostic_discussion']}\n【诊疗计划】{m['plan']}\n"
            f"【依据说明】\n{ev}\n【待核事项】\n{rv or '[]'}")


def score_case(rec: dict | None, judgement: dict | None) -> dict:
    """Apply the rubric's zero and cap rules to one judged case. Returns {total (0-100), raw, rule}."""
    m = (rec or {}).get("medical_record") or {}
    if not rec or rec.get("status") != "success" or any(not str(m.get(s) or "").strip() for s in SECTIONS):
        return {"total": 0.0, "raw": 0.0, "rule": "zero: missing or failed record"}
    if not judgement or "scores" not in judgement:
        return {"total": None, "raw": None, "rule": "not judged"}
    raw = sum(max(0.0, min(10.0, float(judgement["scores"].get(d, 0) or 0))) for d in DIMS) * 2
    types = {e.get("type") for e in confirmed_errors(judgement)}
    if types & ZERO_ERRORS:
        return {"total": 0.0, "raw": raw, "rule": "zero: " + ",".join(sorted(types & ZERO_ERRORS))}
    if types & CAP_ERRORS:
        return {"total": min(raw, 50.0), "raw": raw, "rule": "cap50: " + ",".join(sorted(types & CAP_ERRORS))}
    return {"total": raw, "raw": raw, "rule": ""}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outputs", nargs="+", required=True)
    ap.add_argument("--refs")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    cases = {c["case_id"]: c for c in json.loads(Path(a.input).read_text("utf-8"))}
    refs = json.loads(Path(a.refs).read_text("utf-8")) if a.refs else {}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    cfg = copy.copy(load_config(development=True))
    cfg.endpoint = os.environ.get("JUDGE_ENDPOINT", cfg.endpoint)
    cfg.model = os.environ.get("JUDGE_MODEL", cfg.model)
    cfg.max_calls_per_case, cfg.extra_body, cfg.seed = 1, {}, 42
    cfg.enable_thinking = os.environ.get("JUDGE_THINKING", "0").strip() in ("1", "true", "yes")
    client = LLMClient(cfg)
    adjudicate = os.environ.get("JUDGE_ADJUDICATE", "1").strip() not in ("0", "false", "no")
    adj_cfg = copy.copy(cfg)
    adj_cfg.enable_thinking = os.environ.get("JUDGE_ADJ_THINKING", "1").strip() not in ("0", "false", "no")
    adj_client = LLMClient(adj_cfg)

    cache_path = out / "rubric_judge.json"
    cache = json.loads(cache_path.read_text("utf-8")) if cache_path.exists() else {}
    rows, per_case, errors_out = [], [], []
    names = [Path(p).parent.name or Path(p).stem for p in a.outputs]
    for path, name in zip(a.outputs, names):
        run = name if names.count(name) == 1 else path   # two outputs in one directory stay distinct
        recs = {r["case_id"]: r for r in json.loads(Path(path).read_text("utf-8"))}
        scored = []
        for cid, case in cases.items():
            rec, key = recs.get(cid), None
            if rec and rec.get("status") == "success":
                ref = refs.get(cid)
                prompt = PROMPT.format(
                    cutoff=case.get("record_cutoff", "T0"),
                    sources="\n".join(f"[{s['source_id']}] {s['content']}" for s in case["sources"]),
                    note=note_text(rec),
                    refs=("\n<参考评分要点>\n" + "\n".join(f"- {x}" for x in ref) + "\n</参考评分要点>\n") if ref else "")
                # cache identity = what was judged and how: note, sources, refs, judge model/endpoint/thinking
                key = hashlib.sha256(json.dumps([SYSTEM, prompt, cfg.model, cfg.endpoint, cfg.enable_thinking],
                                                ensure_ascii=False).encode("utf-8")).hexdigest()
            if key and key not in cache:
                for attempt in (1, 2):          # one retry: the judge occasionally emits malformed JSON
                    try:
                        cache[key] = parse_json_object(client.chat(SYSTEM, prompt, CallStats()))
                        break
                    except (LLMError, ParseError) as e:
                        print("judge failed:", f"{run}|{cid}|try{attempt}", f"{type(e).__name__}: {e}"[:200], file=sys.stderr)
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")
            j = copy.deepcopy(cache.get(key) or {})
            if adjudicate and j:
                for e in j.get("major_errors") or []:
                    if e.get("type") not in ZERO_ERRORS | CAP_ERRORS:
                        continue
                    adj_prompt = ADJ_PROMPT.format(
                        cutoff=case.get("record_cutoff", "T0"),
                        sources="\n".join(f"[{s['source_id']}] {s['content']}" for s in case["sources"]),
                        note=note_text(rec), type=e.get("type"), meaning=ADJ_MEANING[e.get("type")],
                        note_quote=e.get("note_quote", ""), source_quote=e.get("source_quote", ""), reason=e.get("reason", ""))
                    akey = hashlib.sha256(json.dumps([ADJ_SYSTEM, adj_prompt, adj_cfg.model, adj_cfg.endpoint,
                                                      adj_cfg.enable_thinking], ensure_ascii=False).encode("utf-8")).hexdigest()
                    if akey not in cache:
                        try:
                            cache[akey] = parse_json_object(adj_client.chat(ADJ_SYSTEM, adj_prompt, CallStats()))
                        except (LLMError, ParseError) as err:   # keep the error: a failed review must not clear a case
                            print("adjudication failed:", f"{run}|{cid}", f"{type(err).__name__}: {err}"[:200], file=sys.stderr)
                        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")
                    if isinstance(cache.get(akey), dict) and isinstance(cache[akey].get("confirmed"), bool):
                        e["adjudication"] = cache[akey]
            s = score_case(rec, j or None)
            scored.append(s)
            errors_out += [{"run": run, "output": str(path), "case_id": cid,
                            **{k: e.get(k, "") for k in ("type", "note_quote", "source_quote", "reason")},
                            "adjudication": e.get("adjudication")}
                           for e in j.get("major_errors") or [] if e.get("type") in ZERO_ERRORS | CAP_ERRORS]
            per_case.append({"run": run, "case_id": cid, "total": s["total"], "rule": s["rule"],
                             **{d: (j.get("scores") or {}).get(d) for d in DIMS},
                             "major_errors": "; ".join(
                                 f"{e.get('type')}{'' if (e.get('adjudication') or {}).get('confirmed', True) else '[overturned]'}: "
                                 f"{e.get('note_quote', '')[:40]}" for e in j.get("major_errors") or [])})
        done = [s for s in scored if s["total"] is not None]
        rows.append({"run": run, "cases": len(scored), "judged": len(done),
                     "mean_total": round(sum(s["total"] for s in done) / len(done), 2) if done else None,
                     "mean_uncapped": round(sum(s["raw"] for s in done) / len(done), 2) if done else None,
                     "capped_50": sum(s["rule"].startswith("cap50") for s in done),
                     "zero": sum(s["rule"].startswith("zero") for s in done),
                     "overturned_errors": sum("[overturned]" in r["major_errors"] for r in per_case if r["run"] == run)})
    md = (f"# Rubric judge (`{cfg.model}`, thinking {'on' if cfg.enable_thinking else 'off'}, "
          f"adjudication {'on (thinking ' + ('on' if adj_cfg.enable_thinking else 'off') + ')' if adjudicate else 'off'}"
          f"{', with reference points' if refs else ', no reference points'})\n\n{md_table(rows)}\n\n## Per case\n\n"
          f"{md_table(per_case)}\n\nDevelopment proxy for the official clinical scoring; not a clinician's score.\n")
    (out / "rubric_summary.md").write_text(md, "utf-8")
    # every major error with its adjudication, for clinician calibration (eval/adjudication_calibration.py)
    (out / "major_errors.json").write_text(json.dumps(errors_out, ensure_ascii=False, indent=1), "utf-8")
    print(md_table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
