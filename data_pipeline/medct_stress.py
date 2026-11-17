"""Stress-test MedTrace's deterministic text layer on real Chinese clinical note fragments (MedCT-clinical-notes).

    python -m data_pipeline.acquire medct_clinical_notes
    python -m data_pipeline.medct_stress            # -> data/standardized/medct_clinical_notes/stress_report.md

Every fragment is treated as a one-source case and its own sentences are fed back verbatim as Case Features.
Any high/medium verifier finding is therefore a false alarm. The report contains AGGREGATE NUMBERS ONLY: the
notes are real patient text and no excerpt is written outside data/raw/ (git-ignored).
"""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

from medtrace import verify as V
from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger
from medtrace.note import Note, Statement
from . import quality as Q

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "medct_clinical_notes"
OUT = ROOT / "data" / "standardized" / "medct_clinical_notes"


def run(min_chars: int = 15) -> dict:
    csv.field_size_limit(10 ** 9)
    notes = list(csv.DictReader(open(RAW / "medct_ner_notes.csv", encoding="utf-8-sig")))
    seen, frags, pii = set(), [], collections.Counter()
    for n in notes:
        h = Q.text_hash(n["text"])
        if h in seen or len(n["text"].strip()) < min_chars:
            continue
        seen.add(h)
        clean, hits = Q.scrub_pii(n["text"])
        pii.update(hits)
        frags.append((n["note_id"], clean))
    stats = collections.Counter()
    alarms = collections.Counter()
    examples = []
    for nid, text in frags:
        case = parse_case({"case_id": nid, "sources": [{"source_id": "s", "content": text}]}, 0)
        if not case.usable:
            stats["unusable"] += 1
            continue
        L = build_ledger(case)
        stats["statements"] += len(L.facts)
        stats["measurements"] += sum(len(f.numerics) for f in L.facts)
        stats["negative_statements"] += sum(bool(f.neg_terms) for f in L.facts)
        stats["pending_statements"] += len(L.by_polarity("missing"))
        stats["uncertain_statements"] += len(L.by_polarity("uncertain"))
        note = Note()
        note.sections["case_features"] = [Statement(f.text, ["s"]) for f in L.facts]
        for f in V.verify_note(note, case, L):
            if f.code != "empty_section" and f.severity != V.LOW:
                alarms[f.code] += 1
                examples.append({"note_id": nid, "code": f.code, "message": f.message, "text": f.text})
    res = {"raw_fragments": len(notes), "unique_fragments_used": len(frags), "min_chars": min_chars, **stats,
           "false_alarms": dict(alarms), "pii_scrub_hits": dict(pii)}
    OUT.mkdir(parents=True, exist_ok=True)
    (RAW / "stress_false_alarm_examples.json").write_text(json.dumps(examples, ensure_ascii=False, indent=1), "utf-8")  # stays local
    n_fa = sum(alarms.values())
    (OUT / "stress_report.md").write_text("\n".join([
        "# Deterministic-layer stress test on real note fragments (MedCT-clinical-notes)", "",
        "Aggregate statistics only; no note text is reproduced here. Source: TigerResearch/MedCT-clinical-notes (Apache-2.0), real hospital note fragments.", "",
        "| Item | Value |", "|---|---|",
        f"| Fragments in file | {len(notes)} |", f"| Unique fragments of at least {min_chars} characters | {len(frags)} |",
        f"| Sentences produced by the splitter | {stats['statements']} |",
        f"| Unit-bearing measurements recognised | {stats['measurements']} |",
        f"| Sentences with a negation cue | {stats['negative_statements']} |",
        f"| Sentences marked pending / not done | {stats['pending_statements']} |",
        f"| Sentences the record itself marks uncertain | {stats['uncertain_statements']} |",
        f"| **Verifier false alarms on verbatim text (high or medium)** | **{n_fa}** ({dict(alarms) or 'none'}) |",
        f"| Identifier patterns redacted before processing | {dict(pii) or 'none'} |", "",
        "What this does and does not show: the verifier does not raise alarms on faithful real-language text. It says nothing about "
        "whether negation scope and polarity are *correct* (the dataset's entity spans carry no polarity labels), and nothing about model output.", ""]), "utf-8")
    return res


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=1))
