import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_pipeline.cdee_negation import compare_context
from eval.phase1 import Experiment, load_public_data
from medtrace.config import Config
from medtrace.mock_llm import MockLLM


class PhaseOneTests(unittest.TestCase):
    def test_public_split_is_reproducible_and_disjoint(self):
        items, splits = load_public_data()
        self.assertEqual(splits, load_public_data()[1])
        self.assertEqual([len(splits[k]) for k in ("proposal", "selection", "confirmation")], [18, 8, 30])
        self.assertEqual(len(set(sum([splits[k] for k in ("proposal", "selection", "confirmation")], []))), 56)
        self.assertTrue(all(cid in items for cid in splits["selection"]))

    def test_three_class_scoring_keeps_unlabelled_positive_findings(self):
        result = compare_context([{"text": "患者发热，否认胸痛，考虑肺炎。", "event": [
            {"core_name": "发热", "tendency": ""}, {"core_name": "胸痛", "tendency": "否定"},
            {"core_name": "肺炎", "tendency": "不确定"}]}])
        self.assertEqual(result["zh_context_v1"]["scored"], 3)
        self.assertEqual(result["zh_context_v1"]["macro_f1"], 1)
        self.assertTrue(result["gate"]["same_scored_set"])

    def test_generation_cache_partition_guard_and_resume(self):
        directory = Path(tempfile.mkdtemp(prefix="medtrace-phase1-test-"))
        cfg = Config(development=True, api_base="http://127.0.0.1/v1", model="test")
        mock = MockLLM()
        def post(url, headers, payload, timeout):
            return 200, json.dumps({"choices": [{"message": {"content": mock.complete(payload["messages"])}}]})
        with patch("medtrace.llm._post", side_effect=post) as transport:
            experiment = Experiment(directory, cfg)
            try:
                with self.assertRaises(ValueError):
                    experiment.generate(experiment.splits["confirmation"][0], "legacy")
                cid = experiment.splits["selection"][0]
                first = experiment.generate(cid, "zh_context_v1")
                self.assertEqual(first, experiment.generate(cid, "zh_context_v1"))
                self.assertTrue(first["metrics"]["valid"])
                self.assertEqual(transport.call_count, 1)
                experiment.report()
            finally:
                experiment.close()
            experiment = Experiment(directory, cfg)
            try:
                self.assertEqual(first, experiment.generate(cid, "zh_context_v1"))
                self.assertEqual(experiment.budget.used(), 1)
            finally:
                experiment.close()

    @unittest.skipUnless(importlib.util.find_spec("dspy"), "optional DSPy development dependency is absent")
    def test_real_mipro_uses_only_budgeted_transport_and_selection_cases(self):
        from eval.optimize_prompt import optimize
        directory = Path(tempfile.mkdtemp(prefix="medtrace-mipro-test-"))
        cfg = Config(development=True, api_base="http://127.0.0.1/v1", model="test")
        proposed = "按问题分组组织病历，保留全部原始事实、证据引用与固定JSON协议。"
        def post(*args):
            prompt = args[2]["messages"][0]["content"]
            field = "proposed_instruction" if "proposed_instruction" in prompt else "summary" if "summary" in prompt else "observations"
            text = f"[[ ## {field} ## ]]\n{proposed}\n[[ ## completed ## ]]"
            return 200, json.dumps({"choices": [{"message": {"content": text}}]})
        experiment = Experiment(directory, cfg)
        calls = []
        def generate(cid, mode, instruction):
            self.assertIn(cid, experiment.splits["selection"])
            self.assertEqual(mode, "zh_context_v1")
            experiment.candidate(instruction)
            calls.append(cid)
            return {"metrics": {"score": 0.5}, "record": {}}
        try:
            with patch("medtrace.llm._post", side_effect=post) as transport, patch.object(experiment, "generate", side_effect=generate):
                result = optimize(experiment)
                self.assertTrue(result)
                self.assertTrue(calls)
                self.assertGreater(transport.call_count, 0)
                self.assertEqual(transport.call_count, experiment.budget.used())
                count = transport.call_count
                self.assertEqual(optimize(experiment), result)
                self.assertEqual(transport.call_count, count)
        finally:
            experiment.close()
