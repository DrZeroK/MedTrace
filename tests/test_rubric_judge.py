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


if __name__ == "__main__":
    unittest.main()
