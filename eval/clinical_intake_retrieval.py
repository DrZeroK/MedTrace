"""Measure retrieval on locally mapped TypicalCase diagnoses and validate draft guideline cards."""

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import re
from unittest.mock import patch

from eval.textbook_rag import TextbookIndex
from medtrace.inputs import parse_case
from medtrace.knowledge import validate_entry
from medtrace.ledger import build_ledger
from medtrace.retrieval import case_query
from medtrace.runner import atomic_write_json
from medtrace.textutil import fw

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path("data/standardized/typicalcase_dc")
MEASURED_CATEGORIES = {"diagnosis", "differential", "tests"}
# Equivalences for scope-safe diagnosis names. Broader screening and procedure
# cards do not count toward a disease diagnosis hit.
SYNONYMS = {
    "高血压": "成人高血压",
    "原发性高血压": "成人高血压",
    "房颤": "心房颤动",
    "慢阻肺": "慢性阻塞性肺疾病",
    "2型糖尿病": "糖尿病",
    "高血压病3级(极高危)": "成人高血压",
    "高血压3级(很高危组)": "成人高血压",
    "原发性骨质疏松": "原发性骨质疏松症",
}


def read(root, path):
    return json.loads((root / path).read_text(encoding="utf-8"))


def intake(rows, *, strict=True):
    output = {}
    for index, row in enumerate(rows):
        case = parse_case(row, index, "redact")
        if case.case_id in output or not case.usable or (strict and case.protocol_errors):
            raise ValueError(f"invalid or duplicate case at index {index}")
        output[case.case_id] = case
    return output


def read_guides(paths):
    """Draft-corpus checks beyond the release schema: plain text, HTTPS provenance, v2 metadata."""
    guides = {}
    strict = re.compile(r"https?://|<[^>]+>|\.(?:pdf|docx)\b", re.I)
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                validate_entry(row)
                if (row["type"] != "card" or row["id"] in guides or not row.get("source_id")
                        or not row.get("categories") or strict.search(row["text"])
                        or len(row["text"]) > 800 or not re.match(r"https://", row.get("source_url", ""))):
                    raise ValueError(f"invalid clinical evidence card: {row['id']}")
                if path.name == "guidelines.v2.jsonl":
                    if (row.get("source_kind") not in {"guideline", "consensus"} or "population" not in row
                            or any(not str(row.get(k, "")).strip() for k in
                                   ("publisher", "specialty", "disease", "version_checked_at"))):
                        raise ValueError(f"incomplete evidence provenance: {row['id']}")
                    date.fromisoformat(row["version_checked_at"])
                guides[row["id"]] = row
    if not guides:
        raise ValueError("no evidence cards")
    return guides


def label_key(name):
    key = "".join(fw(name).lower().split())
    return SYNONYMS.get(key, key)


def evaluate(index_path, root=ROOT):
    index = TextbookIndex(index_path)
    by_diagnosis = defaultdict(set)
    for row in index.guidelines:
        if row.get("disease") and MEASURED_CATEGORIES.intersection(row.get("categories", [])):
            by_diagnosis[label_key(row["disease"])].add(row["source_id"])

    cases = intake(read(root, FOLDER / "cases.json"), strict=False)
    references = read(root, FOLDER / "references.json")
    if set(cases) != {row["case_id"] for row in references} or len(cases) != len(references):
        raise ValueError("case/reference IDs do not match")
    eligible = matched = 0
    scores = {"hits_at_1": 0, "hits_at_5": 0}
    with patch("socket.socket", side_effect=AssertionError("network disabled")):
        for row in references:
            if not row["derived"]["dx_metric_eligible"]:
                continue
            eligible += 1
            expected = set().union(*(by_diagnosis.get(label_key(diagnosis), set())
                                     for diagnosis in row["reference"]["diagnoses"]))
            if not expected:
                continue
            matched += 1
            query = case_query(build_ledger(cases[row["case_id"]]))
            cards = index.retrieve(query, limit=5, categories=MEASURED_CATEGORIES)
            for k in (1, 5):
                scores[f"hits_at_{k}"] += any(c.get("source_id") in expected for c in cards[:k])
    return {
        "metric": "known diagnosis guideline-source hit; development inputs with nonofficial cutoff schema",
        "cases_audited": len(cases), "diagnosis_eligible": eligible,
        "mapped_cases": matched, "unmapped_eligible": eligible - matched, "scores": scores,
        "index_sha256": index.sha256,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.index)
    atomic_write_json(str(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
