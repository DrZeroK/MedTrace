"""Score the experimental guideline corpus with the same offline ranking as MedTrace."""

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from medtrace.knowledge import adult_documented, alias_hit, digest_file, index_card, search_tokens, validate_entry
from medtrace.retrieval import candidates, lexical_tokens, prepare_query, select_cards

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERIES = ROOT / "eval" / "retrieval_queries.v1.jsonl"
DEFAULT_CARDS = ROOT / "knowledge" / "guidelines.v1.jsonl"


def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _metrics(rows, k):
    counts = Counter()
    for row in rows:
        expected = set(row["relevant"])
        retrieved = row["retrieved"][:k]
        hits = len(expected.intersection(retrieved))
        if expected:
            counts["positive"] += 1
            counts["recall_sum"] += hits / len(expected)
        else:
            counts["negative"] += 1
            counts["abstained"] += not retrieved
        counts["returned"] += len(retrieved)
        counts["hits"] += hits

    def ratio(value, divisor):
        return round(counts[value] / counts[divisor], 6) if counts[divisor] else None

    precision = ratio("hits", "returned")
    return {
        "recall": ratio("recall_sum", "positive"),
        "evidence_precision": precision,
        "irrelevant_ratio": round(1 - precision, 6) if precision is not None else None,
        "negative_abstention": ratio("abstained", "negative"),
        "returned": counts["returned"],
        "positive": counts["positive"],
        "negative": counts["negative"],
    }


def benchmark(card_path=DEFAULT_CARDS, question_path=DEFAULT_QUERIES):
    cards = read_jsonl(card_path)
    questions = read_jsonl(question_path)
    known_ids = {card["id"] for card in cards}
    if len(known_ids) != len(cards) or not cards or not questions:
        raise ValueError("empty corpus or questions, or duplicate card IDs")
    seen_questions = set()
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE entries(id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        db.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, title, body)")
        for card in cards:
            validate_entry(card)
            if card["type"] != "card":
                raise ValueError("benchmark expects evidence cards")
            db.execute("INSERT INTO entries VALUES (?,?)", (card["id"], json.dumps(card, ensure_ascii=False)))
            index_card(db, card)

        runs = {"bm25": [], "reranked": []}
        for question in questions:
            identifier = question["id"]
            relevant = question["relevant"]
            if identifier in seen_questions or not set(relevant) <= known_ids:
                raise ValueError(f"bad benchmark labels: {identifier}")
            seen_questions.add(identifier)
            clauses, original = prepare_query(question["query"])
            pool = candidates(db, lexical_tokens(clauses, search_tokens))
            for mode, rows in runs.items():
                selected = select_cards(pool, clauses, original, alias_hit=alias_hit,
                                        adult_documented=adult_documented, search_tokens=search_tokens,
                                        categories=question.get("categories"), baseline=mode == "bm25")
                rows.append({"id": identifier, "group": question["group"], "relevant": relevant,
                             "retrieved": [card["id"] for card in selected]})

    return {
        "corpus_sha256": digest_file(card_path), "queries_sha256": digest_file(question_path),
        "cards": len(cards), "sources": len({card["source_id"] for card in cards}),
        "queries": len(questions),
        "annotation_status": "project-authored synthetic development queries; no independent clinical review",
        "modes": {
            mode: {
                "at_k": {k: _metrics(rows, k) for k in (1, 3, 5)},
                "by_group_at_5": {group: _metrics([row for row in rows if row["group"] == group], 5)
                                  for group in sorted({row["group"] for row in rows})},
                "rows": rows,
            }
            for mode, rows in runs.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(benchmark(args.cards, args.queries), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
