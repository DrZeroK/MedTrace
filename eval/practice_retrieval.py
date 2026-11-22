"""Local-only topic coverage check for a ClinNote practice ZIP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from unittest.mock import patch
from zipfile import ZipFile

from eval.textbook_rag import TextbookIndex
from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger
from medtrace.retrieval import case_query

_HEADING = re.compile(r"[:：]")
_END = {"病史小结", "初步诊断", "出院诊断", "记录医师", "医师签名", "医生签名"}


def _intake(content):
    """Keep only the clinical intake preceding the first summary/diagnosis heading."""
    lines = []
    demographics = []
    started = False
    for raw in content.splitlines():
        line = raw.strip()
        key = re.sub(r"\s+", "", _HEADING.split(line, maxsplit=1)[0])
        if key in _END:
            if not started:
                raise ValueError("practice chart summary preceded the chief complaint")
            return demographics + lines
        if key == "主诉":
            started = True
        if started and line:
            lines.append(line)
        elif key in {"年龄", "性别"}:
            demographics.append(line)
    raise ValueError("practice chart lacks a recognized cutoff heading")


def evaluate(index_path, archive_path, labels):
    index = TextbookIndex(index_path)
    if index.describe()["state"] != "draft":
        raise ValueError("practice evaluation expects the local draft index")
    samples = []
    seen = set()
    with ZipFile(archive_path) as archive, patch("socket.socket", side_effect=AssertionError("network disabled")):
        for member in sorted(archive.infolist(), key=lambda item: item.filename):
            name = member.filename.rsplit("/", 1)[-1]
            match = re.match(r"^(\d{2})_.*\.txt$", name)
            if member.is_dir() or not match:
                continue
            sample_id = match[1]
            if sample_id not in labels or sample_id in seen:
                raise ValueError("unexpected or duplicate practice chart ID")
            seen.add(sample_id)
            lines = _intake(archive.read(member).decode("utf-8-sig"))
            intake = {"case_id": sample_id, "record_cutoff": "T0",
                      "sources": [{"source_id": f"S{i:03d}", "content": line} for i, line in enumerate(lines, 1)]}
            ledger = build_ledger(parse_case(intake, len(samples)))
            result = index.retrieve(case_query(ledger))
            coverage = {}
            for topic, pattern in labels[sample_id].items():
                coverage[topic] = next((rank for rank, card in enumerate(result, 1)
                                        if re.search(pattern, card["title"])), None)
            samples.append({"sample_id": sample_id, "topic_first_rank": coverage,
                            "retrieved_evidence_ids": [card["id"] for card in result]})
    if seen != set(labels):
        raise ValueError("practice ZIP does not contain the labeled practice charts")
    ranks = [rank for sample in samples for rank in sample["topic_first_rank"].values()]
    return {
        "index_sha256": index.sha256,
        "sample_count": len(samples),
        "topic_count": len(ranks),
        "topics_hit_at_1": sum(rank == 1 for rank in ranks),
        "topics_hit_at_5": sum(rank is not None for rank in ranks),
        "samples_with_topic_at_5": sum(any(rank is not None for rank in sample["topic_first_rank"].values())
                                       for sample in samples),
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    report = json.dumps(evaluate(args.index, args.archive, labels), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
