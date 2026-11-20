#!/usr/bin/env python3
"""Acceptance check for an OpenAI-compatible chat-completions endpoint.

This script sends only a tiny synthetic JSON prompt. It never reads input.json, competition
cases or patient records.

Official mode (default) uses the two-key `.env` beside main.py (MODEL_NAME / ENDPOINT):
    python scripts/api_acceptance.py

Development mode uses the development `.env` or environment (LLM_API_BASE, LLM_API_KEY,
MODEL_NAME) and is intended for MaaS/Ollama checks:
    python scripts/api_acceptance.py --development --repeats 3 --json-out /tmp/api.json

The report covers:
  - endpoint used verbatim and whether Authorization was sent;
  - seed and chat_template_kwargs (enable_thinking) presence and 400 compatibility fallback;
  - HTTP status, JSON parseability, finish reason, latency;
  - prompt/completion/total/reasoning/cached tokens when reported.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from medtrace.config import Config, ConfigError, load_config          # noqa: E402
from medtrace.llm import CallStats, LLMClient, LLMError, _post         # noqa: E402
from medtrace.note import ParseError, parse_json_object                # noqa: E402

SYSTEM_PROMPT = ("You are a connectivity check for an OpenAI-compatible chat-completions endpoint. "
                 "Reply with one JSON object and no extra text.")
USER_PROMPT = 'Return exactly this JSON object and nothing else: {"ok": true, "purpose": "api_acceptance"}'


def _response_body(body: str):
    try:
        obj = json.loads(body)
    except (TypeError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _usage(body: str) -> dict:
    usage = _response_body(body).get("usage")
    if not isinstance(usage, dict):
        return {}

    def num(key):
        v = usage.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def detail(container, key):
        d = usage.get(container)
        if not isinstance(d, dict):
            return None
        v = d.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    reasoning = detail("completion_tokens_details", "reasoning_tokens")
    if reasoning is None:
        reasoning = num("reasoning_tokens")
    return {
        "prompt_tokens": num("prompt_tokens"),
        "completion_tokens": num("completion_tokens"),
        "total_tokens": num("total_tokens"),
        "reasoning_tokens": reasoning,
        "cached_tokens": detail("prompt_tokens_details", "cached_tokens"),
        "usage_keys": sorted(usage.keys()),
    }


def _run_once(client: LLMClient, captured: list) -> dict:
    start = len(captured)
    stats = CallStats()
    t0 = time.monotonic()
    error = None
    content = ""
    try:
        content = client.chat(SYSTEM_PROMPT, USER_PROMPT, stats)
    except (LLMError, OSError, ValueError) as e:
        error = f"{type(e).__name__}: {e}"
    elapsed = time.monotonic() - t0
    caps = captured[start:]
    first = caps[0] if caps else {}
    last = caps[-1] if caps else {}
    payload = first.get("payload") or {}
    thinking = payload.get("chat_template_kwargs")
    try:
        parsed = parse_json_object(content) if content else None
        json_ok = isinstance(parsed, dict)
    except (ParseError, ValueError):
        json_ok = False
    usage = _usage(last.get("body", ""))
    detail = stats.attempts[-1] if stats.attempts else {}
    return {
        "ok": error is None and content.strip() != "" and detail.get("status_code") == 200,
        "json_ok": json_ok,
        "error": error,
        "latency_seconds": round(elapsed, 3),
        "content_characters": len(content),
        "content_preview": content[:160],
        "http_attempts": stats.http_attempts,
        "retries": stats.retries,
        "compat": list(stats.compat),
        "request": {
            "payload_keys": sorted(payload.keys()),
            "seed_present": "seed" in payload,
            "seed_value": payload.get("seed"),
            "thinking_present": "chat_template_kwargs" in payload,
            "thinking_value": thinking.get("enable_thinking") if isinstance(thinking, dict) else None,
            "authorization_present": any("Authorization" in (c.get("headers") or {}) for c in caps),
        },
        "response": {
            "status": detail.get("status_code"),
            "finish_reason": detail.get("finish_reason"),
            "usage": usage,
        },
        "stats": {
            "prompt_tokens": stats.prompt_tokens,
            "completion_tokens": stats.completion_tokens,
            "total_tokens": stats.total_tokens,
            "reasoning_tokens": stats.reasoning_tokens,
            "cached_tokens": stats.cached_tokens,
            "usage_missing": stats.usage_missing,
        },
    }


def run_acceptance(cfg: Config, *, repeats: int = 1, timeout: float | None = None, transport=None) -> dict:
    """Run the synthetic checks and return a JSON-serialisable report."""
    import copy
    cfg = copy.copy(cfg)
    if timeout is not None and timeout > 0:
        cfg.timeout = float(timeout)
    captured: list = []

    def recording(url, headers, payload, timeout_seconds):
        result = (transport or _post)(url, headers, payload, timeout_seconds)
        status, body = result
        captured.append({"url": url, "headers": dict(headers or {}), "payload": dict(payload or {}),
                         "status": status, "body": body if isinstance(body, str) else str(body)})
        return result

    client = LLMClient(cfg, transport=recording)
    if client.mock is not None:
        raise LLMError("mock endpoint configured; acceptance needs a real HTTP endpoint")
    runs = [_run_once(client, captured) for _ in range(max(1, repeats))]

    def flat(key):
        return [r[key] for r in runs]

    seed_sent = any(r["request"]["seed_present"] for r in runs)
    thinking_sent = any(r["request"]["thinking_present"] for r in runs)
    compat = [msg for r in runs for msg in r["compat"]]
    usage_total = {k: sum(r["stats"].get(k) or 0 for r in runs)
                   for k in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens", "cached_tokens")}
    usage_missing = sum(r["stats"].get("usage_missing") or 0 for r in runs)
    latencies = [r["latency_seconds"] for r in runs]
    usage_reported = any((r["response"]["usage"] or {}).get("reasoning_tokens") is not None for r in runs)
    cache_reported = any((r["response"]["usage"] or {}).get("cached_tokens") is not None for r in runs)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "official" if cfg.official else "development",
        "endpoint": client.url,
        "model": cfg.model,
        "synthetic_prompt": True,
        "config": {
            "seed": cfg.seed,
            "enable_thinking": cfg.enable_thinking,
            "timeout": cfg.timeout,
            "max_retries": cfg.max_retries,
            "official": cfg.official,
        },
        "runs": runs,
        "summary": {
            "http_ok": all(r["ok"] for r in runs),
            "json_ok": all(r["json_ok"] for r in runs),
            "seed_sent": seed_sent,
            "seed_accepted": (not any("seed" in msg for msg in compat)) if seed_sent else None,
            "thinking_sent": thinking_sent,
            "thinking_accepted": (not any("chat_template_kwargs" in msg for msg in compat)) if thinking_sent else None,
            "authorization_present": any(r["request"]["authorization_present"] for r in runs),
            "compat": compat,
            "latency_seconds": latencies,
            "latency_p50": round(statistics.median(latencies), 3) if latencies else None,
            "latency_max": round(max(latencies), 3) if latencies else None,
            "usage_total": usage_total,
            "usage_missing": usage_missing,
            "reasoning_tokens_reported": usage_reported,
            "cached_tokens_reported": cache_reported,
        },
    }


def _warnings(report: dict) -> list[str]:
    s = report["summary"]
    out = []
    if not s["http_ok"]:
        out.append("one or more requests failed")
    if not s["json_ok"]:
        out.append("model reply was not a JSON object")
    if report["mode"] == "official" and s["authorization_present"]:
        out.append("official request carried an Authorization header")
    if s["seed_sent"] and s["seed_accepted"] is False:
        out.append("seed was stripped by the 400 compatibility fallback")
    if s["thinking_sent"] and s["thinking_accepted"] is False:
        out.append("chat_template_kwargs was stripped by the 400 compatibility fallback")
    if s.get("usage_missing", 0) > 0:
        out.append("usage was missing on one or more successful responses; token accounting is incomplete")
    if s["usage_total"].get("reasoning_tokens", 0) > 0:
        out.append("reasoning tokens were reported; thinking may still be active")
    if s["usage_total"].get("cached_tokens", 0) > 0:
        out.append("prompt-cache hits were reported; official evaluation plans to disable prefix caching")
    return out


def _exit_code(report: dict) -> int:
    s = report["summary"]
    if not s["http_ok"] or not s["json_ok"]:
        return 1
    if report["mode"] == "official" and s["authorization_present"]:
        return 1
    return 0


def _print_report(report: dict) -> None:
    s = report["summary"]
    print(f"API acceptance ({report['mode']}): {report['endpoint']}")
    print(f"model: {report['model'] or '<empty>'}")
    print(f"seed: sent={s['seed_sent']} accepted={s['seed_accepted']} value={report['config']['seed']}")
    print(f"thinking: sent={s['thinking_sent']} accepted={s['thinking_accepted']} value={report['config']['enable_thinking']}")
    print(f"auth header: {'present' if s['authorization_present'] else 'none'}")
    print(f"HTTP: {sum(1 for r in report['runs'] if r['ok'])}/{len(report['runs'])} ok; "
          f"JSON: {sum(1 for r in report['runs'] if r['json_ok'])}/{len(report['runs'])} ok")
    print(f"latency: p50={s['latency_p50']}s max={s['latency_max']}s")
    u = s["usage_total"]
    print("usage: " + ", ".join(f"{k}={u[k]}" for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                                                        "reasoning_tokens", "cached_tokens")))
    if s["compat"]:
        print("compat: " + "; ".join(s["compat"]))
    warnings = _warnings(report)
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"  - {warning}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check an OpenAI-compatible endpoint without sending case data.")
    ap.add_argument("--development", action="store_true",
                    help="use the development .env/environment instead of the official two-key .env")
    ap.add_argument("--repeats", type=int, default=1, help="number of synthetic requests (1-5; default 1)")
    ap.add_argument("--timeout", type=float, default=120.0, help="per-request timeout in seconds (default 120)")
    ap.add_argument("--json-out", type=Path, help="write the full JSON report to this path")
    args = ap.parse_args(argv)

    old_cwd = os.getcwd()
    try:
        if args.development:
            os.chdir(ROOT)  # development .env belongs to the repo root
        cfg = load_config(development=args.development)
    except ConfigError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    finally:
        os.chdir(old_cwd)
    if args.development:
        if cfg.seed is None:
            cfg.seed = 42
        if cfg.enable_thinking is None:
            cfg.enable_thinking = False
    if cfg.max_retries < 2:
        cfg.max_retries = 2
    if (cfg.endpoint or "").lower().startswith("mock") or (not cfg.endpoint and (cfg.api_base or "").lower().startswith("mock")):
        print("FATAL: mock endpoint configured; acceptance needs a real HTTP endpoint", file=sys.stderr)
        return 2
    repeats = max(1, min(5, args.repeats))
    try:
        report = run_acceptance(cfg, repeats=repeats, timeout=args.timeout)
    except LLMError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    _print_report(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(f"report: {args.json_out}")
    return _exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
