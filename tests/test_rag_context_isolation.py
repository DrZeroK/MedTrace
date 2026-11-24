import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from medtrace.config import Config
from medtrace.inputs import load_cases
from medtrace.llm import LLMClient
from medtrace.note import official_schema_errors
from medtrace.pipeline import Pipeline


SOURCE_ID = "admission"
SOURCE_TEXT = "The patient reported a headache on admission."
RAG_RULE = "Check the synthetic knowledge rule."


def response(obj):
    return 200, json.dumps({"choices": [{"message": {"content": json.dumps(obj)}}]})


class RAGContextIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps([{
                "case_id": "rag-context-isolation",
                "record_cutoff": "T0",
                "sources": [{"source_id": SOURCE_ID, "content": SOURCE_TEXT}],
            }]), encoding="utf-8")
            cases, _ = load_cases(str(path), "redact")
        cls.case = cases[0]
        cls.sid = cls.case.sources[0].sid

    def draft(self, **overrides):
        return {
            "case_features": [{"text": SOURCE_TEXT, "sources": [self.sid]}],
            "diagnostic_discussion": ["The cause of the symptom remains uncertain."],
            "treatment_plan": ["Review the admission history."],
            **overrides,
        }

    def knowledge_base(self, cards, *, rules=()):
        kb = Mock()
        kb.retrieve.return_value = cards
        kb.normalize.return_value = []
        kb.check_rules.return_value = list(rules)
        return kb

    def run_case(self, draft, *other_replies, kb=None, renderer=None, variant="A2"):
        cfg = Config(endpoint="http://127.0.0.1:1/v1/chat/completions", model="fixture", repair_call=False)
        transport = Mock(side_effect=[response(reply) for reply in (draft, *other_replies)])
        pipe = Pipeline(cfg, LLMClient(cfg, transport=transport))
        pipe.kb = kb
        with patch("medtrace.pipeline.knowledge_block", renderer or Mock(return_value="")), \
                patch("medtrace.verify.approved_quote", return_value=False):
            result = pipe.run_case(self.case, variant=variant)
        self.assertEqual([], official_schema_errors(result.record, {SOURCE_ID}))
        self.assertEqual("success", result.record["status"])
        return result, [call.args[2] for call in transport.call_args_list]

    def test_render_failure_preserves_base_request_and_skips_knowledge_rules(self):
        draft = self.draft()
        _, baseline = self.run_case(draft)
        card = {"id": "known-card"}
        kb = self.knowledge_base([card], rules=[
            {"state": "triggered", "message": RAG_RULE, "source_ids": [self.sid]},
        ])
        renderer = Mock(side_effect=KeyError("synthetic missing rendering field"))
        result, requests = self.run_case(draft, kb=kb, renderer=renderer)
        renderer.assert_called_once_with([card])
        self.assertEqual(baseline, requests)
        self.assertEqual((1, 1), (result.log["calls"], result.log["http_attempts"]))
        audit = result.log["knowledge"]
        self.assertEqual(("degraded", "context_rendering"), (audit["status"], audit["error_stage"]))
        self.assertEqual([], audit["retrieved"])
        self.assertEqual([], audit["rules"])
        self.assertNotIn(RAG_RULE, result.record["medical_record"]["review_items"])

    def test_unusable_context_does_not_authorize_the_retrieved_id(self):
        card = {"id": "known-card"}
        statement = {"text": "Check the general guidance.", "basis": "knowledge", "knowledge_ids": [card["id"]]}
        draft = self.draft(diagnostic_discussion=[statement])
        for context in (None, {"unexpected": True}, "  \n"):
            with self.subTest(context=context):
                result, requests = self.run_case(draft, kb=self.knowledge_base([card]),
                                                 renderer=Mock(return_value=context))
                self.assertEqual(1, len(requests))
                audit = result.log["knowledge"]
                self.assertEqual("context_rendering", audit["error_stage"])
                self.assertFalse(audit["citations"][0]["valid_ids"])
                self.assertIn("invalid_knowledge_ref", {finding["code"] for finding in audit["citation_findings"]})

    def test_successful_context_is_reused_for_review_with_distinct_citation_fields(self):
        card = {"id": self.sid}
        statement = {"text": "Check the general guidance.", "basis": "knowledge", "knowledge_ids": [card["id"]]}
        context = "\n<knowledge>synthetic card context</knowledge>"
        renderer = Mock(return_value=context)
        result, requests = self.run_case(self.draft(diagnostic_discussion=[statement]), {"patches": []},
                                         kb=self.knowledge_base([card]), renderer=renderer, variant="A3")
        renderer.assert_called_once_with([card])
        self.assertEqual(2, len(requests))
        self.assertTrue(all(request["messages"][1]["content"].endswith(context) for request in requests))
        audit = result.log["knowledge"]
        self.assertEqual("ok", audit["status"])
        self.assertTrue(audit["citations"][0]["valid_ids"])
        self.assertEqual([self.sid], audit["citations"][0]["knowledge_ids"])
        self.assertEqual([{"statement": SOURCE_TEXT, "source_ids": [SOURCE_ID], "kind": "fact"}],
                         result.record["medical_record"]["evidence"])

    def test_no_hits_skip_context_rendering(self):
        renderer = Mock(side_effect=AssertionError("empty retrieval should never be passed to the renderer"))
        result, requests = self.run_case(self.draft(), kb=self.knowledge_base([]), renderer=renderer)
        renderer.assert_not_called()
        self.assertEqual("no_hits", result.log["knowledge"]["status"])
        self.assertEqual(1, len(requests))
