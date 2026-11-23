"""Compare baseline and fitted ranking on locally mapped TypicalCase diagnoses."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
from unittest.mock import patch

from eval.fit_clinical_retrieval import ROOT, intake, read
from eval.textbook_rag import TextbookIndex
from medtrace.ledger import build_ledger
from medtrace.retrieval import case_query
from medtrace.runner import atomic_write_json
from medtrace.textutil import fw

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


def label_key(name):
    key = "".join(fw(name).lower().split())
    return SYNONYMS.get(key, key)


def evaluate(index_path, profile_path, root=ROOT):
    indexes = {"baseline": TextbookIndex(index_path), "fitted": TextbookIndex(index_path, profile_path)}
    by_diagnosis = defaultdict(set)
    for row in indexes["baseline"].guidelines:
        if row.get("disease") and MEASURED_CATEGORIES.intersection(row.get("categories", [])):
            by_diagnosis[label_key(row["disease"])].add(row["source_id"])

    cases = intake(read(root, FOLDER / "cases.json"), strict=False)
    references = read(root, FOLDER / "references.json")
    if set(cases) != {row["case_id"] for row in references} or len(cases) != len(references):
        raise ValueError("case/reference IDs do not match")
    eligible = matched = 0
    scores = {name: {"hits_at_1": 0, "hits_at_5": 0} for name in indexes}
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
            for name, index in indexes.items():
                cards = index.retrieve(query, limit=5, categories=MEASURED_CATEGORIES)
                for k in (1, 5):
                    scores[name][f"hits_at_{k}"] += any(c.get("source_id") in expected for c in cards[:k])
    return {
        "metric": "known diagnosis guideline-source hit; development inputs with nonofficial cutoff schema",
        "cases_audited": len(cases), "diagnosis_eligible": eligible,
        "mapped_cases": matched, "unmapped_eligible": eligible - matched, "scores": scores,
        "index_sha256": indexes["baseline"].sha256,
        "profile_sha256": indexes["fitted"].profile_sha256,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--anchor-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.index, args.anchor_profile)
    atomic_write_json(str(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
