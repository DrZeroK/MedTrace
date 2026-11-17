"""Offline retrieval evaluation; never reads clinical answer/reference datasets."""
import argparse
import json
import math
import statistics
import time
from pathlib import Path

from medtrace.knowledge import KnowledgeBase


def evaluate(kb, questions):
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        got = [e["id"] for e in kb.retrieve(q["query"])]
        elapsed = (time.perf_counter() - t0) * 1000
        gold = set(q["relevant_ids"])
        rows.append({"id": q["id"], "retrieved": got, "relevant_ids": sorted(gold),
                     "recall": len(gold & set(got)) / len(gold) if gold else None,
                     "false_injection": bool(got) if not gold else None, "milliseconds": elapsed})
    answers = [r["recall"] for r in rows if r["recall"] is not None]
    noanswers = [r["false_injection"] for r in rows if r["false_injection"] is not None]
    times = sorted(r["milliseconds"] for r in rows)
    return {"knowledge_version": kb.manifest["version"], "knowledge_sha256": kb.manifest["sha256"],
            "n": len(rows), "answerable": len(answers), "unanswerable": len(noanswers),
            "recall_at_5": statistics.mean(answers) if answers else None,
            "false_injection_rate": statistics.mean(noanswers) if noanswers else None,
            "p95_ms": times[max(0, math.ceil(len(times)*.95)-1)] if times else None, "rows": rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kb-path", required=True)
    p.add_argument("--questions", required=True)
    p.add_argument("--split", choices=["dev", "heldout"], default="dev")
    p.add_argument("--output", required=True)
    a = p.parse_args()
    doc = json.loads(Path(a.questions).read_text("utf-8"))
    kb = KnowledgeBase(a.kb_path)
    report = evaluate(kb, [q for q in doc["questions"] if q["split"] == a.split])
    report.update(split=a.split, annotation_status=doc["annotation_status"])
    from medtrace.runner import atomic_write_json
    atomic_write_json(a.output, report)
    print(json.dumps({k:v for k,v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
