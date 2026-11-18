import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from eval.experiment import RequestBudget
from eval.followup import FollowupBudget, planned_jobs
from medtrace.llm import BudgetExceeded, CallStats, LLMClient
from medtrace.config import Config


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="medtrace-budget-test-"))

    def test_budget_is_charged_before_dispatch_and_resume_keeps_it(self):
        def post(*args):
            journal = [json.loads(l) for l in (self.d / "requests.jsonl").read_text().splitlines()]
            self.assertEqual(journal[-1]["event"], "reserved")
            return 200, '{"choices":[{"message":{"content":"{}"}}],"usage":{"total_tokens":3}}'
        with RequestBudget(self.d, {"test": 1}) as budget, patch("medtrace.llm._post", side_effect=post):
            c = Config(development=True, output_protocol="legacy", endpoint="http://127.0.0.1/test", model="test", max_retries=0)
            LLMClient(c, transport=budget.post).chat("s", "u", CallStats())
            self.assertEqual(budget.used(), 1)
        with RequestBudget(self.d, {"test": 1}) as budget:
            self.assertEqual(budget.used(), 1)
        with self.assertRaises(ValueError):
            RequestBudget(self.d, {"test": 2})

    def test_stage_caps_reserve_confirmation_and_reject_attempt_301(self):
        with RequestBudget(self.d, {}) as budget, patch("medtrace.llm._post", return_value=(200, "{}")) as post:
            for _ in range(120):
                budget.post("http://test", {}, {"model": "test"}, 1)
            with self.assertRaises(BudgetExceeded):
                budget.post("http://test", {}, {}, 1)
            budget.stage = "confirmation"
            for _ in range(180):
                budget.post("http://test", {}, {"model": "test"}, 1)
            with self.assertRaises(BudgetExceeded):
                budget.post("http://test", {}, {}, 1)
            self.assertEqual(post.call_count, 300)
        with RequestBudget(self.d, {}) as budget:
            self.assertEqual(budget.used(), 300)
            budget.stage = "confirmation"
            with self.assertRaises(BudgetExceeded):
                budget.post("http://test", {}, {}, 1)

    def test_failure_consumes_budget_and_duplicate_process_is_refused(self):
        with RequestBudget(self.d, {}) as budget:
            with self.assertRaises(ValueError):
                RequestBudget(self.d, {})
            with patch("medtrace.llm._post", side_effect=ConnectionError("synthetic")):
                with self.assertRaises(ConnectionError):
                    budget.post("http://test", {}, {}, 1)
            self.assertEqual(budget.used(), 1)
            self.assertEqual(budget.events[-1]["error_type"], "ConnectionError")

    def test_followup_concurrent_budget_is_global_and_persists(self):
        self.assertEqual(sum(map(len, planned_jobs())), 48)
        def submit(budget, stage, index):
            try:
                budget.post("http://stub", {}, {"model": "test"}, 1, purpose=f"{stage}/{index}", stage=stage)
            except BudgetExceeded:
                return False
            return True
        with FollowupBudget(self.d, {"test": "capped"}) as budget, ThreadPoolExecutor(3) as pool:
            with patch("medtrace.llm._post", return_value=(200, "{}")) as post:
                initial = list(pool.map(lambda i: submit(budget, "development", i), range(60)))
                recovery = list(pool.map(lambda i: submit(budget, "recovery", i), range(10)))
                self.assertEqual((sum(initial), sum(recovery), post.call_count), (52, 8, 60))
        with FollowupBudget(self.d, {"test": "capped"}) as budget:
            self.assertEqual(budget.used(), 60)
            self.assertFalse(submit(budget, "development", 61))
            self.assertFalse(submit(budget, "recovery", 61))

