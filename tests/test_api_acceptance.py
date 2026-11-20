"""Tests for scripts/api_acceptance.py (synthetic prompts only; no network)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import api_acceptance as A                                      # noqa: E402
from medtrace.config import Config                             # noqa: E402
from medtrace.llm import CallStats, LLMError                    # noqa: E402

GOOD_CONTENT = '{"ok": true, "purpose": "api_acceptance"}'


def ok_body(usage=None):
    return json.dumps({
        "choices": [{"message": {"content": GOOD_CONTENT}, "finish_reason": "stop"}],
        "usage": usage or {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "total_tokens": 12,
            "completion_tokens_details": {"reasoning_tokens": 4},
            "prompt_tokens_details": {"cached_tokens": 2},
        },
    })


class ApiAcceptance(unittest.TestCase):
    def cfg(self, **kw):
        return Config(endpoint="http://host:8000/v1/chat/completions", model="qwen", api_key="secret",
                      enable_thinking=False, timeout=5, max_retries=2, retry_backoff=0.0, **kw)

    def test_official_payload_and_usage(self):
        calls = []

        def transport(url, headers, payload, timeout):
            calls.append((dict(headers), dict(payload)))
            return 200, ok_body()

        report = A.run_acceptance(self.cfg(), repeats=1, timeout=5, transport=transport)
        self.assertEqual(report["mode"], "official")
        self.assertEqual(report["endpoint"], "http://host:8000/v1/chat/completions")
        self.assertTrue(report["summary"]["http_ok"])
        self.assertTrue(report["summary"]["json_ok"])
        self.assertTrue(report["summary"]["seed_accepted"])
        self.assertTrue(report["summary"]["thinking_accepted"])
        self.assertFalse(report["summary"]["authorization_present"])
        self.assertEqual(calls[0][1]["seed"], 42)
        self.assertEqual(calls[0][1]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("Authorization", calls[0][0])
        self.assertEqual(report["summary"]["usage_total"]["total_tokens"], 12)
        self.assertEqual(report["summary"]["usage_total"]["reasoning_tokens"], 4)
        self.assertEqual(report["summary"]["usage_total"]["cached_tokens"], 2)
        self.assertEqual(report["summary"]["usage_missing"], 0)
        self.assertEqual(A._exit_code(report), 0)

    def test_compat_fallback_is_reported(self):
        calls = []

        def transport(url, headers, payload, timeout):
            calls.append(dict(payload))
            if len(calls) == 1:
                return 400, json.dumps({"error": {"message": "Unrecognized fields: seed, chat_template_kwargs"}})
            return 200, ok_body()

        report = A.run_acceptance(self.cfg(), repeats=1, timeout=5, transport=transport)
        self.assertEqual(len(calls), 2)
        self.assertIn("seed", calls[0])
        self.assertIn("chat_template_kwargs", calls[0])
        self.assertNotIn("seed", calls[1])
        self.assertNotIn("chat_template_kwargs", calls[1])
        self.assertTrue(report["summary"]["http_ok"])
        self.assertFalse(report["summary"]["seed_accepted"])
        self.assertFalse(report["summary"]["thinking_accepted"])
        self.assertTrue(report["summary"]["compat"])
        self.assertEqual(A._exit_code(report), 0)

    def test_non_json_reply_fails_acceptance(self):
        def transport(url, headers, payload, timeout):
            return 200, json.dumps({"choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}]})

        report = A.run_acceptance(self.cfg(), repeats=1, timeout=5, transport=transport)
        self.assertTrue(report["summary"]["http_ok"])
        self.assertFalse(report["summary"]["json_ok"])
        self.assertEqual(A._exit_code(report), 1)

    def test_official_authorization_is_a_failure(self):
        report = {"mode": "official",
                  "summary": {"http_ok": True, "json_ok": True, "authorization_present": True}}
        self.assertEqual(A._exit_code(report), 1)

    def test_zero_reasoning_tokens_still_count_as_reported(self):
        def transport(url, headers, payload, timeout):
            return 200, ok_body({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                                 "completion_tokens_details": {"reasoning_tokens": 0}})

        report = A.run_acceptance(self.cfg(), repeats=1, timeout=5, transport=transport)
        self.assertTrue(report["summary"]["reasoning_tokens_reported"])
        self.assertEqual(report["summary"]["usage_total"]["reasoning_tokens"], 0)

    def test_mock_endpoint_is_rejected(self):
        with self.assertRaises(LLMError):
            A.run_acceptance(Config(api_base="mock://", model=""), repeats=1)

    def test_usage_details_accumulate(self):
        stats = CallStats()
        stats.add_usage({"prompt_tokens": 3, "completion_tokens": 4,
                         "completion_tokens_details": {"reasoning_tokens": 6},
                         "prompt_tokens_details": {"cached_tokens": 2}})
        self.assertEqual((stats.prompt_tokens, stats.completion_tokens, stats.total_tokens), (3, 4, 7))
        self.assertEqual((stats.reasoning_tokens, stats.cached_tokens), (6, 2))
        self.assertEqual(stats.usage_missing, 0)


if __name__ == "__main__":
    unittest.main()
