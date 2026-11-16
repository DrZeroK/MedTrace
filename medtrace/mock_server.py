"""HTTP mock of an OpenAI-compatible chat-completions endpoint, for protocol and fault-injection tests.

    python -m medtrace.mock_server --port 8089
    LLM_API_BASE=http://127.0.0.1:8089/v1 python main.py

MOCK_FAULTS      content faults (see mock_llm.py)
MOCK_HTTP_FAULTS transport faults, e.g. "http500:0.3,slow:0.2,garbage:0.1" (slow sleeps MOCK_SLOW_SECONDS, default 5)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .mock_llm import MockLLM


def make_server(port: int = 0, mock: MockLLM | None = None, http_faults: dict | None = None, seed: int = 0):
    mock = mock or MockLLM.from_env()
    faults = http_faults or {}
    rng = random.Random(seed)
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            with lock:
                r = [rng.random() for _ in range(3)]
            if r[0] < faults.get("slow", 0):
                time.sleep(float(os.environ.get("MOCK_SLOW_SECONDS", "5")))
            if r[1] < faults.get("http500", 0):
                return self._send(500, {"error": {"message": "injected server error"}})
            if r[2] < faults.get("garbage", 0):
                return self._send(200, {"unexpected": True})
            try:
                messages = json.loads(body.decode("utf-8"))["messages"]
                with lock:
                    content = mock.complete(messages)
            except Exception as e:
                return self._send(400, {"error": {"message": str(e)}})
            self._send(200, {"id": "mock", "object": "chat.completion",
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]})

        def _send(self, code, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.mock = mock
    return srv


def _parse(spec: str) -> dict:
    out = {}
    for part in (spec or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = float(v)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8089)
    a = ap.parse_args()
    s = make_server(a.port, http_faults=_parse(os.environ.get("MOCK_HTTP_FAULTS", "")))
    print(f"mock model listening on http://127.0.0.1:{s.server_address[1]}/v1", flush=True)
    s.serve_forever()
