import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from medtrace import runner
from medtrace.config import Config
from medtrace.note import Note, Statement, official_schema_errors, to_official_record
from medtrace.pipeline import CaseResult


class BatchDeadlineTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.input = directory / "input.json"
        self.output = directory / "output.json"
        self.cfg = Config(input_path=str(self.input), output_path=str(self.output),
                          log_dir=str(directory / "logs"), total_timeout=10.0,
                          case_timeout=20.0, time_reserve=2.0)
        self.now = 100.0
        self.pipe = Mock()
        self.pipe.kb = None
        self.enterContext(patch.object(runner, "load_config", return_value=self.cfg))
        self.enterContext(patch.object(runner, "LLMClient"))
        self.pipeline_factory = self.enterContext(patch.object(runner, "Pipeline", return_value=self.pipe))
        self.enterContext(patch.object(runner, "_git_rev", return_value="fixture"))
        self.enterContext(patch.object(runner.time, "monotonic", side_effect=lambda: self.now))
        self.audit = self.enterContext(patch.object(runner, "write_audit"))

        self.publications = []
        write_json = runner.atomic_write_json

        def write_and_record_time(path, obj):
            if Path(path) == self.output:
                self.publications.append(self.now)
            write_json(path, obj)

        self.enterContext(patch.object(runner, "atomic_write_json", side_effect=write_and_record_time))

    def make_input(self, *case_ids, invalid=()):
        records = [{
            "case_id": case_id,
            "record_cutoff": "T0",
            "sources": [] if case_id in invalid else [
                {"source_id": "admission", "content": "Synthetic admission note."},
            ],
        } for case_id in case_ids]
        self.input.write_text(json.dumps(records), encoding="utf-8")

    def run_batch(self):
        self.assertEqual(0, runner.main([]))
        records = json.loads(self.output.read_text(encoding="utf-8"))
        for record in records:
            self.assertEqual([], official_schema_errors(record, {"admission"}))
        events = json.loads(self.output.with_name("run_log.json").read_text(encoding="utf-8"))
        return records, events

    def success(self, case, deadline):
        note = Note()
        note.sections["case_features"] = [Statement("Synthetic admission note.", [case.sources[0].sid])]
        note.sections["diagnostic_discussion"] = [Statement("Assessment pending.")]
        note.sections["treatment_plan"] = [Statement("Review the admission history.")]
        record = to_official_record(note, case)
        return CaseResult(record, note, "ok", log={"case_id": case.case_id, "index": case.index, "status": "ok",
                                                 "calls": 1, "http_attempts": 1})

    def test_cutoff_preserves_publication_time_and_case_order(self):
        self.make_input("first", "second", "third")
        previous = '[{"previous": true}]'
        self.output.write_text(previous, encoding="utf-8")

        def finish_first(case, deadline):
            self.assertEqual(108.0, deadline)
            self.assertEqual(previous, self.output.read_text(encoding="utf-8"))
            self.now = 107.25
            return self.success(case, deadline)

        self.pipe.run_case.side_effect = finish_first
        records, events = self.run_batch()
        self.assertEqual([("first", "success"), ("second", "failed"), ("third", "failed")],
                         [(record["case_id"], record["status"]) for record in records])
        for skipped in records[1:]:
            self.assertIsNone(skipped["medical_record"])
            self.assertEqual({"code": "FALLBACK", "message": "skipped: total time budget exhausted"},
                             skipped["error"])
        self.assertEqual([107.25], self.publications)
        self.pipeline_factory.assert_called_once()
        self.assertEqual(1, self.pipe.run_case.call_count)
        self.assertEqual(2, events[-1]["batch_budget_skipped"])
        self.assertEqual(1, events[-1]["http_attempts"])
        case_events = [event for event in events if event["event"] == "case"]
        for event in case_events[1:]:
            self.assertEqual("total_time_budget", event["skip_reason"])
            self.assertEqual((0, 0, []), (event["calls"], event["http_attempts"], event["attempts"]))

    def test_expired_batch_skips_pipeline_and_preserves_invalid_input_error(self):
        self.make_input("valid", "invalid", invalid=("invalid",))
        self.pipe.kb = object()
        self.pipe.run_case.side_effect = AssertionError("expired cases must not execute the pipeline")
        read_cases = runner.load_cases

        def load_after_deadline(*args):
            cases = read_cases(*args)
            self.now = 111.0
            return cases

        with patch.object(runner, "load_cases", side_effect=load_after_deadline):
            records, events = self.run_batch()
        self.pipeline_factory.assert_called_once()
        self.pipe.run_case.assert_not_called()
        self.assertEqual(["FALLBACK", "INPUT_ERROR"], [record["error"]["code"] for record in records])
        self.assertEqual(2, events[-1]["batch_budget_skipped"])
        self.assertEqual(0, events[-1]["http_attempts"])
        self.assertEqual(2, self.audit.call_count)
        self.assertEqual(["valid", "invalid"], [result.record["case_id"] for result in self.audit.call_args.args[1]])

    def test_shorter_case_deadline_still_wins(self):
        self.make_input("first", "second")
        self.cfg.case_timeout = 3.0
        self.pipe.run_case.side_effect = self.success
        records, events = self.run_batch()
        self.assertEqual(["success", "success"], [record["status"] for record in records])
        self.assertEqual([103.0, 103.0], [call.kwargs["deadline"] for call in self.pipe.run_case.call_args_list])
        self.assertEqual(0, events[-1].get("batch_budget_skipped", 0))
