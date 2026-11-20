"""Sentence-level fact regression over the frozen second-round outputs.

The saved statement text is replayed through the current verifier. NEG01 citations are
projected onto the split-source fixture: the nurse observation moves from S01 to S02 and
the later sources shift by one.

Counting rules:
- generation error: a statement matching a labelled wrong fact;
- verifier miss: that statement has no finding from the label's expected detector;
- verifier false positive: any other finding, including an unrelated finding on an
  erroneous statement.
"""
from __future__ import annotations

import json
from pathlib import Path

from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger
from medtrace.note import Note, Statement
from medtrace.verify import verify_note

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/followup60_fact_regression.json"

ERRORS = [
    {"case_id": "SYN012", "arm": "plain", "repeat": 1, "section": "diagnostic_discussion",
     "contains": "突发呼吸困难", "caught_by": set()},
    {"case_id": "LONG01", "arm": "json", "repeat": 1, "section": "diagnostic_discussion",
     "contains": "目前无发热及腹痛", "caught_by": set()},
    {"case_id": "NEG01", "arm": "legacy", "repeat": 1, "section": "case_features",
     "contains": "否认胸痛和咯血", "caught_by": {"negation_flip"}},
    {"case_id": "NEG01", "arm": "legacy", "repeat": 2, "section": "case_features",
     "contains": "否认胸痛和咯血", "caught_by": {"negation_flip"}},
]

_NEG01_NURSE = "护士今晨观察到少量咯血"


def _cases():
    from eval.followup_fixtures import cases_from
    reviewed = json.loads((ROOT / "data/input_review_20261118/input.json").read_text("utf-8"))
    return cases_from(reviewed)


def project_neg01(statement):
    """Map a round-2 NEG01 citation onto the split-source fixture."""
    text = statement["text"]
    ids = list(statement["source_ids"])
    if text.startswith("护士") and _NEG01_NURSE in text:
        return ["S02" if i == "S01" else {"S02": "S03", "S03": "S04"}.get(i, i) for i in ids]
    if "否认胸痛" in text and "护士" in text:
        return ["S01", "S02"] if ids == ["S01"] else ids
    return [{"S02": "S03", "S03": "S04"}.get(i, i) for i in ids]


def _sections(output):
    sections = json.loads(json.dumps(output["sections"], ensure_ascii=False))
    if output["case_id"] == "NEG01":
        for name, statements in sections.items():
            sections[name] = [{**st, "source_ids": project_neg01(st)} for st in statements]
    return sections


def _note(sections):
    note = Note()
    for name, statements in sections.items():
        note.sections[name] = [Statement(st["text"], list(st["source_ids"]), basis=st.get("basis", ""),
                                         knowledge_ids=list(st.get("knowledge_ids", [])))
                               for st in statements]
    return note


def replay(output, cases):
    case = parse_case(cases[output["case_id"]], 0, "redact")
    mode = "zh_context_v1" if output["case_id"] == "NEG01" and output["arm"] == "context" else "legacy"
    ledger = build_ledger(case, context_mode=mode)
    ledger.knowledge_cards = {card["id"]: card for card in output.get("injected_cards", [])}
    sections = _sections(output)
    return sections, verify_note(_note(sections), case, ledger)


def evaluate():
    cases = _cases()
    outputs = json.loads(FIXTURE.read_text("utf-8"))["outputs"]
    wanted = {(e["case_id"], e["arm"], e["repeat"]): e for e in ERRORS}
    seen = set()
    generation_errors = misses = false_positives = 0
    details = []
    for output in outputs:
        key = (output["case_id"], output["arm"], output["repeat"])
        sections, findings = replay(output, cases)
        labels = []
        if key in wanted:
            label = wanted[key]
            cells = [(name, i) for name, statements in sections.items()
                     for i, st in enumerate(statements)
                     if name == label["section"] and label["contains"] in st["text"]]
            if len(cells) != 1:
                raise ValueError(f"expected one error statement for {key}, found {len(cells)}")
            labels.append((cells[0], label["caught_by"]))
            seen.add(key)
        error_cells = dict(labels)
        output_misses = output_fp = 0
        for cell, caught_by in labels:
            generation_errors += 1
            if not any((f.section, f.index) == cell and f.code in caught_by for f in findings):
                misses += 1
                output_misses += 1
        for finding in findings:
            if finding.code in error_cells.get((finding.section, finding.index), set()):
                continue
            false_positives += 1
            output_fp += 1
        if output["case_id"] != "NEG01":
            saved = sorted((f["code"], f["section"], f["index"]) for f in output["round2_findings"])
            now = sorted((f.code, f.section, f.index) for f in findings)
            if saved != now:
                raise ValueError(f"round-2 replay drift for {key}: {saved} != {now}")
        details.append({"case_id": output["case_id"], "arm": output["arm"], "repeat": output["repeat"],
                        "findings": [f.as_dict() for f in findings],
                        "generation_errors": len(labels), "misses": output_misses,
                        "false_positives": output_fp})
    missing = set(wanted) - seen
    if missing:
        raise ValueError(f"missing labelled outputs: {sorted(missing)}")
    return {"generation_errors": generation_errors, "verifier_misses": misses,
            "verifier_false_positives": false_positives, "outputs": details}


def main():
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
