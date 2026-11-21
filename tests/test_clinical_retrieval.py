"""Regression checks for offline ranking and local textbook release boundaries."""

import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from eval.rag_benchmark import benchmark
from medtrace.knowledge import KnowledgeBase, KnowledgeError, build_database
from scripts.textbook_kb import organize_drafts
from test_knowledge import entry


class ClinicalRetrievalTests(unittest.TestCase):
    def test_offline_guideline_relevance(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network disabled")):
            result = benchmark()
        baseline = result["modes"]["bm25"]["at_k"][5]
        reranked = result["modes"]["reranked"]["at_k"][5]
        self.assertEqual(result["queries"], 50)
        self.assertGreater(reranked["recall"], .90)
        self.assertLess(reranked["irrelevant_ratio"], baseline["irrelevant_ratio"])
        self.assertEqual(reranked["negative_abstention"], 1)

    def test_structured_query_and_negation_for_approved_cards(self):
        with TemporaryDirectory() as directory:
            db = Path(directory) / "fixture.sqlite"
            build_database([entry(source_id="fixture-v1", categories=["tests"])], db, "fixture")
            kb = KnowledgeBase(db)
            with patch.object(socket, "socket", side_effect=AssertionError("network disabled")):
                hits = kb.retrieve({"history": "50岁", "labs": "potassium 5 mmol/L"}, categories=["tests"])
                self.assertEqual(hits[0]["source_id"], "fixture-v1")
                self.assertIn("potassium", hits[0]["matched_terms"])
                self.assertEqual(kb.retrieve("50岁，未提供：potassium"), [])
                self.assertEqual(kb.retrieve("50岁 potassium", categories=["treatment"]), [])
                self.assertEqual(kb.retrieve("50岁 potassium1"), [])

    def test_textbook_rechunking_preserves_location_and_draft_status(self):
        content = ("这是为测试合成的较长段落，用于校验小节拆分。" * 38
                   + "检验检出限为0.65 μmol/L。")
        original = entry(text=content, status="draft", license="pending", source_id="fixture-v10",
                         structure={"chapter": "第一章", "label": "【诊断与鉴别诊断】"})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source.write_text(json.dumps(original) + "\n", encoding="utf-8")
            output = root / "cards.jsonl"
            stats = organize_drafts(source, output)
            cards = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertGreater(stats["chunks"], 1)
            self.assertTrue(any("0.65 μmol/L" in card["text"] for card in cards))
            for card in cards:
                self.assertEqual(card["parent_id"], original["id"])
                self.assertEqual(card["locator"], original["locator"])
                self.assertEqual(card["categories"], ["differential", "diagnosis"])
                self.assertEqual(card["source_id"], "fixture-v10")
            with self.assertRaisesRegex(KnowledgeError, "no approved entries"):
                build_database(cards, root / "release.sqlite", "draft")
