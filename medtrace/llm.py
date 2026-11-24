"""Client for the designated model (OpenAI-compatible chat-completions protocol - to be confirmed).

`LLM_API_BASE=mock://` routes to the in-process mock so the whole system runs offline.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
# A 400 that explicitly names an unsupported request field is recoverable: strip that field
# once, cache the decision, and retry. Other 400s remain non-retryable.
_UNSUPPORTED_FIELD = re.compile(
    r"(?i)(?:unrecognized|unknown|unexpected|unsupported|not supported|not permitted|"
    r"not a valid\s+(?:field|parameter|argument)|"
    r"extra\s+(?:input|field|parameter)|invalid\s+(?:field|parameter|argument))")
_COMPAT_FIELDS = (
    ("seed", re.compile(r"(?i)\bseed\b")),
    ("chat_template_kwargs", re.compile(r"(?i)chat_template_kwargs|enable_thinking")),
    ("reasoning_effort", re.compile(r"(?i)\breasoning_effort\b")),
)


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
    reasoning_tokens: int = 0   # when reported by the endpoint
    cached_tokens: int = 0      # prompt-cache hits, when reported by the endpoint
    usage_missing: int = 0    # successful HTTP responses with no usable "usage" object
    errors: list = field(default_factory=list)
    attempts: list = field(default_factory=list)
    compat: list = field(default_factory=list)   # request fields stripped after an explicit 400

    def add_usage(self, usage) -> None:
        """Accumulate server-reported usage; malformed or missing objects are only counted, never fatal."""
        if not isinstance(usage, dict):
            self.usage_missing += 1
            return

        def num(key):
            v = usage.get(key)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        def detail(container, key):
            d = usage.get(container)
            if not isinstance(d, dict):
                return None
            v = d.get(key)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        rt = detail("completion_tokens_details", "reasoning_tokens")
        if rt is None:
            rt = num("reasoning_tokens")
        if rt is not None:
            self.reasoning_tokens += int(rt)
        ct = detail("prompt_tokens_details", "cached_tokens")
        if ct is not None:
            self.cached_tokens += int(ct)

        p, c, t = num("prompt_tokens"), num("completion_tokens"), num("total_tokens")
        if p is None and c is None and t is None:
            self.usage_missing += 1
            return
        self.prompt_tokens += int(p or 0)
        self.completion_tokens += int(c or 0)
        self.total_tokens += int(t if t is not None else (p or 0) + (c or 0))


def _post(url, headers, payload, timeout):
    """Returns (status, text). Uses requests when available, urllib otherwise."""
    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None:
        try:
            with requests.Session() as session:
                session.trust_env = False
                r = session.post(url, headers=headers, json=payload, timeout=timeout, allow_redirects=False)
                return r.status_code, r.text
        except requests.RequestException as e:
            raise ConnectionError(f"{type(e).__name__}: {e}") from e
    import urllib.request, urllib.error
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        raise ConnectionError(f"{type(e).__name__}: {e}") from e


def _usage(body: str):
    try:
        obj = json.loads(body)
    except ValueError:
        return None
    return obj.get("usage") if isinstance(obj, dict) else None


class LLMClient:
    def __init__(self, cfg, mock=None, transport=None):
        self.cfg = cfg
        self.mock = mock
        self.transport = transport or _post
        self.compat_disabled: set[str] = set()   # payload fields rejected by this endpoint
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

    def _payload(self, messages: list) -> dict:
        payload = {"model": self.cfg.model, "messages": messages, "temperature": self.cfg.temperature, "stream": False}
        if self.cfg.max_tokens > 0:
            payload["max_tokens"] = self.cfg.max_tokens
        if self.cfg.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.cfg.seed is not None and "seed" not in self.compat_disabled:
            payload["seed"] = self.cfg.seed
        if self.cfg.enable_thinking is not None and "chat_template_kwargs" not in self.compat_disabled:
            payload["chat_template_kwargs"] = {"enable_thinking": self.cfg.enable_thinking}
        payload.update(self.cfg.extra_body or {})
        for key in self.compat_disabled:
            payload.pop(key, None)
        return payload

    def _compat_fields(self, body: str) -> set[str]:
        text = str(body or "")
        if not _UNSUPPORTED_FIELD.search(text):
            return set()
        return {key for key, rx in _COMPAT_FIELDS if key not in self.compat_disabled and rx.search(text)}

    def _chat(self, system, user, stats, deadline):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.mock is not None:
            self._check_request_budget(stats)
            stats.http_attempts += 1
            attempt = {"number": stats.http_attempts, "transport": "mock", "started_at": datetime.now(timezone.utc).isoformat()}
            stats.attempts.append(attempt)
            try:
                return self.mock.complete(messages)
            finally:
                attempt["finished_at"] = datetime.now(timezone.utc).isoformat()
        headers = {"Content-Type": "application/json"}
        # official runs are keyless; development may preview the official output format against a keyed test endpoint
        if self.cfg.api_key and (self.cfg.development or not self.cfg.official):
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        last = "no attempt made"
        for attempt in range(self.cfg.max_retries + 1):
            payload = self._payload(messages)
            timeout = self.cfg.timeout
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 1:
                    raise BudgetExceeded(f"time budget exhausted before model call ({last})")
                timeout = min(timeout, remaining)
            self._check_request_budget(stats)
            stats.http_attempts += 1
            detail = {"number": stats.http_attempts, "transport": "http", "started_at": datetime.now(timezone.utc).isoformat()}
            stats.attempts.append(detail)
            retryable = True
            try:
                status, body = self.transport(self.url, headers, payload, timeout)
                detail["status_code"] = status
                if status == 200:
                    stats.add_usage(_usage(body))
                    return self._content(body, detail)
                last = f"HTTP {status}: {body[:200]}"
                if status == 400:
                    stripped = self._compat_fields(body)
                    if stripped:
                        self.compat_disabled.update(stripped)
                        note = f"HTTP 400 rejected {sorted(stripped)}; retrying without them"
                        stats.compat.append(note)
                        detail["compat"] = note
                        last = note + f" ({body[:160]})"
                        retryable = attempt < self.cfg.max_retries
                        if retryable:
                            detail["error"] = last
                            stats.errors.append(last)
                            stats.retries += 1
                            continue
                retryable = retryable and status in _RETRY_STATUS
            except ConnectionError as e:
                last = str(e)
            except LLMError as e:      # 200 with unusable body
                last = str(e)
            finally:
                detail["finished_at"] = datetime.now(timezone.utc).isoformat()
            detail["error"] = last
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
    def _content(body: str, detail: dict | None = None) -> str:
        if detail is not None:
            detail["response_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        try:
            choice = json.loads(body)["choices"][0]
            msg = choice["message"]
            content = msg.get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError(f"unexpected response shape: {body[:200]}") from e
        if detail is not None:
            finish = choice.get("finish_reason")
            detail["finish_reason"] = finish if finish in ("stop", "length", "content_filter", "tool_calls", "function_call") else "unknown"
            detail["content_type"] = type(content).__name__
            if isinstance(content, str):
                detail["content_characters"] = len(content)
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise LLMError("model returned empty content")
        return _THINK.sub("", content).strip()
