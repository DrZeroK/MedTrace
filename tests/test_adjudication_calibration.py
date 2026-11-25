import csv
import json
import tempfile
import unittest
from pathlib import Path

from eval import adjudication_calibration as AC

NOTE = {"case_features": "f", "diagnostic_discussion": "d", "plan": "p", "evidence": [], "review_items": []}


class Calibration(unittest.TestCase):
    def test_export_hides_verdicts_and_score_counts_disagreements(self):
        d = Path(tempfile.mkdtemp())
        (d / "input.json").write_text(json.dumps([{"case_id": "A", "sources": [{"source_id": "S1", "content": "x"}]}]))
        (d / "out.json").write_text(json.dumps([{"case_id": "A", "status": "success", "medical_record": NOTE, "error": None}]))
        (d / "j").mkdir()
        errs = [{"run": "r", "output": str(d / "out.json"), "case_id": "A", "type": t, "note_quote": q, "source_quote": "",
                 "reason": "", "adjudication": {"confirmed": c, "reason": "why"}}
                for t, q, c in (("harmful", "禁食胃肠减压", False), ("harmful", "用同类过敏药", False),
                                ("fabricated_key_fact", "编造", True))]
        (d / "j" / "major_errors.json").write_text(json.dumps(errs, ensure_ascii=False))
        AC.main(["export", "--input", str(d / "input.json"), "--judge-dirs", str(d / "j"), "--out", str(d / "c")])
        text = (d / "c" / "labels.csv").read_text("utf-8-sig") + (d / "c" / "packet.md").read_text("utf-8")
        self.assertNotIn("why", text)                     # adjudication reasons stay in key.json only
        with open(d / "c" / "labels.csv", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        human = {"禁食胃肠减压": "不成立", "用同类过敏药": "成立", "编造": "成立"}
        for r in rows:
            r[AC.COLS[6]] = human[r["记录原文"]]
        with open(d / "c" / "labels.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, AC.COLS)
            w.writeheader()
            w.writerows(rows)
        AC.main(["score", "--dir", str(d / "c")])
        md = (d / "c" / "calibration.md").read_text("utf-8")
        self.assertIn("初评精确率）：2/3", md)
        self.assertIn("复核与标注一致：2/3", md)
        self.assertIn("即过松）：1", md)


if __name__ == "__main__":
    unittest.main()
