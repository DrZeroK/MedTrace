import json
import subprocess
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from unittest.mock import patch

from medtrace.config import Config
from medtrace.llm import BudgetExceeded, CallStats, LLMClient


REPLY = json.dumps({"choices": [{"message": {"content": "fixture"}}],
                    "usage": {"total_tokens": 12}}).encode("ascii")
CASE_BUDGET = 1.4
SCHEDULING_TOLERANCE = 0.65


class FixtureHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.paths.append(self.path)
        status = 200
        body = REPLY
        if self.path == "/retry" and self.server.paths.count(self.path) == 1:
            status, body = 503, b"temporarily unavailable"
        if self.path == "/slow-headers":
            time.sleep(2.4)
        slow_body = self.path in self.server.closed
        if slow_body:
            body = body.ljust(256)
        try:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if slow_body:
                for offset in range(0, len(body), 12):
                    time.sleep(0.13)
                    self.wfile.write(body[offset:offset + 12])
                    self.wfile.flush()
            else:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            if slow_body:
                self.server.closed[self.path].set()

    def log_message(self, *args):
        pass


class HttpDeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.server.paths = []
        cls.server.closed = {path: Event() for path in ("/slow-body-default", "/slow-body-urllib")}
        thread = Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)

    def client(self, path, transport=None):
        url = f"http://127.0.0.1:{self.server.server_port}{path}"
        cfg = Config(model="fixture", endpoint=url, timeout=5.0, retry_backoff=0.01)
        return LLMClient(cfg, transport=transport)

    def assert_stops_at_deadline(self, path):
        client = self.client(path)
        stats = CallStats()
        started = time.monotonic()
        with self.assertRaisesRegex(BudgetExceeded, "time budget exhausted during model request"):
            client.chat("system", "user", stats, deadline=started + CASE_BUDGET)
        self.assertLess(time.monotonic() - started, CASE_BUDGET + SCHEDULING_TOLERANCE)
        self.assertEqual(1, self.server.paths.count(path))
        self.assertEqual((1, 1, 0), (stats.calls, stats.http_attempts, stats.retries))
        self.assertIn("finished_at", stats.attempts[0])
        self.assertIn("time budget exhausted", stats.attempts[0]["error"])

    def test_response_before_deadline_preserves_usage(self):
        stats = CallStats()
        content = self.client("/fast").chat("system", "user", stats, deadline=time.monotonic() + 3.0)
        self.assertEqual("fixture", content)
        self.assertEqual(12, stats.total_tokens)
        self.assertEqual((1, 1, 0), (stats.calls, stats.http_attempts, stats.retries))

    def test_slow_headers_use_the_same_deadline(self):
        self.assert_stops_at_deadline("/slow-headers")

    def test_slow_body_closes_the_connection_without_retry(self):
        self.assert_stops_at_deadline("/slow-body-default")
        self.assertTrue(self.server.closed["/slow-body-default"].wait(1.5))

    def test_urllib_worker_also_closes_a_slow_body(self):
        start_process = subprocess.Popen

        def without_site_packages(command, **kwargs):
            return start_process([command[0], "-S", *command[1:]], **kwargs)

        with patch.object(subprocess, "Popen", side_effect=without_site_packages):
            self.assert_stops_at_deadline("/slow-body-urllib")
        self.assertTrue(self.server.closed["/slow-body-urllib"].wait(1.5))

    def test_transient_status_still_retries_with_time_remaining(self):
        stats = CallStats()
        content = self.client("/retry").chat("system", "user", stats, deadline=time.monotonic() + 4.0)
        self.assertEqual("fixture", content)
        self.assertEqual([503, 200], [attempt["status_code"] for attempt in stats.attempts])
        self.assertEqual((1, 2, 1), (stats.calls, stats.http_attempts, stats.retries))

    def test_late_injected_transport_result_is_rejected(self):
        clock = [0.0]

        def late_response(*args):
            clock[0] = 2.0
            return 200, REPLY.decode("ascii")

        stats = CallStats()
        with patch("medtrace.llm.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(BudgetExceeded):
                self.client("/injected", transport=late_response).chat("system", "user", stats, deadline=1.5)
        self.assertEqual((1, 1, 0), (stats.calls, stats.http_attempts, stats.retries))

    def test_no_deadline_keeps_the_direct_transport(self):
        with patch.object(subprocess, "Popen") as spawn:
            content = self.client("/direct").chat("system", "user", CallStats())
        self.assertEqual("fixture", content)
        spawn.assert_not_called()
