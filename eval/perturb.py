"""Clinical robustness: change one clinically meaningful fact and check that the note changes accordingly.

    python -m eval.perturb [--variant A2] [--name NAME]

For each perturbation the base case and the edited case are both generated (the edited one through the
incremental-update path, so the model is told what changed). Checks:
  present   - new information / required reassessment appears
  absent    - obsolete or leaked content does not appear
  invariant - key facts covered in the base note and unaffected by the edit are still covered
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

from medtrace.config import load_config
from medtrace.inputs import parse_case
from medtrace.llm import LLMClient
from medtrace.pipeline import Pipeline
from medtrace.update import run_update
from . import metrics as M
from .run_ablation import BUDGET, load_eval_cases, md_table

HERE = Path(__file__).parent


def apply_edit(case: dict, edit: dict) -> dict:
    c = copy.deepcopy(case)
    if edit["op"] == "add":
        c["sources"].append({"source_id": edit["source_id"], "content": edit["content"]})
    elif edit["op"] == "replace":
        src = next(s for s in c["sources"] if s["source_id"] == edit["source_id"])
        if edit["find"] not in src["content"]:
            raise ValueError(f"perturbation text not found: {edit['find']!r}")
        src["content"] = src["content"].replace(edit["find"], edit["with"])
    if "cutoff" in edit:
        c["record_cutoff"] = edit["cutoff"]
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A2")
    ap.add_argument("--name", default="perturb")
    ap.add_argument("--mock", action="store_true", help="force the offline mock model even if .env configures a real endpoint")
    a = ap.parse_args(argv)
    cfg = load_config()
    if a.mock or not cfg.api_base:
        cfg.api_base = "mock://"
    cfg.pipeline, cfg.max_calls_per_case = a.variant.upper(), BUDGET[a.variant.upper()]
    cfg.output_field_map, cfg.output_fields = {}, []
    pipe = Pipeline(cfg, LLMClient(cfg))
    by_id = {c["case"]["case_id"]: c for c in load_eval_cases()}
    rows, detail = [], []
    for p in json.loads((HERE / "perturbations.json").read_text("utf-8")):
        item = by_id[p["base"]]
        base = parse_case(item["case"], 0, cfg.cutoff_mode)
        new = parse_case(apply_edit(item["case"], p["edit"]), 0, cfg.cutoff_mode)
        r_base = pipe.run_case(base).record
        res, diff = run_update(pipe, base, new)
        r_new = res.record
        pres = [(d, bool(re.search(rx, M.scope_text(r_new, sc)))) for d, rx, sc in p["expect_present"]]
        absn = [(d, not re.search(rx, M.scope_text(r_new, sc))) for d, rx, sc in p["expect_absent"]]
        hb, hn = M.key_fact_hits(r_base, item["annotation"]), M.key_fact_hits(r_new, item["annotation"])
        lost = [k for k in hb if hb[k] and not hn[k] and k not in p.get("may_drop", [])]
        rows.append({"perturbation": p["id"], "base": p["base"], "status": res.status,
                     "ledger_detected_change": bool(diff and diff["changed"]),
                     "present": f"{sum(ok for _, ok in pres)}/{len(pres)}", "absent": f"{sum(ok for _, ok in absn)}/{len(absn)}",
                     "invariant_facts_lost": len(lost),
                     "pass": all(ok for _, ok in pres + absn) and not lost})
        detail.append({"id": p["id"], "failed_present": [d for d, ok in pres if not ok], "failed_absent": [d for d, ok in absn if not ok],
                       "lost_facts": lost, "diff": diff, "base_output": r_base, "perturbed_output": r_new})
    out = HERE / "results" / a.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "perturbation_detail.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), "utf-8")
    table = md_table(rows)
    mock = cfg.api_base.startswith("mock")
    (out / "perturbation_summary.md").write_text(
        f"# Perturbation tests ({a.variant}, model `{cfg.model or '<mock>'}`)\n\n"
        + ("**MOCK MODEL** - the mock does not reason, so reasoning-level expectations are expected to fail; "
           "this run only checks the mechanics (change detection, cutoff, invariance).\n\n" if mock else "") + table + "\n", "utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
