import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from medtrace.config import Config
from medtrace.inputs import load_cases
from medtrace.llm import LLMClient
from medtrace.note import official_schema_errors
from medtrace.pipeline import Pipeline


SOURCE_ID = "ADMISSION-01"
SOURCE_TEXT = "The patient reported a headache on admission."


def response(content, usage=None):
    return 200, json.dumps({
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": 17} if usage is None else usage,
    })


class ResponseIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps([{
                "case_id": "response-isolation",
                "record_cutoff": "T0",
                "sources": [{"source_id": SOURCE_ID, "content": SOURCE_TEXT}],
            }]), encoding="utf-8")
            cases, _ = load_cases(str(path), "redact")
        cls.case = cases[0]
        cls.model_source_id = cls.case.sources[0].sid

    def model_note(self, **overrides):
        return {
            "case_features": [{"text": SOURCE_TEXT, "sources": [self.model_source_id]}],
            "diagnostic_discussion": ["The cause of the symptom remains uncertain."],
            "treatment_plan": ["Review the admission history."],
            **overrides,
        }

    def run_case(self, *replies):
        cfg = Config(endpoint="http://127.0.0.1:1/v1/chat/completions", model="fixture",
                     repair_call=False, retry_backoff=0)
        transport = Mock(side_effect=replies)
        result = Pipeline(cfg, LLMClient(cfg, transport=transport)).run_case(self.case)
        self.assertEqual([], official_schema_errors(result.record, {SOURCE_ID}))
        self.assertEqual(transport.call_count, result.log["http_attempts"])
        return result

    def test_malformed_optional_fields_preserve_the_record(self):
        clean = self.run_case(response(json.dumps(self.model_note())))
        self.assertEqual("success", clean.record["status"])
        for field, invalid in (("review_items", 17), ("review_items", "stray text"),
                               ("evidence", True), ("evidence", {"text": "wrong container"})):
            with self.subTest(field=field, invalid=invalid):
                result = self.run_case(response(json.dumps(self.model_note(**{field: invalid}))))
                self.assertEqual(clean.record, result.record)
                self.assertEqual({field: 1}, result.log["optional_fields_dropped"])
                self.assertEqual((1, 1), (result.log["calls"], result.log["http_attempts"]))

    def test_malformed_entries_do_not_discard_valid_siblings(self):
        reviews = ["Confirm the patient history."]
        evidence = [{"statement": SOURCE_TEXT, "section": "case_features", "source_ids": [self.model_source_id]}]
        clean = self.run_case(response(json.dumps(self.model_note(review_items=reviews, evidence=evidence))))
        mixed = self.model_note(review_items=[10, *reviews, {"text": {"unexpected": True}}],
                                evidence=[False, *evidence, {"statement": 3}])
        result = self.run_case(response(json.dumps(mixed)))
        self.assertEqual("success", clean.record["status"])
        self.assertIn( f"[Confirm] {reviews[0]}", clean.record["medical_record"]["review_items"])
        self.assertEqual(clean.record, result.record)
        self.assertEqual([{"section": "case_features", "statement": SOURCE_TEXT,
                           "source_ids": [self.model_source_id]}], result.note.extra_evidence)
        self.assertEqual({"review_items": 2, "evidence": 2}, result.log["optional_fields_dropped"])

    def test_unusable_token_counts_do_not_discard_valid_content(self):
        content = json.dumps(self.model_note())
        code, body = response(content, {
            "total_tokens": "overflow-marker",
            "completion_tokens_details": {"reasoning_tokens": "overflow-marker"},
            "prompt_tokens_details": {"cached_tokens": "overflow-marker"},
        })
        result = self.run_case((code, body.replace('"overflow-marker"', "1e400")))
        self.assertEqual("success", result.record["status"])
        self.assertEqual((1, 1), (result.log["calls"], result.log["http_attempts"]))
        self.assertEqual(1, result.log["usage_missing"])
        self.assertEqual(0, result.log["total_tokens"])
        self.assertEqual(0, result.log["reasoning_tokens"])
        self.assertEqual(0, result.log["cached_tokens"])

        result = self.run_case(response(content, {"prompt_tokens": 12, "completion_tokens": 5.0}))
        self.assertEqual("success", result.record["status"])
        self.assertEqual(0, result.log["usage_missing"])
        self.assertEqual(17, result.log["total_tokens"])

    def test_invalid_content_part_uses_existing_transport_retry(self):
        result = self.run_case(response([{"text": None}]), response([{"text": json.dumps(self.model_note())}]))
        self.assertEqual("success", result.record["status"])
        self.assertEqual((1, 2), (result.log["calls"], result.log["http_attempts"]))
        self.assertEqual(1, result.log["retries"])

    def test_missing_required_section_uses_existing_regeneration(self):
        incomplete = self.model_note(review_items=17)
        del incomplete["treatment_plan"]
        first = response(json.dumps(incomplete))
        result = self.run_case(first, response(json.dumps(self.model_note())))
        self.assertEqual("success", result.record["status"])
        self.assertEqual((2, 2), (result.log["calls"], result.log["http_attempts"]))
        self.assertEqual(1, len(result.log["parse_errors"]))
        failed = self.run_case(first, first)
        self.assertEqual("failed", failed.record["status"])
        self.assertIsNone(failed.record["medical_record"])
        self.assertEqual((2, 2), (failed.log["calls"], failed.log["http_attempts"]))

    def test_missing_traceable_evidence_remains_a_failure(self):
        result = self.run_case(response(json.dumps(self.model_note(case_features=[SOURCE_TEXT], evidence=True))))
        self.assertEqual("failed", result.record["status"])
        self.assertIsNone(result.record["medical_record"])
        self.assertEqual("INVALID_OUTPUT", result.record["error"]["code"])
