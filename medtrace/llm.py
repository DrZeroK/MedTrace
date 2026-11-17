"""Client for the designated model (OpenAI-compatible chat-completions protocol - to be confirmed).

`LLM_API_BASE=mock://` routes to the in-process mock so the whole system runs offline.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class CallStats:
    calls: int = 0            # logical model calls
    http_attempts: int = 0    # including retries
    retries: int = 0
    latency: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    errors: list = field(default_factory=list)


def _post(url, headers, payload, timeout):
    """Returns (status, text). Uses requests when available, urllib otherwise."""
    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None:
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            return r.status_code, r.text
        except requests.RequestException as e:
            raise ConnectionError(f"{type(e).__name__}: {e}") from e
    import urllib.request, urllib.error
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        raise ConnectionError(f"{type(e).__name__}: {e}") from e


class LLMClient:
    def __init__(self, cfg, mock=None):
        self.cfg = cfg
        self.mock = mock
        # An explicit official ENDPOINT outranks a legacy mock base: copying .env.example (LLM_API_BASE=mock://)
        # and filling ENDPOINT must reach the real service, not silently return synthetic mock output.
        if self.mock is None and not cfg.endpoint and cfg.api_base.lower().startswith("mock"):
            from .mock_llm import MockLLM
            self.mock = MockLLM.from_env()
        if self.mock is None and not cfg.endpoint and not cfg.api_base:
            raise LLMError("neither ENDPOINT nor LLM_API_BASE is configured (set MODEL_NAME/ENDPOINT in .env, "
                           "or LLM_API_BASE for legacy providers, or use mock:// for offline runs)")
        if cfg.endpoint:
            # Official provider spec: ENDPOINT is the complete request address (includes its path).
            # Use it verbatim - do not append /v1 or /chat/completions.
            if self.mock is None and not (cfg.model or "").strip():
                raise LLMError("MODEL_NAME must be non-empty when ENDPOINT is set (official config requires "
                               "both MODEL_NAME and ENDPOINT)")
            self.url = cfg.endpoint
        else:
            base = cfg.api_base.rstrip("/")
            self.url = base if base.endswith("/chat/completions") else base + "/chat/completions"

    def chat(self, system: str, user: str, stats: CallStats, deadline: float | None = None) -> str:
        if stats.calls >= self.cfg.max_calls_per_case:
            raise BudgetExceeded("model-call budget for this case is exhausted")
        stats.calls += 1
        t0 = time.monotonic()
        try:
            return self._chat(system, user, stats, deadline)
        finally:
            stats.latency += time.monotonic() - t0

    def _check_request_budget(self, stats: CallStats) -> None:
        limit = self.cfg.max_requests_per_case
        if limit > 0 and stats.http_attempts >= limit:
            raise BudgetExceeded(f"request budget for this case is exhausted ({stats.http_attempts}/{limit} HTTP attempts)")

    def _chat(self, system, user, stats, deadline):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.mock is not None:
            self._check_request_budget(stats)
            stats.http_attempts += 1
            return self.mock.complete(messages)
        payload = {"model": self.cfg.model, "messages": messages, "temperature": self.cfg.temperature, "stream": False}
        if self.cfg.max_tokens > 0:
            payload["max_tokens"] = self.cfg.max_tokens
        if self.cfg.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.cfg.seed is not None:
            payload["seed"] = self.cfg.seed
        if self.cfg.enable_thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.cfg.enable_thinking}
        payload.update(self.cfg.extra_body or {})
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        last = "no attempt made"
        for attempt in range(self.cfg.max_retries + 1):
            timeout = self.cfg.timeout
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 1:
                    raise BudgetExceeded(f"time budget exhausted before model call ({last})")
                timeout = min(timeout, remaining)
            self._check_request_budget(stats)
            stats.http_attempts += 1
            retryable = True
            try:
                status, body = _post(self.url, headers, payload, timeout)
                if status == 200:
                    self._usage(body, stats)
                    return self._content(body)
                last = f"HTTP {status}: {body[:200]}"
                retryable = status in _RETRY_STATUS
            except ConnectionError as e:
                last = str(e)
            except LLMError as e:      # 200 with unusable body
                last = str(e)
            stats.errors.append(last)
            if not retryable or attempt == self.cfg.max_retries:
                break
            stats.retries += 1
            pause = min(self.cfg.retry_backoff * (2 ** attempt), 20.0)
            if deadline is not None:
                pause = max(0.0, min(pause, deadline - time.monotonic() - 1))
            time.sleep(pause)
        raise LLMError(f"model call failed: {last}")

    @staticmethod
    def _usage(body: str, stats: CallStats) -> None:
        """Accumulate token usage from a successful response when present; a missing/odd usage never fails the call."""
        try:
            usage = json.loads(body).get("usage")
        except (ValueError, AttributeError):
            return
        if not isinstance(usage, dict):
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            v = usage.get(key)
            if isinstance(v, int):
                setattr(stats, key, getattr(stats, key) + v)

    @staticmethod
    def _content(body: str) -> str:
        try:
            msg = json.loads(body)["choices"][0]["message"]
            content = msg.get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError(f"unexpected response shape: {body[:200]}") from e
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise LLMError("model returned empty content")
        return _THINK.sub("", content).strip()
