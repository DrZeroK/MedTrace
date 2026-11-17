"""Re-run the deterministic verifier on the saved outputs of a run - no model calls.

    python -m eval.reverify eval/results/<run> [--show high|medium] [--variant A0]

Use it to measure the verifier's behaviour on real model prose after changing a rule: the notes are fixed,
only the rules change, so differences are attributable to the rules alone.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

from medtrace import verify as V
from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger
from medtrace.note import SECTIONS, Note, Statement
from medtrace.textutil import strip_enum


def note_from_record(rec: dict) -> Note:
    src = {(e["section"], e["statement"]): [str(i) for i in e["source_ids"]] for e in rec.get("evidence", [])}
    n = Note()
    for sec in SECTIONS:
        for line in str(rec.get(sec, "")).split("\n"):
            t = strip_enum(line)
            if t:
                n.sections[sec].append(Statement(t, src.get((sec, t), [])))
    n.review_items = [dict(r) for r in rec.get("review_items", [])]
    return n


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    run = Path(argv[0])
    show = argv[argv.index("--show") + 1] if "--show" in argv else ""
    only = argv[argv.index("--variant") + 1] if "--variant" in argv else ""
    cases = {c["case"]["case_id"]: c["case"] for c in json.loads((run / "cases_used.json").read_text("utf-8"))}
    for f in sorted(run.glob("outputs_*.json")):
        v = f.stem.split("_", 1)[1]
        if only and v != only:
            continue
        counts, notes_high, n = collections.Counter(), 0, 0
        for rec in json.loads(f.read_text("utf-8")):
            case = parse_case(cases[rec["case_id"]], 0)
            L = build_ledger(case)
            note = note_from_record(rec)
            fs = [x for x in V.verify_note(note, case, L) + V.omission_findings(note, L) if x.code not in ("invalid_ref", "missing_ref")]
            n += 1
            notes_high += any(x.severity == V.HIGH for x in fs)
            for x in fs:
                if x.severity != V.LOW:
                    counts[(x.severity, x.code)] += 1
                    if show and x.severity == show:
                        print(f"  {v} {rec['case_id']} {x.code}: {x.text[:110]!r} | {x.message[:110]}")
        print(f"{v}: notes={n} notes_with_high={notes_high} " + ", ".join(f"{s}:{c}={k}" for (s, c), k in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
