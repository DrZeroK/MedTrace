import unittest

from eval.rubric_judge import score_case

REC = {"case_id": "A", "status": "success", "error": None,
       "medical_record": {"case_features": "x", "diagnostic_discussion": "y", "plan": "z", "evidence": [], "review_items": []}}
FULL = {"fidelity": 9, "discussion": 8, "plan": 7, "structure": 8, "attribution": 8}


class RubricRules(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(score_case(REC, {"scores": FULL, "major_errors": []}), {"total": 80.0, "raw": 80.0, "rule": ""})
        cap = score_case(REC, {"scores": FULL, "major_errors": [{"type": "key_number_or_chronology"}]})
        self.assertEqual((cap["total"], cap["raw"]), (50.0, 80.0))
        self.assertEqual(score_case(REC, {"scores": FULL, "major_errors": [{"type": "harmful"}, {"type": "fabricated_key_fact"}]})["total"], 0.0)
        empty = {**REC, "medical_record": {**REC["medical_record"], "plan": " "}}
        self.assertEqual(score_case(empty, None)["total"], 0.0)
        self.assertEqual(score_case(None, None)["total"], 0.0)
        self.assertIsNone(score_case(REC, None)["total"])
        self.assertEqual(score_case(REC, {"scores": {**FULL, "plan": 99}, "major_errors": []})["total"], 86.0)

    def test_only_confirmed_errors_zero_or_cap(self):
        # rubric: a case is zeroed only after a third reviewer confirms; an overturned error leaves the dimension score
        over = {"type": "harmful", "adjudication": {"confirmed": False, "reason": "胆囊炎禁食及胃肠减压为常规处理"}}
        kept = {"type": "harmful", "adjudication": {"confirmed": True, "reason": "记录过敏仍用同类药"}}
        self.assertEqual(score_case(REC, {"scores": FULL, "major_errors": [over]})["total"], 80.0)
        self.assertEqual(score_case(REC, {"scores": FULL, "major_errors": [over, kept]})["total"], 0.0)
        self.assertEqual(score_case(REC, {"scores": FULL, "major_errors": [{"type": "harmful"}]})["total"], 0.0)   # review failed or off


class CacheIdentity(unittest.TestCase):
    def test_two_outputs_in_one_directory_are_judged_separately(self):
        import json, os, tempfile
        from pathlib import Path
        from unittest import mock
        import eval.rubric_judge as RJ

        calls = []

        class FakeClient:
            def __init__(self, cfg):
                pass

            def chat(self, system, user, stats):
                calls.append(user)
                good = "GOOD" in user
                return json.dumps({"scores": {d: 10 if good else 5 for d in RJ.DIMS}, "major_errors": []})

        d = Path(tempfile.mkdtemp())
        (d / "input.json").write_text(json.dumps([{"case_id": "A", "sources": [{"source_id": "S1", "content": "x"}]}]))
        for name, text in (("a.json", "GOOD"), ("b.json", "weak")):
            rec = {**REC, "medical_record": {**REC["medical_record"], "case_features": text}}
            (d / name).write_text(json.dumps([rec]))
        with mock.patch.object(RJ, "LLMClient", FakeClient), \
             mock.patch.dict(os.environ, {"LLM_API_BASE": "mock://", "JUDGE_MODEL": "m"}):
            args = ["--input", str(d / "input.json"), "--outputs", str(d / "a.json"), str(d / "b.json"), "--out", str(d / "j")]
            RJ.main(args)
            RJ.main(args)                       # second run reuses the cache, one entry per distinct note
        self.assertEqual(len(calls), 2)
        summary = (d / "j" / "rubric_summary.md").read_text("utf-8")
        self.assertIn("| 100.0 |", summary)
        self.assertIn("| 50.0 |", summary)


if __name__ == "__main__":
    unittest.main()
