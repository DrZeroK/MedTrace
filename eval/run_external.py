"""Evaluate pipeline variants on a standardized external dataset (data/standardized/<name>/).

    python -m eval.run_external --dataset cmb_clin --split dev --variants A0,A1,A2 --name cmbclin_dev_v1
    python -m eval.run_external --dataset cmb_clin --split test ...        # final comparison only

Automatic metrics (all proxies; labels are either the dataset's own expert references or rule-derived, never generated):
  dx_hit            eligible cases whose Diagnostic Discussion names the textbook diagnosis (string match on the case-title label)
  ddx_recall        share of the reference answer's differential diagnoses named in the Diagnostic Discussion
  measurement_cov   share of the record's unit-bearing measurements whose value appears in the note
  verifier_high     notes with at least one unresolved high-severity deterministic finding
  title/withheld leak cannot occur by construction (never in the input); post-admission sections are excluded from the sources.
`--limit N` and the mock model exist for smoke tests. Use `eval.blind_review` on the run directory for expert scoring.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import statistics as st
import sys
import time
from pathlib import Path

from medtrace.config import load_config
from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger
from medtrace.llm import LLMClient
from medtrace.mock_llm import MockLLM
from medtrace.note import schema_errors
from medtrace.pipeline import Pipeline, prompt_fingerprint
from medtrace import verify as V
from . import metrics as M
from .run_ablation import BUDGET, md_table

ROOT = Path(__file__).resolve().parent.parent
_norm = lambda s: re.sub(r"[\s（）()“”\"'、，,。/]", "", s or "").lower()


def name_hit(name: str, text: str) -> bool:
    """A disease name counts as mentioned if it, or any '或'/'/'-separated alternative of it, appears verbatim."""
    t = _norm(text)
    alts = [a for a in re.split(r"[或/]|（.*?）|\(.*?\)", name) if len(_norm(a)) >= 2] or [name]
    return any(_norm(a) in t for a in alts)


def load_dataset(name: str, split: str):
    d = ROOT / "data" / "standardized" / name
    cases = {c["case_id"]: c for c in json.loads((d / "cases.json").read_text("utf-8"))}
    refs = json.loads((d / "references.json").read_text("utf-8"))
    return [(cases[r["case_id"]], r) for r in refs if r["split"] == split or (split == "all" and r["split"] in ("dev", "validation", "test"))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="cmb_clin")
    ap.add_argument("--split", default="dev", choices=["dev", "validation", "test", "all"])
    ap.add_argument("--variants", default="A0,A1,A2")
    ap.add_argument("--name", default=time.strftime("ext_%Y%m%d_%H%M%S"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    cfg0 = load_config()
    if not cfg0.api_base:
        cfg0.api_base = "mock://"
    is_mock = cfg0.api_base.startswith("mock")
    items = load_dataset(a.dataset, a.split)
    items = items[:a.limit] if a.limit else items
    variants = [v.strip().upper() for v in a.variants.split(",") if v.strip()]
    rows, outputs = [], {v: [] for v in variants}
    for v in variants:
        cfg = copy.copy(cfg0)
        cfg.pipeline, cfg.max_calls_per_case = v, BUDGET[v]
        cfg.output_field_map, cfg.output_fields, cfg.include_meta = {}, [], False
        for i, (raw, ref) in enumerate(items):
            pipe = Pipeline(cfg, LLMClient(cfg, mock=MockLLM() if is_mock else None))
            case = parse_case(raw, i, cfg.cutoff_mode)
            res = pipe.run_case(case)
            rec = res.record
            disc = rec["diagnostic_discussion"]
            der = ref["derived"]
            hit, tot = V.measurement_coverage(res.note, build_ledger(case))
            ddx = der["reference_differentials"]
            ok_refs, n_refs = M.refs_valid(rec, raw)
            rows.append({
                "variant": v, "case_id": case.case_id, "tier": ref["quality"]["tier"], "chapter": ref["classification"]["specialty_chapter"],
                "complexity": ref["classification"]["complexity"], "status": res.status, "schema_valid": int(not schema_errors(rec)),
                "dx_eligible": int(der["dx_metric_eligible"]),
                "dx_hit": int(name_hit(ref["classification"]["disease_label"], disc)) if der["dx_metric_eligible"] else "",
                "ddx_named": sum(name_hit(n, disc) for n in ddx), "ddx_total": len(ddx),
                "meas_hit": hit, "meas_total": tot, "refs_valid": ok_refs, "refs_total": n_refs,
                "verifier_high": res.log["findings_final"]["high"], "verifier_medium": res.log["findings_final"]["medium"],
                "review_items": len(rec["review_items"]), "calls": res.log["calls"], "latency": res.log["latency"],
            })
            outputs[v].append(rec)
    summary = []
    for v in variants:
        r = [x for x in rows if x["variant"] == v]
        el = [x for x in r if x["dx_eligible"]]
        pct = lambda num, den: f"{100 * num / den:.1f}" if den else "n/a"
        summary.append({
            "variant": v, "cases": len(r), "completed_ok_%": pct(sum(x["status"] == "ok" for x in r), len(r)),
            "schema_valid_%": pct(sum(x["schema_valid"] for x in r), len(r)),
            "dx_hit_%": pct(sum(x["dx_hit"] for x in el), len(el)) + f" (n={len(el)})",
            "ddx_recall_%": pct(sum(x["ddx_named"] for x in r), sum(x["ddx_total"] for x in r)),
            "measurement_cov_%": pct(sum(x["meas_hit"] for x in r), sum(x["meas_total"] for x in r)),
            "refs_valid_%": pct(sum(x["refs_valid"] for x in r), sum(x["refs_total"] for x in r)),
            "notes_with_verifier_high": sum(x["verifier_high"] > 0 for x in r),
            "mean_review_items": round(st.mean(x["review_items"] for x in r), 1),
            "mean_calls": round(st.mean(x["calls"] for x in r), 2), "mean_latency_s": round(st.mean(x["latency"] for x in r), 2),
            "max_latency_s": round(max(x["latency"] for x in r), 2)})
    out = ROOT / "eval" / "results" / a.name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "per_case.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for v, recs in outputs.items():
        (out / f"outputs_{v}.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), "utf-8")
    # for eval.blind_review: the records each reviewer needs, plus the dataset's expert reference answers
    (out / "cases_used.json").write_text(json.dumps([{"case": raw, "annotation": {"reference": ref["reference"]}} for raw, ref in items],
                                                   ensure_ascii=False, indent=1), "utf-8")
    conf = {"name": a.name, "dataset": a.dataset, "split": a.split, "n_cases": len(items), "variants": variants,
            "budget": {v: BUDGET[v] for v in variants}, "model": cfg0.model or "<mock>", "mock": is_mock,
            "prompt": prompt_fingerprint(), "config": cfg0.public(),
            "dataset_manifest": json.loads((ROOT / "data" / "standardized" / a.dataset / "manifest.json").read_text("utf-8"))["raw_sha256"]}
    (out / "config.json").write_text(json.dumps(conf, ensure_ascii=False, indent=2), "utf-8")
    note = ("**MOCK MODEL** - mechanics only; the mock does not reason, so dx_hit / ddx_recall are meaningless here.\n\n" if is_mock else "")
    (out / "summary.md").write_text(f"# External evaluation `{a.name}`\n\n{note}Dataset `{a.dataset}` split `{a.split}` ({len(items)} cases) | "
                                    f"model `{conf['model']}` | prompts `{conf['prompt']}`\n\n" + md_table(summary) + "\n", "utf-8")
    print(md_table(summary))
    print(f"\nresults: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
