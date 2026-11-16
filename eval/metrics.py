"""Automatic proxy metrics. These approximate - and never replace - blinded expert review."""
from __future__ import annotations

import json
import random
import re

from medtrace.note import schema_errors

SECS = {"features": ["case_features"], "discussion": ["diagnostic_discussion"], "plan": ["treatment_plan"],
        "note": ["case_features", "diagnostic_discussion", "treatment_plan"]}


def scope_text(rec: dict, scope: str) -> str:
    if scope == "review":
        return "\n".join(r.get("description", "") for r in rec.get("review_items", []))
    return "\n".join(str(rec.get(k, "")) for k in SECS.get(scope, SECS["note"]))


def key_fact_hits(rec: dict, ann: dict) -> dict:
    text = scope_text(rec, "note") + "\n" + scope_text(rec, "review")   # missing-information facts may be met by a review item
    return {fid: bool(re.search(rx, text, re.I)) for fid, rx in ann["key_facts"]}


def must_not_hits(rec: dict, ann: dict) -> list[str]:
    return [desc for desc, rx, scope in ann.get("must_not", []) if re.search(rx, scope_text(rec, scope), re.M)]


def refs_valid(rec: dict, case: dict) -> tuple[int, int]:
    ids = {s["source_id"] for s in case["sources"]}
    refs = [i for e in rec.get("evidence", []) for i in e.get("source_ids", [])]
    refs += [i for r in rec.get("review_items", []) for i in r.get("source_ids", [])]
    return sum(i in ids for i in refs), len(refs)


def fault_survival(rec: dict, fault_log: list) -> list[dict]:
    blob = json.dumps(rec, ensure_ascii=False)
    out = []
    for f in fault_log:
        if f["fault"] == "bad_json" or not f["needle"]:
            continue
        needle = json.dumps(f["needle"], ensure_ascii=False)[1:-1]
        # a statement that survives but is explicitly flagged for clinician verification counts separately
        survived = needle in blob
        flagged = survived and needle[:160] in scope_text(rec, "review").replace("\\", "") if f["fault"] != "invalid_ref" else False
        out.append({"fault": f["fault"], "survived": survived, "flagged": bool(flagged)})
    return out


def is_schema_valid(rec: dict) -> bool:
    return not schema_errors(rec)


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]
