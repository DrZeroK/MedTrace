"""Controlled comparison of pipeline variants on the annotated evaluation set.

    python -m eval.run_ablation --name mock_faults --faults "wrong_number:0.5,unit_swap:0.3,..."   # offline harness test
    LLM_API_BASE=... LLM_MODEL=... python -m eval.run_ablation --name real_v1                      # designated model

Same cases, model, settings and scoring for every variant. All configuration is saved next to the results.
With the mock, every variant receives the *same* injected faults per case (paired design).
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import statistics as st
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from medtrace.config import load_config
from medtrace.inputs import parse_case
from medtrace.llm import LLMClient
from medtrace.mock_llm import MockLLM
from medtrace.pipeline import Pipeline, prompt_fingerprint
from . import metrics as M

HERE = Path(__file__).parent
BUDGET = {"A0": 1, "A1": 1, "A2": 2, "S2": 3, "A3": 2}   # logical model calls allowed per case


def load_eval_cases(split: str = "all"):
    cases = json.loads((HERE / "cases.json").read_text("utf-8"))
    return [c for c in cases if split == "all" or c["annotation"]["split"] == split]


def parse_faults(spec: str) -> dict:
    return {k.strip(): float(v) for k, v in (p.split(":", 1) for p in spec.split(",") if ":" in p)}


def run(variants, cases, faults, seed, budget=None, workers=1, mock=False):
    cfg0 = load_config()
    if mock or faults or not cfg0.api_base:      # fault injection only exists in the mock: never send such a run to a real model
        cfg0.api_base = "mock://"
    is_mock = cfg0.api_base.startswith("mock")
    rows, outputs = [], {v: [] for v in variants}
    for v in variants:
        cfg = copy.copy(cfg0)
        cfg.pipeline, cfg.max_calls_per_case = v, (budget or BUDGET[v])
        cfg.output_field_map, cfg.output_fields, cfg.include_meta = {}, [], False
        cfg.repair_call = True     # the ablation's A2/S2 are defined with the repair call (production default is off)
        def one(job, v=v, cfg=cfg):
            i, item = job
            mock = MockLLM(faults, seed) if is_mock else None
            pipe = Pipeline(cfg, LLMClient(cfg, mock=mock))
            case = parse_case(item["case"], i, cfg.cutoff_mode)
            res = pipe.run_case(case)
            ann, rec = item["annotation"], res.record
            hits = M.key_fact_hits(rec, ann)
            ok_refs, n_refs = M.refs_valid(rec, item["case"])
            fs = M.fault_survival(rec, mock.fault_log) if mock else []
            return {
                "variant": v, "case_id": case.case_id, "category": ann["category"], "split": ann["split"],
                "status": res.status, "schema_valid": int(M.is_schema_valid(rec)),
                "raw_parse_retries": res.log.get("raw_parse_retries", 0),
                "refs_valid": ok_refs, "refs_total": n_refs,
                "key_hits": sum(hits.values()), "key_total": len(hits),
                "missed_facts": ";".join(k for k, h in hits.items() if not h),
                "must_not_hits": len(M.must_not_hits(rec, ann)), "must_not_detail": " | ".join(M.must_not_hits(rec, ann)),
                "verifier_high_initial": res.log["findings_initial"]["high"], "verifier_high_final": res.log["findings_final"]["high"],
                "verifier_medium_final": res.log["findings_final"]["medium"],
                "faults_injected": len(fs), "faults_survived": sum(f["survived"] for f in fs),
                "faults_survived_unflagged": sum(f["survived"] and not f["flagged"] for f in fs),
                "fault_detail": ";".join(f'{f["fault"]}:{"S" if f["survived"] else "R"}{"f" if f["flagged"] else ""}' for f in fs),
                "calls": res.log["calls"], "retries": res.log["retries"], "latency": res.log["latency"],
            }, rec

        with ThreadPoolExecutor(max(1, workers)) as ex:
            for row, rec in ex.map(one, list(enumerate(cases))):
                rows.append(row)
                outputs[v].append(rec)
    return rows, outputs, cfg0


def summarise(rows, variants):
    out = []
    for v in variants:
        r = [x for x in rows if x["variant"] == v]
        n = len(r)
        cov = [x["key_hits"] / x["key_total"] for x in r]
        lo, hi = M.bootstrap_ci(cov)
        inj, surv = sum(x["faults_injected"] for x in r), sum(x["faults_survived"] for x in r)
        unfl = sum(x["faults_survived_unflagged"] for x in r)
        refs_t = sum(x["refs_total"] for x in r)
        out.append({
            "variant": v, "cases": n,
            "completed_ok_%": round(100 * sum(x["status"] == "ok" for x in r) / n, 1),
            "schema_valid_%": round(100 * sum(x["schema_valid"] for x in r) / n, 1),
            "refs_valid_%": round(100 * sum(x["refs_valid"] for x in r) / refs_t, 1) if refs_t else "n/a",
            "key_fact_coverage_%": round(100 * st.mean(cov), 1),
            "coverage_95CI": f"{100 * lo:.1f}-{100 * hi:.1f}",
            "cases_with_must_not_hit": sum(x["must_not_hits"] > 0 for x in r),
            "cases_with_verifier_high": sum(x["verifier_high_final"] > 0 for x in r),
            "faults_injected": inj,
            "faults_in_output": surv,
            "faults_in_output_unflagged": unfl,
            "mean_calls": round(st.mean(x["calls"] for x in r), 2),
            "mean_latency_s": round(st.mean(x["latency"] for x in r), 3),
            "max_latency_s": round(max(x["latency"] for x in r), 3),
        })
    return out


def md_table(rows: list[dict]) -> str:
    cols = list(rows[0])
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] +
                     ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=time.strftime("run_%Y%m%d_%H%M%S"))
    ap.add_argument("--variants", default="A0,A1,A2,S2,A3")
    ap.add_argument("--split", default="all", choices=["all", "dev", "heldout"])
    ap.add_argument("--faults", default="", help="mock only: fault:prob,...")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=int, default=0, help="override per-variant model-call budget")
    ap.add_argument("--mock", action="store_true", help="force the offline mock model even if .env configures a real endpoint")
    ap.add_argument("--workers", type=int, default=1, help="cases in parallel (mind the provider's rate limits)")
    a = ap.parse_args(argv)
    variants = [v.strip().upper() for v in a.variants.split(",") if v.strip()]
    cases = load_eval_cases(a.split)
    rows, outputs, cfg = run(variants, cases, parse_faults(a.faults), a.seed, a.budget or None, a.workers, a.mock)
    out = HERE / "results" / a.name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "per_case.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for v, recs in outputs.items():
        (out / f"outputs_{v}.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), "utf-8")
    summary = summarise(rows, variants)
    is_mock = cfg.api_base.startswith("mock")
    conf = {"name": a.name, "variants": variants, "split": a.split, "n_cases": len(cases), "faults": a.faults, "seed": a.seed,
            "budget": {v: (a.budget or BUDGET[v]) for v in variants}, "model": cfg.model or "<mock>", "mock": is_mock,
            "prompt": prompt_fingerprint(), "config": cfg.public()}
    (out / "config.json").write_text(json.dumps(conf, ensure_ascii=False, indent=2), "utf-8")
    note = ("**MOCK MODEL.** These numbers test the software and the verifier's ability to catch *injected* errors. "
            "They say nothing about clinical quality or about the designated model.\n\n" if is_mock else "")
    (out / "summary.md").write_text(f"# Ablation `{a.name}`\n\n{note}Model: `{conf['model']}`  |  cases: {len(cases)} ({a.split})  |  "
                                    f"prompts: `{conf['prompt']}`  |  faults: `{a.faults or 'none'}`  |  seed: {a.seed}\n\n"
                                    + md_table(summary) + "\n\nKey-fact coverage and must-not hits are regex proxies defined in "
                                    "`eval/cases.json`; confirm with blinded review (`eval/blind_review.py`).\n", "utf-8")
    print(md_table(summary))
    print(f"\nresults: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
