"""Phase 6 - incremental updates: regenerate a note when the records change, telling the model exactly what changed.

    python -m medtrace.update previous_input.json new_input.json --output output.json

Cases are matched by case_id. The diff is computed on the deterministic fact ledger, so it does not
depend on the model. A `<output>.changes.json` file records what was detected for each case.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

from .config import load_config
from .inputs import Case, load_cases
from .ledger import build_ledger
from .llm import LLMClient
from .pipeline import Pipeline
from .knowledge import digest_file, write_audit
from .runner import atomic_write_json, wrap

_norm = lambda s: " ".join(s.lower().split())


def diff_cases(prev: Case, new: Case) -> dict:
    lp, ln = build_ledger(prev), build_ledger(new)
    old = {_norm(f.text) for f in lp.facts}
    cur = {_norm(f.text) for f in ln.facts}
    added = [{"source": f.sid, "text": f.text} for f in ln.facts if _norm(f.text) not in old]
    removed = [{"source": f.sid, "text": f.text} for f in lp.facts if _norm(f.text) not in cur]
    old_conf = {(c["kind"], c["term"]) for c in lp.conflicts}
    conflicts = [c for c in ln.conflicts if (c["kind"], c["term"]) not in old_conf]
    resolved = [u["en"] for u in lp.undocumented if u["key"] not in {x["key"] for x in ln.undocumented}]
    return {"added": added, "removed": removed, "new_conflicts": conflicts, "now_documented": resolved,
            "changed": bool(added or removed)}


def changes_block(d: dict, lang: str = "en") -> str:
    if not d["changed"]:
        return ""
    zh = lang == "zh"
    L = ["\n<changes_since_previous_version>",
         "资料较上一版本有更新。请重新评估所有受影响的结论；未受影响的内容保持不变；不得保留已被新信息否定的结论；新旧信息矛盾且无法判定时列入review_items。"
         if zh else
         "The records have been updated since the previous version of this note. Reassess every conclusion the changes affect; "
         "keep what is unaffected; do not carry forward a conclusion that the new information contradicts; if new and old "
         "information conflict and cannot be reconciled, report both and add a review item."]
    if d["added"]:
        L.append("新增：" if zh else "New or changed statements:")
        L += [f'- ({a["source"]}) {a["text"]}' for a in d["added"][:40]]
    if d["removed"]:
        L.append("已删除或被替换（不得再引用）：" if zh else "Removed or superseded statements (no longer part of the record - do not use):")
        L += [f'- {a["text"]}' for a in d["removed"][:40]]
    if d["new_conflicts"]:
        L.append("新出现的可能矛盾：" if zh else "Newly detected candidate conflicts:")
        L += [f'- {c["term"]}: {c["detail"]}' for c in d["new_conflicts"][:10]]
    L.append("</changes_since_previous_version>\n")
    return "\n".join(L)


def run_update(pipe: Pipeline, prev: Case | None, new: Case):
    d = diff_cases(prev, new) if prev is not None and prev.usable and new.usable else None
    res = pipe.run_case(new, changes=changes_block(d, new.lang) if d else "")
    return res, d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("previous")
    ap.add_argument("new")
    ap.add_argument("--output", default="output.json")
    a = ap.parse_args(argv)
    cfg = load_config(output_path=a.output)
    prev_cases, _ = load_cases(a.previous, cfg.cutoff_mode)
    new_cases, envelope = load_cases(a.new, cfg.cutoff_mode)
    prev_by_id = {json.dumps(c.case_id, default=str): c for c in prev_cases}
    pipe = Pipeline(cfg, LLMClient(cfg))
    records, changes, results = [], [], []
    audit_run_id = str(uuid.uuid4())
    if pipe.kb:
        write_audit(a.output, [], pipe.kb, digest_file(a.new), audit_run_id)
    for c in new_cases:
        res, d = run_update(pipe, prev_by_id.get(json.dumps(c.case_id, default=str)), c)
        records.append(res.record)
        results.append(res)
        changes.append({"case_id": c.case_id, "status": res.status, "diff": d})
    atomic_write_json(a.output, wrap(records, envelope, cfg))
    atomic_write_json(a.output + ".changes.json", changes)
    if pipe.kb:
        write_audit(a.output, results, pipe.kb, digest_file(a.new), audit_run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
