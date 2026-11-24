"""Formatting regressions use self-authored data and a local stub, never inference."""
import hashlib
import json
import unittest

from medtrace.config import Config
from medtrace.inputs import parse_case
from medtrace.llm import LLMClient
from medtrace.note import ParseError, parse_json_object
from medtrace.pipeline import Pipeline
from eval.response_metrics import observe_response

CASE = {"case_id": "format-regression", "record_cutoff": "T0", "sources": [
    {"source_id": "S", "content": "记录使用药物甲10mg后缓解。"}]}
# Unrecoverable by the parser (missing comma between fields), so the regeneration path is exercised.
# A mixed-quote reply ('使用“药物甲10mg"后缓解') is now repaired in the parser; see test_medtrace Parsing.
BAD = '{"case_features":[{"text":"使用药物甲10mg后缓解。" "sources":["S"]}]}'
GOOD = {"case_features": [{"text": "记录使用药物甲10mg后缓解。", "sources": ["S"]}],
        "diagnostic_discussion": [{"text": "建议核实原始用药记录。", "sources": ["S"]}],
        "treatment_plan": [{"text": "建议复核用药情况。", "sources": ["S"]}]}


class GenerationRecovery(unittest.TestCase):
    def test_observation_preserves_recovery_requests_and_results(self):
        complete = json.dumps(GOOD, ensure_ascii=False)
        missing = json.dumps({"case_features": GOOD["case_features"]})
        empty = json.dumps({**GOOD, "treatment_plan": []})
        for raw, strict, object_json, recover in (
            (missing, True, True, True), (empty, True, True, True),
            (BAD, False, False, True), ("[]", True, False, True),
            (missing, True, True, False),
        ):
            for limit in (1, 2):
                with self.subTest(raw=raw, recover=recover, limit=limit):
                    def run(observed):
                        sent, metrics = [], []
                        def transport(url, headers, payload, timeout):
                            sent.append(payload)
                            reply = raw if len(sent) == 1 or not recover else complete
                            body = json.dumps({"choices": [{"message": {"content": reply}}]})
                            if observed:
                                metrics.append(observe_response(200, body))
                            return 200, body
                        cfg = Config(endpoint="http://127.0.0.1/stub", model="stub", repair_call=False,
                                     max_retries=0, max_calls_per_case=limit)
                        output = Pipeline(cfg, LLMClient(cfg, transport=transport)).run_case(parse_case(CASE, 0))
                        return sent, output.record, metrics
                    base, corrected, _ = run(False)
                    sent, final, metrics = run(True)
                    self.assertEqual(sent, base)
                    self.assertEqual(final, corrected)
                    self.assertEqual(len(metrics), limit)
                    self.assertTrue(metrics[0]["http_success"])
                    self.assertEqual(metrics[0]["strict_json"], strict)
                    self.assertEqual(metrics[0]["json_object"], object_json)
                    self.assertFalse(metrics[0]["three_sections"])
                    self.assertEqual(final["status"], "success" if recover and limit == 2 else "failed")
                    if limit == 2:
                        self.assertEqual(metrics[1]["three_sections"], recover)

    def test_parser_reports_location_without_copying_medical_text(self):
        with self.assertRaises(ParseError) as error:
            parse_json_object(BAD)
        message = str(error.exception)
        self.assertIn("Expecting ',' delimiter", message)
        self.assertIn("line 1", message)
        self.assertNotIn("药物甲", message)

    def test_second_call_corrects_format_and_preserves_request_budget(self):
        requests, responses = [], []
        def transport(url, headers, payload, timeout):
            requests.append(payload)
            content = BAD if len(requests) == 1 else json.dumps(GOOD, ensure_ascii=False)
            body = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]})
            responses.append(body)
            return 200, body
        cfg = Config(development=True, endpoint="http://127.0.0.1/stub", model="test", repair_call=False, max_retries=0)
        result = Pipeline(cfg, LLMClient(cfg, transport=transport)).run_case(parse_case(CASE, 0))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.log["http_attempts"], 2)
        first, second = [r["messages"][1]["content"] for r in requests]
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith(first))
        self.assertIn("双引号", second[len(first):])
        self.assertIn("T0", second)
        self.assertIn("药物甲10mg", first)
        self.assertEqual([r["seed"] for r in requests], [37, 37])
        attempt = result.log["attempts"][0]
        self.assertEqual(attempt["finish_reason"], "stop")
        self.assertEqual(attempt["content_characters"], len(BAD))
        self.assertEqual(attempt["response_sha256"], hashlib.sha256(responses[0].encode()).hexdigest())
        self.assertNotIn("药物甲", json.dumps(result.log["attempts"], ensure_ascii=False))

    def test_format_correction_cannot_exceed_one_call_allowance(self):
        calls = []
        def transport(*args):
            calls.append(1)
            return 200, json.dumps({"choices": [{"message": {"content": BAD}}]})
        cfg = Config(development=True, endpoint="http://127.0.0.1/stub", model="test", repair_call=False,
                     max_retries=0, max_calls_per_case=1)
        result = Pipeline(cfg, LLMClient(cfg, transport=transport)).run_case(parse_case(CASE, 0))
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.record["status"], "failed")
        self.assertEqual(len(calls), 1)
