import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from eval.blind_review import paired_deltas
from eval.rag_ablation import main, prepare_cases, run
from medtrace.config import Config
from medtrace.knowledge import KnowledgeError
from scripts.textbook_kb import build_index
from test_knowledge import entry


class RagAblationTests(unittest.TestCase):
    def test_mock_pair_and_blind_export(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "cards.jsonl"
            draft.write_text(json.dumps(entry(title="测试胸痛", text="这是合成检索证据。",
                                              scope="general", aliases=["胸痛"], status="draft",
                                              license="pending")), encoding="utf-8")
            sqlite = root / "draft.sqlite"
            build_index(draft, sqlite)
            records = [{"case_id": "test", "record_cutoff": "2026-01-02", "sources": [
                {"source_id": "S1", "content": "主诉：胸痛。"},
                {"source_id": "S2", "time": "2026-01-03", "content": "后续测试结论。"},
            ]}]
            input_path = root / "input.json"
            input_path.write_text(json.dumps(records), encoding="utf-8")
            out = root / "run"
            self.assertEqual(main(["--input", str(input_path), "--index", str(sqlite), "--output", str(out)]), 0)
            m = json.loads((out / "summary.json").read_text("utf-8"))
            self.assertEqual(m["retrieval_context_pairs"], 1)
            self.assertEqual(m["same_base_prompt_pairs"], 1)
            self.assertEqual(m["identical_output_pairs"], 1)
            self.assertEqual(m["paired_successes"], 1)
            self.assertEqual(m["pairs"][0]["rag_on"]["http_attempts"], 0)
            self.assertEqual(m["pairs"][0]["rag_off"]["first_prompt"]["kb_ids"], [])
            packet = (out / "review/packet.md").read_text("utf-8")
            self.assertNotIn("后续测试结论", packet)
            self.assertNotIn("rag_on", packet)
            self.assertNotIn("rag_off", packet)
            self.assertEqual(len(json.loads((out / "review/key.json").read_text("utf-8"))), 2)
            with patch("eval.rag_ablation.load_config", return_value=Config()):
                with self.assertRaises(KnowledgeError):
                    run(prepare_cases(records), sqlite, official=True)

    def test_one_reviewer_one_case_pair_for_deltas(self):
        key = {
            "a": {"case_id": "x", "variant": "rag_off"},
            "b": {"case_id": "x", "variant": "rag_on"},
            "c": {"case_id": "y", "variant": "rag_off"},
            "d": {"case_id": "y", "variant": "rag_on"},
        }
        off = {"reasoning_score": "2", "plan_score": "2", "critical_error": "1",
               "facts_wrong": "2", "facts_assessed": "4"}
        on = {"reasoning_score": "4", "critical_error": "0", "facts_wrong": "1", "facts_assessed": "4"}
        deltas = paired_deltas(key, {"R1": {"a": off, "b": on, "c": off}, "R2": {"d": on}})
        self.assertEqual(deltas["reasoning_score"], [2])
        self.assertEqual(deltas["plan_score"], [])
        self.assertEqual(deltas["factual_error_rate"], [-0.25])
        self.assertEqual(deltas["critical_error"], [-1])
