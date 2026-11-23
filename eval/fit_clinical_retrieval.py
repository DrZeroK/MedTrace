"""Fit a local ranking profile and inventory all canonical case inputs under data/."""

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import subprocess

from medtrace.inputs import parse_case
from medtrace.knowledge import digest_file, validate_entry
from medtrace.ranking_profile import fit_anchor_weights
from medtrace.runner import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = Path("data/synthetic_admissions_100_20261117/input_100_final.json")
REVIEWED = Path("data/input_review_20261118/input.json")
DATASETS = ("cmb_clin", "typicalcase_dc")


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
                    if (row.get("source_kind") not in {"guideline", "consensus"}
                            or row.get("population") not in {"adult", "nonpregnant_adult", "pediatric", "pregnancy", "general"}
                            or any(not str(row.get(k, "")).strip() for k in
                                   ("publisher", "specialty", "disease", "version_checked_at"))):
                        raise ValueError(f"incomplete evidence provenance: {row['id']}")
                    date.fromisoformat(row["version_checked_at"])
                guides[row["id"]] = row
    if not guides:
        raise ValueError("no evidence cards")
    return guides


def inventory(root):
    raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "--", "data"])
    paths = [Path(item.decode("utf-8")) for item in raw.split(b"\0") if item]
    counts = Counter("/".join(p.parts[:3] if p.parts[1] == "standardized" else p.parts[:2]) for p in paths)
    return {"tracked_files": len(paths), "tracked_groups": dict(sorted(counts.items())),
            "missing_sparse_checkout_files": sum(not (root / path).is_file() for path in paths)}


def fit(root, guide_paths):
    original = intake(read(root, SYNTHETIC))
    reviewed = intake(read(root, REVIEWED))
    if set(reviewed) != set(original):
        raise ValueError("original and review batches must refer to the same synthetic cases")
    cards = read_guides(guide_paths)
    vocabulary = {alias for card in cards.values() for alias in card.get("aliases", [])}

    audit = {"inventory": inventory(root), "synthetic": {"original": len(original), "reviewed": len(reviewed),
             "trained_unique": len(reviewed), "revision_policy": "prefer reviewed input per case ID"}}
    audit["external"] = {}
    for name in DATASETS:
        folder = Path("data/standardized") / name
        cases = intake(read(root, folder / "cases.json"), strict=False)
        refs = read(root, folder / "references.json")
        if len(cases) != len(refs) or set(cases) != {r["case_id"] for r in refs}:
            raise ValueError(f"case/reference IDs do not match for {name}")
        audit["external"][name] = {
            "audited_for_evaluation": len(cases),
            "split": dict(sorted(Counter(r["split"] for r in refs).items())),
            "diagnosis_metric_eligible": sum(bool(r["derived"]["dx_metric_eligible"]) for r in refs),
            "without_official_input_schema": sum(bool(case.protocol_errors) for case in cases.values()),
            "trained": 0,
        }
    return {
        "format": "clinical-anchor-idf-v1",
        "case_count": len(reviewed),
        "training_input_sha256": digest_file(root / REVIEWED),
        "guides": {p.name: digest_file(p) for p in guide_paths},
        "anchored_vocabulary_count": len(vocabulary),
        "anchor_weights": fit_anchor_weights(reviewed.values(), vocabulary),
    }, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--guides", type=Path, action="append")
    args = parser.parse_args()
    paths = args.guides or sorted((ROOT / "knowledge").glob("guidelines.v*.jsonl"))
    profile, audit = fit(ROOT, paths)
    atomic_write_json(str(args.output), profile)
    atomic_write_json(str(args.audit), audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
