import json
import unittest

from eval.fact_regression import FIXTURE, _cases, evaluate, replay
from eval.followup_fixtures import check_anchors


class FactRegression(unittest.TestCase):
    def test_neg01_observation_uses_its_own_source(self):
        sources = {s["source_id"]: s["content"] for s in _cases()["NEG01"]["sources"]}
        self.assertIn("否认胸痛", sources["S01"])
        self.assertNotIn("护士", sources["S01"])
        self.assertIn("护士今晨观察到少量咯血", sources["S02"])

        outputs = json.loads(FIXTURE.read_text("utf-8"))["outputs"]
        output = next(o for o in outputs
                      if (o["case_id"], o["arm"], o["repeat"]) == ("NEG01", "context", 1))
        sections, findings = replay(output, _cases())
        rows = check_anchors("NEG01", sections)
        self.assertEqual([r["source"] for r in rows], ["S01", "S02"])
        self.assertTrue(all(r["source_match"] for r in rows))
        self.assertEqual([f for f in findings if f.code == "context_assertion"], [])

    def test_legacy_expanded_negation_is_caught_after_source_switch(self):
        outputs = json.loads(FIXTURE.read_text("utf-8"))["outputs"]
        for repeat in (1, 2):
            output = next(o for o in outputs
                          if (o["case_id"], o["arm"], o["repeat"]) == ("NEG01", "legacy", repeat))
            _, findings = replay(output, _cases())
            self.assertEqual([(f.code, f.severity) for f in findings
                              if f.section == "case_features" and f.index == 1],
                             [("negation_flip", "high")])

    def test_round2_counts(self):
        summary = evaluate()
        self.assertEqual(summary["generation_errors"], 4)
        self.assertEqual(summary["verifier_misses"], 2)
        self.assertEqual(summary["verifier_false_positives"], 5)
        by_key = {(d["case_id"], d["arm"], d["repeat"]): d for d in summary["outputs"]}
        self.assertEqual(by_key[("SYN012", "plain", 1)]["misses"], 1)
        self.assertEqual(by_key[("LONG01", "json", 1)]["misses"], 1)
        self.assertEqual(by_key[("SYN100", "mixed", 1)]["findings"], [])
        self.assertEqual(by_key[("SYN100", "mixed", 1)]["generation_errors"], 0)
        self.assertEqual(by_key[("NEG01", "context", 1)]["findings"], [])


if __name__ == "__main__":
    unittest.main()
