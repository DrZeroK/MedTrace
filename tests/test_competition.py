"""Competition regressions use retained artifacts and loopback HTTP only."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from medtrace import config, llm, runner
from medtrace.inputs import InputError, parse_case
from medtrace.note import Note, Statement, official_schema_errors, to_official_record
from medtrace.pipeline import Pipeline
from scripts.build_submission import build_zip, build_results

ROOT = Path(__file__).resolve().parents[1]
CASE = {"case_id": "C1", "record_cutoff": "T0", "sources": [{"source_id": "S1", "content": "成人，发热2天，体温38.5℃。"}]}
DRAFT = {"case_features": [{"text": "成人，发热2天，体温38.5℃。", "sources": ["S1"]}],
         "diagnostic_discussion": [{"text": "发热原因待查。", "sources": ["S1"], "basis": "inference"}],
         "treatment_plan": [{"text": "建议进一步明确发热病因。", "sources": ["S1"], "basis": "inference"}]}


class Reply:
    def __init__(self, *drafts):
        self.drafts = list(drafts)
        self.calls = 0

    def chat(self, system, user, stats, deadline=None):
        self.calls += 1
        return json.dumps(self.drafts[min(self.calls - 1, len(self.drafts) - 1)])


class Competition(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="medtrace-protocol-"))

    def package(self):
        build_zip(ROOT, self.d / "package.zip")
        root = self.d / "package"
        with zipfile.ZipFile(self.d / "package.zip") as z:
            z.extractall(root)
        return root

    def server(self, responder=None):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append({"payload": req, "headers": dict(self.headers)})
                draft = responder(len(requests)) if responder else DRAFT
                body = json.dumps({"choices": [{"message": {"content": json.dumps(draft)}}],
                                   "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}/exact-endpoint", requests

    def run_package(self, root, cases, endpoint, extra_env=None):
        (root / ".env").write_text(f"MODEL_NAME=official-test\nENDPOINT={endpoint}\n")
        (root / "input.json").write_text(json.dumps(cases))
        cwd = self.d / "unrelated"
        cwd.mkdir(exist_ok=True)
        (cwd / ".env").write_text("MODEL_NAME=poison\nENDPOINT=http://127.0.0.1:1/poison\n")
        dependency_paths = os.pathsep.join(p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
                                           if p and Path(p).resolve() != ROOT.resolve())
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": dependency_paths, **(extra_env or {})}
        return subprocess.run([sys.executable, str(root / "main.py")], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=30)

    def test_official_entrypoint_ignores_poisoned_environment_and_cwd(self):
        root = self.package()
        endpoint, requests = self.server()
        poison = {"MODEL_NAME": "wrong", "ENDPOINT": "http://127.0.0.1:1/wrong", "INPUT_PATH": "/missing/input.json",
                  "OUTPUT_PATH": "/missing/output.json", "OUTPUT_PROTOCOL": "legacy", "PROMPT_VERSION": "missing",
                  "CONTEXT_MODE": "zh_context_v1", "PROMPT_CANDIDATE_PATH": "/missing/candidate.json",
                  "LLM_API_BASE": "mock://", "LLM_API_KEY": "SYNTHETIC-KEY", "OPENAI_API_KEY": "SYNTHETIC-KEY",
                  "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1"}
        p = self.run_package(root, [CASE], endpoint, poison)
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = json.loads((root / "output.json").read_text())[0]
        self.assertEqual(rec["status"], "success")
        self.assertEqual(official_schema_errors(rec, {"S1"}), [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["payload"]["model"], "official-test")
        self.assertEqual(requests[0]["payload"]["seed"], 42)
        self.assertNotIn("Authorization", requests[0]["headers"])
        events = json.loads((root / "run_log.json").read_text())
        self.assertEqual(len({e["run_id"] for e in events}), 1)
        self.assertTrue(all(datetime.fromisoformat(e["time"]) for e in events))
        case = next(e for e in events if e["event"] == "case")
        self.assertTrue(case["started_at"] <= case["finished_at"])
        self.assertEqual(len(case["attempts"]), case["http_attempts"])
        self.assertEqual(events[-1]["output_sha256"], hashlib.sha256((root / "output.json").read_bytes()).hexdigest())
        self.assertEqual(events[-1]["total_tokens"], 7)

    def test_empty_input_publishes_empty_array_without_model_call(self):
        root = self.package()
        endpoint, requests = self.server()
        p = self.run_package(root, [], endpoint)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads((root / "output.json").read_text()), [])
        self.assertEqual(requests, [])

    def test_invalid_material_is_failed_and_next_case_runs(self):
        cases = []
        for i, change in enumerate(({"record_cutoff": None}, {"record_cutoff": "invalid"},
                                    {"sources": [{"content": "发热。"}]},
                                    {"sources": [{"source_id": "S1", "content": 1}]},
                                    {"sources": [CASE["sources"][0], CASE["sources"][0]]})):
            cases.append(dict(CASE, **change, case_id=f"bad-{i}"))
        root = self.package()
        endpoint, requests = self.server()
        p = self.run_package(root, cases + [CASE], endpoint)
        self.assertEqual(p.returncode, 0, p.stderr)
        recs = json.loads((root / "output.json").read_text())
        self.assertEqual([r["status"] for r in recs], ["failed"] * len(cases) + ["success"])
        self.assertEqual([r["case_id"] for r in recs], [c["case_id"] for c in cases + [CASE]])
        self.assertEqual(len(requests), 1)

    def test_missing_sections_retry_then_fail_or_recover(self):
        for drafts, expected in ((({"case_features": []}, DRAFT), "success"),
                                 (({"case_features": []},), "failed")):
            with self.subTest(expected=expected):
                root = self.d / expected
                root.mkdir()
                inp, out = root / "input.json", root / "output.json"
                inp.write_text(json.dumps([CASE]))
                client = Reply(*drafts)
                cfg = config.Config(input_path=str(inp), output_path=str(out), log_dir=str(root / "logs"), repair_call=False)
                with patch.object(runner, "load_config", return_value=cfg), patch.object(runner, "LLMClient", return_value=client):
                    self.assertEqual(runner.main([]), 0)
                rec = json.loads(out.read_text())[0]
                self.assertEqual(rec["status"], expected)
                self.assertEqual(client.calls, 2)

    def test_official_output_is_not_published_before_model_finishes(self):
        inp, out = self.d / "input.json", self.d / "output.json"
        inp.write_text(json.dumps([CASE]))
        cfg = config.Config(input_path=str(inp), output_path=str(out), log_dir=str(self.d / "logs"), repair_call=False)
        class Checking(Reply):
            def chat(me, *args, **kw):
                self.assertFalse(out.exists())
                return super().chat(*args, **kw)
        with patch.object(runner, "load_config", return_value=cfg), patch.object(runner, "LLMClient", return_value=Checking(DRAFT)):
            self.assertEqual(runner.main([]), 0)
        self.assertEqual(json.loads(out.read_text())[0]["status"], "success")

    def test_interrupted_run_preserves_existing_result(self):
        inp, out = self.d / "input.json", self.d / "output.json"
        inp.write_text(json.dumps([CASE]))
        out.write_text("previous result retained")
        cfg = config.Config(input_path=str(inp), output_path=str(out), log_dir=str(self.d / "logs"), repair_call=False)
        class Interrupt:
            def chat(self, *args, **kw):
                raise KeyboardInterrupt()
        with patch.object(runner, "load_config", return_value=cfg), patch.object(runner, "LLMClient", return_value=Interrupt()):
            with self.assertRaises(KeyboardInterrupt):
                runner.main([])
        self.assertEqual(out.read_text(), "previous result retained")

    def test_bad_case_identifiers_are_task_errors(self):
        for value in (None, "", " ", 1, True, [], {}):
            with self.subTest(value=value), self.assertRaises(InputError):
                runner._validate_official_input([parse_case(dict(CASE, case_id=value), 0)], "list")
        with self.assertRaises(InputError):
            runner._validate_official_input([parse_case(CASE, 0), parse_case(CASE, 1)], "list")

    def test_source_identifiers_are_preserved_without_merging_distinct_strings(self):
        raw = dict(CASE, sources=[{"source_id": "S1", "content": "成人，发热。"},
                                  {"source_id": " S1 ", "content": "体温38.5℃。"}])
        case = parse_case(raw, 0)
        self.assertEqual(case.protocol_errors, [])
        self.assertEqual([s.sid for s in case.sources], ["S1", " S1 "])
        draft = copy.deepcopy(DRAFT)
        draft["case_features"][0]["sources"] = ["S1", " S1 "]
        result = Pipeline(config.Config(repair_call=False), Reply(draft)).run_case(case)
        self.assertEqual(result.record["status"], "success")
        ids = {s for e in result.record["medical_record"]["evidence"] for s in e["source_ids"]}
        self.assertEqual(ids, {"S1", " S1 "})

    def test_config_requires_exactly_two_keys_and_rejects_credentials(self):
        for body in ("", "MODEL_NAME=x\n", "MODEL_NAME=x\nMODEL_NAME=y\nENDPOINT=http://host/path\n",
                     "MODEL_NAME='unterminated\nENDPOINT=http://host/path\n", "MODEL_NAME=x\nENDPOINT=http://u:p@host/path\n",
                     "MODEL_NAME=x\nENDPOINT=ftp://host/path\n", "MODEL_NAME=x\nENDPOINT=http://host/path\nINPUT_PATH=elsewhere\n"):
            (self.d / ".env").write_text(body)
            with self.subTest(body=body), patch.object(config, "ROOT", self.d), self.assertRaises(config.ConfigError):
                config.load_config()

    def test_bundled_knowledge_is_loaded_without_extra_env_keys(self):
        from medtrace.knowledge import build_database
        from tests.test_knowledge import entry
        db = self.d / "knowledge.sqlite"
        build_database([entry()], db, "engineering-fixture")
        build_zip(ROOT, self.d / "package.zip", db)
        root = self.d / "package"
        with zipfile.ZipFile(self.d / "package.zip") as z:
            z.extractall(root)
        endpoint, _ = self.server()
        p = self.run_package(root, [CASE], endpoint)
        self.assertEqual(p.returncode, 0, p.stderr)
        audit = json.loads((root / "output.json.knowledge_audit.json").read_text())
        self.assertEqual(audit["knowledge_version"], "engineering-fixture")

    def test_official_header_never_contains_development_key(self):
        cfg = config.Config(endpoint="http://127.0.0.1:8000/exact", model="m", api_key="SYNTHETIC-KEY", max_retries=0)
        body = json.dumps({"choices": [{"message": {"content": "{}"}}]})
        with patch.object(llm, "_post", return_value=(200, body)) as post:
            llm.LLMClient(cfg).chat("s", "u", llm.CallStats())
        self.assertNotIn("Authorization", post.call_args.args[1])

    def test_http_transport_disables_inherited_credentials_and_redirects(self):
        endpoint, requests = self.server()
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "all_proxy": "http://127.0.0.1:1"}):
            status, _ = llm._post(endpoint, {"Content-Type": "application/json"}, {"messages": []}, 3)
        self.assertEqual(status, 200)
        self.assertNotIn("Authorization", requests[0]["headers"])
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(307)
                self.send_header("Location", endpoint)
                self.send_header("Content-Length", "0")
                self.end_headers()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        status, _ = llm._post(f"http://127.0.0.1:{srv.server_port}/redirect", {}, {"messages": []}, 3)
        self.assertEqual(status, 307)
        self.assertEqual(len(requests), 1)

    def test_requests_session_does_not_inherit_netrc(self):
        class Session:
            trust_env = True
            def __enter__(me):
                return me
            def __exit__(me, *args):
                return False
            def post(me, url, **kw):
                self.assertFalse(me.trust_env)
                self.assertFalse(kw["allow_redirects"])
                return type("Response", (), {"status_code": 200, "text": "{}"})()
        module = type("Requests", (), {"Session": Session, "RequestException": ConnectionError})
        with patch.dict(sys.modules, {"requests": module}):
            self.assertEqual(llm._post("http://127.0.0.1/x", {}, {}, 3), (200, "{}"))

    def test_standard_library_transport_works_without_requests(self):
        endpoint, _ = self.server()
        with patch.dict(sys.modules, {"requests": None}):
            status, _ = llm._post(endpoint, {}, {"messages": []}, 3)
        self.assertEqual(status, 200)

    def test_record_validator_checks_status_and_local_references(self):
        note = Note()
        for sec in note.sections:
            note.sections[sec] = [Statement("发热。", ["S1"])]
        rec = to_official_record(note, parse_case(CASE, 0))
        self.assertEqual(official_schema_errors(rec, {"S1"}), [])
        for edit in (lambda r: r.update(error={"code": "bad", "message": "bad"}),
                     lambda r: r["medical_record"].update(plan=" "),
                     lambda r: r["medical_record"]["evidence"][0].update(source_ids=["OTHER"]),
                     lambda r: r["medical_record"].update(review_items=[{}])):
            value = copy.deepcopy(rec)
            edit(value)
            self.assertTrue(official_schema_errors(value, {"S1"}))
        self.assertTrue(official_schema_errors({"case_id": "C", "status": "failed", "medical_record": {}, "error": None}))

    def test_exported_schema_agrees_with_runtime_status_validation(self):
        try:
            from jsonschema import Draft7Validator
        except ImportError:
            self.skipTest("optional jsonschema is absent")
        from medtrace.note import OFFICIAL_SCHEMA
        validator = Draft7Validator(OFFICIAL_SCHEMA)
        Draft7Validator.check_schema(OFFICIAL_SCHEMA)
        for rec in (to_official_record(Note(), parse_case(CASE, 0), status="failed"),
                    {"case_id": "C", "status": "success", "medical_record": None, "error": None},
                    {"case_id": "C", "status": "failed", "medical_record": None, "error": {}},
                    {"case_id": 1, "status": "failed", "medical_record": None, "error": {"code": "E", "message": "x"}}):
            self.assertEqual(bool(list(validator.iter_errors(rec))), bool(official_schema_errors(rec)))

    def test_manifest_and_existing_archive_protection(self):
        self.package()
        archive = self.d / "package.zip"
        before = archive.read_bytes()
        with self.assertRaises(FileExistsError):
            build_zip(ROOT, archive)
        self.assertEqual(archive.read_bytes(), before)
        with zipfile.ZipFile(archive) as z:
            manifest = json.loads(z.read("submission.manifest.json"))
            self.assertEqual(set(z.namelist()), set(manifest["files"]) | {"submission.manifest.json"})
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
            self.assertNotIn(".env.development.example", z.namelist())

    def test_packaged_docs_and_configuration_describe_official_protocol(self):
        root = self.package()
        self.assertEqual((root / ".env.example").read_text().splitlines(),
                         ["MODEL_NAME=replace_with_model_name", "ENDPOINT=http://127.0.0.1:8000/v1/chat/completions"])
        text = (root / "README.md").read_text()
        for term in ("MODEL_NAME", "ENDPOINT", "medical_record", "review_items", "run_log.json", "--development", "seed 42"):
            self.assertIn(term, text)
        for path in ("README.md", "README.zh-CN.md"):
            import re
            for target in re.findall(r"\]\(([^)]+)\)", (root / path).read_text()):
                if not target.startswith(("https://", "http://")):
                    self.assertTrue((root / target).is_file(), target)

    def test_result_bundle_rejects_changed_outputs_and_stale_logs(self):
        root = self.package()
        endpoint, _ = self.server()
        p = self.run_package(root, [CASE], endpoint)
        self.assertEqual(p.returncode, 0, p.stderr)
        names = build_results(root, self.d / "results.zip")
        self.assertEqual(names, ["output.json", "run_log.json", "submission.manifest.json"])
        with zipfile.ZipFile(self.d / "results.zip") as z:
            self.assertEqual(set(z.namelist()), set(names))
        out = root / "output.json"
        original = out.read_bytes()
        out.write_text("[]")
        with self.assertRaises(ValueError):
            build_results(root, self.d / "changed.zip")
        out.write_bytes(original)
        with (root / "logs/run_log.jsonl").open("a") as stream:
            stream.write(json.dumps({"event": "fatal", "run_id": "later-run", "time": "2026-11-18T00:00:00Z"}) + "\n")
        with self.assertRaises(ValueError):
            build_results(root, self.d / "stale.zip")


if __name__ == "__main__":
    unittest.main()
