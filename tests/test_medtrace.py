"""Regression, protocol and fault-injection tests.  Run:  python -m unittest discover -s tests -v   (or pytest)"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from medtrace import textutil as T                                    # noqa: E402
from medtrace import verify as V                                      # noqa: E402
from medtrace.config import Config, load_config                  # noqa: E402
from medtrace.inputs import InputError, load_cases, parse_case         # noqa: E402
from medtrace.ledger import build_ledger                              # noqa: E402
from medtrace.llm import CallStats, LLMClient, LLMError                # noqa: E402
from medtrace.mock_llm import MockLLM                                 # noqa: E402
from medtrace.mock_server import make_server                          # noqa: E402
from medtrace.note import (Note, ParseError, Statement, note_from_model, parse_json_object,
                           schema_errors, to_record, to_official_record, official_schema_errors)  # noqa: E402
from medtrace.pipeline import Pipeline, apply_patches                 # noqa: E402
from medtrace.update import diff_cases                                # noqa: E402

CASE = {"case_id": "T-1", "record_cutoff": "2026-03-02T18:00:00", "sources": [
    {"source_id": "S1", "content": "68-year-old man with fever and cough for 3 days. Denies chest pain, hemoptysis. Allergy: penicillin (rash)."},
    {"source_id": "S2", "content": "Temp 38.6 °C, HR 104 bpm, BP 128/76 mmHg, SpO2 93% on room air. Potassium 4.1 mmol/L."},
    {"source_id": "S3", "content": "Chest X-ray: right lower lobe consolidation. Blood cultures pending. 2026-03-04 sputum culture grew Streptococcus pneumoniae."}]}


def cfg(**kw):
    c = Config(api_base="mock://", pipeline="A2", max_calls_per_case=2, output_protocol="legacy")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def pipe(faults=None, **kw):
    c = cfg(**kw)
    m = MockLLM(faults or {}, seed=1)
    return Pipeline(c, LLMClient(c, mock=m)), m


def codes(text, section="case_features", sources=("S2",), case=CASE):
    c = parse_case(case, 0)
    return {f.code for f in V.check_statement(section, 0, Statement(text, list(sources)), c, build_ledger(c))}


class TextUtil(unittest.TestCase):
    def test_sentences_keep_decimals(self):
        self.assertEqual(T.split_sentences("Temp 38.6 °C. HR 104 bpm. 2026-03-04 seen."), ["Temp 38.6 °C.", "HR 104 bpm.", "2026-03-04 seen."])
        self.assertEqual(len(T.split_sentences("体温38.4℃，脉搏106次/分。神志清楚；皮肤干燥。")), 3)

    def test_dates_and_cutoff(self):
        d = T.find_dates("seen 2026-03-04 10:20 and on March 5, 2026; 2026年3月6日复查")
        self.assertEqual([x[0].day for x in d], [4, 5, 6])
        self.assertTrue(d[0][1])
        cut, ok = T.parse_cutoff("2026-03-04")
        self.assertTrue(ok and cut.hour == 23)
        self.assertFalse(T.is_after(d[0][0], True, cut))
        self.assertTrue(T.is_after(d[1][0], False, cut))
        self.assertEqual(T.parse_cutoff("garbage"), (None, False))

    def test_symbolic_cutoff(self):
        for marker in ("T0", " T0 "):
            self.assertEqual(T.parse_instant(marker), (None, True, None))
            self.assertEqual(T.parse_cutoff(marker), (None, True))
        for invalid in ("T1", "T0+1", "T0garbage"):
            self.assertEqual(T.parse_cutoff(invalid), (None, False))

    def test_numbers_units(self):
        n = T.extract_numbers("WBC 15.2 ×10^9/L, SpO2 93%, BP 128/76 mmHg, HbA1c raised")
        self.assertEqual([(v, u) for v, u, _ in n], [(15.2, "×10^9/l"), (93.0, "%"), (128.0, None), (76.0, "mmhg")])
        self.assertEqual(T.norm_unit("次/分"), T.norm_unit("bpm"))
        self.assertEqual(T.norm_unit("μmol/L"), T.norm_unit("umol/L"))

    def test_negation(self):
        self.assertEqual(T.negated_terms("Denies chest pain, hemoptysis."), ["chest pain", "hemoptysis"])
        self.assertEqual(T.negated_terms("否认发热、寒战，有咳嗽。"), ["发热", "寒战"])
        self.assertEqual(T.negated_terms("Kernig sign negative."), ["kernig sign"])
        self.assertEqual(T.negated_terms("四肢无力，无尿2天。"), [])
        self.assertTrue(T.term_positive_in("cough", "No fever but has cough"))
        self.assertFalse(T.term_positive_in("fever", "No fever but has cough"))


class Inputs(unittest.TestCase):
    def test_symbolic_cutoff_preserves_available_records(self):
        raw = copy.deepcopy(CASE)
        raw["record_cutoff"] = "T0"
        raw["sources"][0]["time"] = "2026-03-05T09:00:00Z"
        for mode in ("redact", "warn", "off"):
            with self.subTest(mode=mode):
                c = parse_case(raw, 0, mode)
                self.assertTrue(c.usable)
                self.assertEqual(c.cutoff_raw, "T0")
                self.assertIsNone(c.cutoff)
                self.assertIsNone(c.cutoff_tz)
                self.assertEqual(c.warnings, [])
                self.assertEqual(c.excluded_sources, [])
                self.assertEqual(c.redacted, [])
                self.assertEqual([s.content for s in c.sources], [s["content"] for s in raw["sources"]])

    def test_cutoff_redaction(self):
        c = parse_case(CASE, 0)
        self.assertNotIn("Streptococcus", c.text)
        self.assertIn("Blood cultures pending", c.text)
        self.assertEqual(len(c.redacted), 1)
        self.assertIn("Streptococcus", parse_case(CASE, 0, "off").text)

    def test_source_timestamp_cutoff(self):
        raw = copy.deepcopy(CASE)
        raw["sources"].append({"source_id": "late", "content": "CT: abscess.", "time": "2026-03-05T09:00:00"})
        c = parse_case(raw, 0)
        self.assertEqual(c.excluded_sources, ["late"])
        self.assertNotIn("late", c.valid_ids)

    def test_timezone_aware_cutoff(self):
        # cutoff 18:00Z; 17:30-02:00 is 19:30Z (after), 19:30+02:00 is 17:30Z (before)
        raw = {"case_id": 1, "record_cutoff": "2026-03-02T18:00:00Z", "sources": [
            {"source_id": "base", "content": "Fever."},
            {"source_id": "late", "content": "CT: abscess.", "time": "2026-03-02T17:30:00-02:00"},
            {"source_id": "early", "content": "Cough.", "time": "2026-03-02T19:30:00+02:00"},
            {"source_id": "epoch_late", "content": "Rash.", "time": 1772478000}]}          # 2026-03-02T19:00:00Z
        c = parse_case(raw, 0)
        self.assertEqual(c.excluded_sources, ["late", "epoch_late"])
        self.assertEqual(sorted(c.valid_ids), ["base", "early"])
        # the cutoff keeps its own local clock, so in-text dates written in that clock still compare correctly
        c = parse_case({"case_id": 2, "record_cutoff": "2026-03-02T18:00:00+08:00", "sources": [
            {"source_id": "a", "content": "2026-03-02 15:00 seen. 2026-03-02 19:00 worse."},
            {"source_id": "b", "content": "Late.", "time": "2026-03-02T11:00:00Z"}]}, 0)     # 19:00+08:00
        self.assertEqual((c.cutoff.hour, c.excluded_sources), (18, ["b"]))
        self.assertIn("15:00 seen", c.text)
        self.assertNotIn("worse", c.text)
        # offset on one side only: not comparable -> compared as written, with a warning
        c = parse_case({"case_id": 3, "record_cutoff": "2026-03-02T18:00:00", "sources": [
            {"source_id": "a", "content": "x.", "time": "2026-03-02T17:30:00-02:00"}]}, 0)
        self.assertEqual(c.excluded_sources, [])
        self.assertTrue(any("UTC offset" in w for w in c.warnings))

    def test_malformed_cases(self):
        self.assertFalse(parse_case("x", 0).usable)
        self.assertFalse(parse_case({"case_id": 1}, 0).usable)
        self.assertFalse(parse_case({"case_id": 1, "sources": [{"source_id": "a", "content": "  "}]}, 0).usable)
        c = parse_case({"case_id": 7, "record_cutoff": "??", "sources": [{"content": "Fever."}, {"source_id": 5, "content": "Cough."},
                                                                           {"source_id": 5, "content": "Wheeze."}, "junk"]}, 0)
        self.assertTrue(c.usable)
        self.assertEqual(sorted(c.valid_ids), ["5", "source_1"])
        self.assertEqual(c.raw_id("5"), 5)                     # original identifier type preserved
        self.assertIn("Wheeze", c.text)
        self.assertGreaterEqual(len(c.warnings), 3)

    def test_envelopes_and_bad_files(self):
        # Retain test artifacts: project policy forbids permanent exit cleanup.
        from contextlib import nullcontext
        with nullcontext(tempfile.mkdtemp(prefix="medtrace-test-")) as d:
            p = Path(d) / "in.json"
            for doc, env in (([CASE], "list"), ({"cases": [CASE]}, "cases"), (CASE, "single")):
                p.write_text(json.dumps(doc), "utf-8")
                cases, e = load_cases(str(p))
                self.assertEqual((len(cases), e), (1, env))
            p.write_bytes(b"\xef\xbb\xbf" + json.dumps([CASE]).encode())      # UTF-8 BOM tolerated
            self.assertEqual(len(load_cases(str(p))[0]), 1)
            for bad in ("{not json", '"a string"', "42"):
                p.write_text(bad, "utf-8")
                self.assertRaises(InputError, load_cases, str(p))
            self.assertRaises(InputError, load_cases, str(Path(d) / "missing.json"))


class Ledger(unittest.TestCase):
    def test_contents(self):
        L = build_ledger(parse_case(CASE, 0))
        self.assertIn(38.6, L.numbers)
        self.assertEqual(L.units[4.1], {"mmol/l"})
        self.assertIn("chest pain", L.neg_only)
        self.assertEqual([f.text for f in L.by_polarity("missing")], ["Blood cultures pending."])
        self.assertEqual([u["key"] for u in L.undocumented], ["medication"])

    def test_conflict_detection(self):
        raw = {"case_id": 1, "sources": [{"source_id": "a", "content": "Denies diabetes. Potassium 4.1 mmol/L."},
                                        {"source_id": "b", "content": "Known diabetes for 5 years. Potassium 5.9 mmol/L."}]}
        kinds = {(c["kind"], c["term"]) for c in build_ledger(parse_case(raw, 0)).conflicts}
        self.assertEqual(kinds, {("polarity", "diabetes"), ("numeric", "potassium")})


class Verifier(unittest.TestCase):
    def test_verbatim_is_clean(self):
        c = parse_case(CASE, 0)
        L = build_ledger(c)
        n = Note()
        n.sections["case_features"] = [Statement(f.text, [f.sid]) for f in L.facts]
        self.assertEqual([f for f in V.verify_note(n, c, L) if f.severity != V.LOW and f.code != "empty_section"], [])

    def test_detections(self):
        self.assertIn("number_not_in_source", codes("Temp 39.6 °C, HR 104 bpm."))
        self.assertIn("unit_mismatch", codes("Potassium 4.1 mg/dL."))
        self.assertIn("negation_flip", codes("He reports chest pain and fever.", sources=("S1",)))
        self.assertIn("negation_flip", codes("No fever or cough.", sources=("S1",)))
        self.assertIn("undocumented_negative", codes("No history of gout.", sources=("S1",)))
        self.assertIn("invalid_ref", codes("Fever and cough for 3 days.", sources=("S9",)))
        self.assertIn("post_cutoff", codes("Sputum culture on 2026-03-04 grew pneumococcus."))
        self.assertIn("low_support", codes("Long-standing chronic kidney disease on warfarin for a mechanical valve."))
        self.assertIn("undocumented_normal", codes("Abdominal and neurological examinations are normal."))
        self.assertIn("unsupported_completed", codes("Bronchoscopy was performed and antibiotics were started.", "treatment_plan"))
        self.assertIn("overconfident", codes("Pneumonia is confirmed.", "diagnostic_discussion"))

    def test_statements_about_missing_information(self):
        # reporting that something is not documented is not a negative finding ...
        self.assertEqual(codes("Current medications are not documented and must not be assumed normal.", sources=()) - {"missing_ref"}, set())
        zh = {"case_id": 1, "sources": [{"source_id": "a", "content": "患者男，50岁，发现肿物3个月。青霉素过敏。"}]}
        self.assertEqual(codes("资料中未记录生命体征及当前用药情况，不能视为正常。", sources=("a",), case=zh), set())
        # ... unless the records do document it
        self.assertIn("false_missing", codes("药物过敏史未记录。", sources=("a",), case=zh))
        self.assertIn("false_missing", codes("Allergy status is not documented.", sources=("S1",)))
        # sub-item claims are not judged: some vitals / medication being documented does not make these false
        self.assertEqual(codes("Anticoagulant medication use is not documented.", sources=()) - {"missing_ref"}, set())
        two = {"case_id": 1, "sources": [{"source_id": "a", "content": "钼靶：肿块大小约2.2cm。超声：肿块大小约2.5cm。"}]}
        self.assertNotIn("value_label_mismatch", codes("钼靶示肿块，大小约2.5cm。", sources=("a",), case=two))

    def test_missing_information_clause_does_not_shield_the_rest(self):
        # regression (review P2): a pending clause used to exempt the whole statement from every check
        self.assertIn("negation_flip", codes("Chest pain. Blood cultures pending."))
        self.assertIn("negation_flip", codes("Chest pain, blood cultures pending."))
        zh = {"case_id": 1, "sources": [{"source_id": "a", "content": "患者否认胸痛。血培养待回报。"}]}
        self.assertIn("negation_flip", codes("胸痛。血培养待回报。", sources=("a",), case=zh))

    def test_no_false_alarm_on_faithful_paraphrase(self):
        self.assertEqual(codes("68-year-old man with 3 days of fever and cough; denies chest pain and hemoptysis.", sources=("S1",)), set())
        self.assertEqual(codes("Recommend repeat potassium in 6 hours and oxygen to keep SpO2 above 94%.", "treatment_plan"), set())
        self.assertEqual(codes("The absence of chest pain makes pulmonary embolism less likely.", "diagnostic_discussion"), set())

    def test_safe_repair_only_drops_bad_refs(self):
        c = parse_case(CASE, 0)
        n = Note()
        n.sections["case_features"] = [Statement("Temp 99 °C.", ["S2", "NOPE"])]
        self.assertEqual(V.safe_repair(n, c), 1)
        self.assertEqual((n.sections["case_features"][0].text, n.sections["case_features"][0].sources), ("Temp 99 °C.", ["S2"]))


class ChineseAndNewChecks(unittest.TestCase):
    ZH = {"case_id": "Z1", "sources": [
        {"source_id": "a", "content": "患者男，60岁。否认糖尿病史。无头晕、头痛。青霉素过敏。血常规：WBC 12.5×109／L，N 85％。血钾 3.1 mmol/L，血钠 138 mmol/L。病理结果未回。"},
        {"source_id": "b", "content": "2型糖尿病病史5年。1周前出现头晕。手术瘢痕：无。"}]}

    def test_fullwidth_and_lost_superscript_units(self):
        self.assertEqual([(v, u) for v, u, _ in T.extract_numbers("WBC 12.5×109／L，N 85％")], [(12.5, "×10^9/l"), (85.0, "%")])
        self.assertEqual(T.norm_unit("×109/L"), T.norm_unit("×10^9/L"))

    def test_units_and_date_ranges_seen_in_real_notes(self):
        got = [(v, u) for v, u, _ in T.extract_numbers("泼尼松25mg 每日一次，PT 12.3s，流速1.2m/s，尿量0.5ml/kg/h，HBV-DNA 500 IU/ml")]
        self.assertEqual(got, [(25.0, "mg"), (12.3, "s"), (1.2, "m/s"), (0.5, "ml/kg/h"), (500.0, "iu/ml")])
        self.assertEqual(T.find_dates("2023.9-2023.12住院"), [])                     # a year.month range is not a date
        self.assertEqual(codes("2023.9-2023.12至外院住院治疗。", sources=("a",),
                               case={"case_id": 1, "sources": [{"source_id": "a", "content": "2023.9-2023.12至外院住院治疗。"}]}), set())

    def test_negation_rules_tuned_on_chip_cdee(self):
        s = "入院前5月，患者无明显诱因出现咳嗽、咳痰，无胸闷、胸痛，无尿频、尿急、尿痛，未再出现咯血。"
        for pos in ("咳嗽", "咳痰"):
            self.assertTrue(T.term_positive_in(pos, s), pos)          # "无明显诱因" negates nothing
        for neg in ("胸闷", "胸痛", "尿频", "尿急", "尿痛", "咯血"):
            self.assertFalse(T.term_positive_in(neg, s), neg)
        self.assertTrue(T.term_positive_in("无尿", "患者无尿2天，伴乏力。"))   # anuria is a positive finding
        self.assertEqual(T.negated_terms("患者无尿2天。"), [])

    def test_negation_scope_on_real_model_prose(self):
        # each of these was a false alarm on the first qwen4-max run
        self.assertEqual(T.negated_terms("尿道口无明显新生物、闭合良好，无阴道前后壁脱垂"), ["新生物", "阴道前后壁脱垂"])
        self.assertEqual(T.negated_terms("无明显神经功能障碍（感觉对称、肌力5级、病理征阴性）")[:1], ["神经功能障碍"])
        self.assertTrue(T.term_positive_in("偶有恶心", "病程中无腹泻、偶有恶心、无呕吐"))
        self.assertEqual(T.negated_terms("触诊：语颤：正常        胸膜摩擦感：正常       皮下捻发感：无"), ["皮下捻发感"])
        self.assertEqual(T.negated_terms("移动性浊音：阴性"), ["移动性浊音"])
        self.assertEqual(T.negated_terms("未叩及腹部包块"), ["腹部包块"])
        self.assertIn(5.0, T.all_number_values("肝上界：右锁骨中线：五肋间"))
        src = {"case_id": 1, "sources": [{"source_id": "a", "content": "未见乳头凹陷，皮肤改变、酒窝征、桔皮症等。既往高血压病史。胆总管呈巨大囊样扩张。无肝内胆管远端分支扩张。"}]}
        self.assertEqual(codes("未见皮肤改变、酒窝征。", sources=("a",), case=src), set())                 # ambiguous source list: not flagged
        self.assertEqual(codes("肝内胆管远端分支无扩张。", sources=("a",), case=src), set())               # site-dependent finding
        self.assertEqual(codes("资料中未提供体温、血压等生命体征。", sources=("a",), case=src), set())     # 高血压病史 is not a reading
        self.assertEqual(codes("本次资料中无体格检查记录，亦无血常规等化验结果。", sources=("a",), case=src), set())
        self.assertEqual(T.negated_terms("重要阴性表现：体温正常"), [])
        # found on fresh validation output: glued label+number in the record, and a denied history inside a test name
        glued = {"case_id": 1, "sources": [{"source_id": "a", "content": "T37.1℃，P75次/分，R20次/分。血肿最厚处约20mm。否认肝炎病史。"}]}
        self.assertEqual(codes("R 20次/分，P 75次/分。", sources=("a",), case=glued), set())
        self.assertEqual(codes("肝炎病毒标志物等资料未记录。", sources=("a",), case=glued), set())
        self.assertIn("unit_mismatch", codes("R 20mm。", sources=("a",), case={"case_id": 1, "sources": [{"source_id": "a", "content": "R20次/分。"}]}))
        self.assertEqual(codes("骨巨细胞瘤好发于20~40岁，需完善24小时尿检查。", "diagnostic_discussion", sources=("a",), case=src), set())
        self.assertIn("number_not_in_source", codes("直接胆红素约占总胆红素68%。", "diagnostic_discussion", sources=("a",), case=src))

    def test_only_denied_history_counts_as_conflict(self):
        L = build_ledger(parse_case(self.ZH, 0))
        self.assertEqual([(c["kind"], c["term"]) for c in L.conflicts], [("polarity", "糖尿病")])   # not 头晕 (time-specific negative)
        self.assertEqual(T.negated_terms("手术瘢痕：无。"), ["手术瘢痕"])

    def test_value_attached_to_wrong_measurement(self):
        self.assertIn("value_label_mismatch", codes("血钾 138 mmol/L。", sources=("a",), case=self.ZH))
        self.assertNotIn("value_label_mismatch", codes("血钾 3.1 mmol/L，血钠 138 mmol/L。", sources=("a",), case=self.ZH))

    def test_critical_omissions_are_surfaced(self):
        c = parse_case(self.ZH, 0)
        L = build_ledger(c)
        n = Note()
        n.sections["case_features"] = [Statement("患者男，60岁。血钾 3.1 mmol/L。", ["a"])]
        self.assertEqual(sorted(f.text for f in V.omission_findings(n, L)), ["病理结果未回。", "青霉素过敏。"])
        n.sections["case_features"].append(Statement("青霉素过敏。病理结果未回。", ["a"]))
        self.assertEqual(V.omission_findings(n, L), [])
        self.assertEqual(V.measurement_coverage(n, L), (1, 4))


class DataPipeline(unittest.TestCase):
    def test_pii_scrub(self):
        from data_pipeline.quality import scrub_pii
        t, hits = scrub_pii("张三丰，男，45岁，住院号：A123456，联系电话：13812345678。身份证110101199003071234。\n病人，男，3岁。王某，女，20岁。")
        self.assertNotIn("张三丰", t)
        self.assertNotIn("13812345678", t)
        self.assertNotIn("110101199003071234", t)
        self.assertNotIn("A123456", t)
        self.assertIn("病人，男，3岁", t)
        self.assertEqual(hits["possible_name"], 1)

    def test_duplicates_and_group_splits(self):
        from data_pipeline import quality as Q
        a = "患者男，49岁，3小时前解大便后出现右下腹疼痛，右下腹可触及一包块，既往体健。" * 3
        self.assertEqual(Q.text_hash(a), Q.text_hash(a.replace("，", " , ")))
        self.assertEqual(Q.near_duplicate_groups({"x": a, "y": a + "体温37.8℃。", "z": "完全不同的另一份病历，主诉头痛三天伴发热。" * 3}), [["x", "y"]])
        s = Q.assign_splits({"c1": "dx:痔", "c2": "dx:痔", "c3": "dx:胃癌"})
        self.assertEqual(s["c1"], s["c2"])
        self.assertEqual(s, Q.assign_splits({"c3": "dx:胃癌", "c2": "dx:痔", "c1": "dx:痔"}))     # order-independent, deterministic
        self.assertIn("too_short", Q.corruption_issues("短"))

    def test_cmb_clin_sectioning_withholds_post_admission_content(self):
        from data_pipeline.cmb_clin import question_kinds, split_sections
        kept, withheld = split_sections("现病史\n（1）病史摘要\n病人，男，49岁，3小时前解大便后出现右下腹疼痛。\n\n体格检查\nT 37.8℃，P 101次/分，腹软，右侧腹股沟区可扪及肿块。\n\n"
                                        "辅助检查\n超声检查\n\n治疗经过\n急诊行疝修补术，术后恢复良好，7天后出院。\n\n辅助检查\n术后病理：肠壁组织缺血坏死。")
        self.assertEqual([k["slug"] for k in kept], ["hpi", "exam"])
        self.assertTrue(all("术后" not in k["text"] and "出院" not in k["text"] for k in kept))
        self.assertEqual([w["reason"][:4] for w in withheld], ["empt", "post", "post"])
        self.assertEqual(question_kinds("简述该病人的鉴别诊断。"), ["differential"])
        self.assertEqual(question_kinds("简述本例病人的诊断及诊断依据，鉴别诊断。"), ["differential", "diagnosis"])
        self.assertEqual(question_kinds("治疗原则是什么？"), ["plan"])

    def test_typicalcase_sectioning_and_denied_history_precision(self):
        from data_pipeline.typicalcase_dc import split_sections
        secs = split_sections("个人信息：男，28 岁。\n主诉：头痛 6 个月。\n现病史：6 个月前出现头痛。\n既往史：无。\n\n**六、家族史**\n\n无肿瘤家族史。\n体格检查：无。\n检查检验：\n    - 血常规正常。")
        self.assertEqual(list(secs), ["hx", "past", "exam", "tests"])
        self.assertEqual(len(secs["hx"]), 3)
        self.assertIn("    - 血常规正常。", secs["tests"])
        # a denied history is not contradicted by the term inside a test name or a negative result
        mk = lambda b: build_ledger(parse_case({"case_id": 1, "sources": [{"source_id": "a", "content": "否认肝炎、结核病史，否认药物、食物过敏史。"},
                                                                         {"source_id": "b", "content": b}]}, 0)).conflicts
        self.assertEqual(mk("肝炎标志物、肿瘤标志物未见异常。自行服用感冒药物。"), [])
        self.assertEqual([c["term"] for c in mk("肝脏病理检查：中度慢性肝炎伴结节性肝硬化形成。")], ["肝炎"])

    def test_standardized_dataset_invariants(self):
        d = ROOT / "data" / "standardized" / "cmb_clin"
        cases = json.loads((d / "cases.json").read_text("utf-8"))
        refs = {r["case_id"]: r for r in json.loads((d / "references.json").read_text("utf-8"))}
        ids = [s["source_id"] for c in cases for s in c["sources"]]
        self.assertEqual(len(ids), len(set(ids)))                                   # source ids globally unique
        self.assertEqual(len(cases), len(refs))
        by_label = {}
        for c in cases:
            r = refs[c["case_id"]]
            self.assertTrue(parse_case(c, 0).usable)
            text = "\n".join(s["content"] for s in c["sources"])
            self.assertNotIn("案例分析", text)                                        # the diagnosis-bearing title never leaks
            self.assertFalse(any(h in text.split("\n") for h in ("治疗经过", "治疗过程", "病情变化")))
            self.assertIsNone(r["reference"]["case_features"])                       # nothing generated
            if r["split"] != "excluded_pending_review":
                by_label.setdefault(r["classification"]["disease_label"], set()).add(r["split"])
        self.assertTrue(all(len(v) == 1 for v in by_label.values()))                # no disease label spans two splits


class Parsing(unittest.TestCase):
    def test_tolerant_json(self):
        self.assertEqual(parse_json_object('<think>hmm</think>```json\n{"a": [1,2,],}\n```')["a"], [1, 2])
        self.assertEqual(parse_json_object('Sure! {"a": 1} hope it helps'), {"a": 1})
        for bad in ("", "no json", '{"a": ', "[1,2]"):
            self.assertRaises(ParseError, parse_json_object, bad)

    def test_note_shapes(self):
        n = note_from_model({"case_features": "1. Fever. [[S1]]\n2. Cough.", "discussion": ["x"], "诊疗计划": [{"statement": "y", "source_ids": "S1, S2"}],
                             "review_items": ["check allergy", {"type": "bogus", "text": "t"}]})
        self.assertEqual([(s.text, s.sources) for s in n.sections["case_features"]], [("Fever.", ["S1"]), ("Cough.", [])])
        self.assertEqual(n.sections["treatment_plan"][0].sources, ["S1", "S2"])
        self.assertEqual([r["type"] for r in n.review_items], ["verify", "verify"])
        self.assertRaises(ParseError, note_from_model, {"foo": 1})


class PipelineTests(unittest.TestCase):
    def test_all_variants_valid(self):
        c = parse_case(CASE, 0)
        for v in ("A0", "A1", "A2", "S2", "A3"):
            p, _ = pipe(max_calls_per_case=3)
            r = p.run_case(c, variant=v)
            self.assertEqual(r.status, "ok", v)
            self.assertEqual(schema_errors(r.record), [], v)
            self.assertEqual(r.record["case_id"], "T-1")
            self.assertNotIn("Streptococcus", json.dumps(r.record))

    def test_faults_removed_or_flagged(self):
        c = parse_case(CASE, 0)
        for fault in ("wrong_number", "unit_swap", "negation_flip", "fabricate", "undoc_negative", "post_cutoff", "done_plan", "invalid_ref"):
            p, m = pipe({fault: 1.0})
            r = p.run_case(c)
            self.assertTrue(m.fault_log, fault)
            blob = json.dumps({k: r.record[k] for k in ("case_features", "diagnostic_discussion", "treatment_plan", "evidence")}, ensure_ascii=False)
            needle = m.fault_log[0]["needle"]
            flagged = any(needle[:100] in i["description"] for i in r.record["review_items"])
            self.assertTrue(needle not in blob or flagged, f"{fault} survived unflagged")
            self.assertEqual(schema_errors(r.record), [])

    def test_single_call_budget_flags_instead_of_repairing(self):
        p, m = pipe({"wrong_number": 1.0}, max_calls_per_case=1)
        r = p.run_case(parse_case(CASE, 0))
        self.assertEqual((r.status, r.log["calls"]), ("ok", 1))
        self.assertTrue(any(m.fault_log[0]["needle"][:60] in i["description"] for i in r.record["review_items"]))

    def test_bad_json_retry_then_fallback(self):
        c = parse_case(CASE, 0)
        p, _ = pipe({"bad_json": 1.0})
        r = p.run_case(c)
        self.assertEqual((r.status, r.log["calls"]), ("fallback", 2))
        self.assertEqual(schema_errors(r.record), [])
        self.assertIn("Temp 38.6", r.record["case_features"])            # verbatim extracts only
        self.assertNotIn("Streptococcus", r.record["case_features"])     # cutoff still respected
        self.assertTrue(r.record["review_items"])

    def test_guard_rejects_hallucinating_reviewer(self):
        p, m = pipe({"bad_patch": 1.0}, pipeline="A3")
        r = p.run_case(parse_case(CASE, 0))
        self.assertNotIn("9.9", r.record["case_features"])
        self.assertGreaterEqual(r.log["patches"]["rejected"], 1)

    def test_patch_guards(self):
        c = parse_case(CASE, 0)
        L = build_ledger(c)
        n = Note()
        n.sections["case_features"] = [Statement("Temp 38.6 °C.", ["S2"]), Statement("Temp 55 °C.", ["S2"])]
        n.sections["treatment_plan"] = [Statement("Recommend oxygen.", [])]
        res = apply_patches(n, [
            {"section": "case_features", "index": 0, "action": "delete"},                               # unflagged feature: reject
            {"section": "case_features", "index": 1, "action": "replace", "text": "Temp 77 °C."},        # still wrong: reject
            {"section": "case_features", "index": 1, "action": "replace", "text": "Temp 38.6 °C, HR 104 bpm."},  # ok
            {"section": "treatment_plan", "index": 0, "action": "delete"},                               # would empty: reject
            {"section": "case_features", "index": 99, "action": "replace", "text": "x"}, "junk"],
            c, L, "repair", {("case_features", 1)})
        self.assertEqual((res["applied"], res["rejected"]), (1, 5))
        self.assertEqual([s.text for s in n.sections["case_features"]], ["Temp 38.6 °C.", "Temp 38.6 °C, HR 104 bpm."])

    def test_drop_mode_removes_everything_flagged(self):
        raw = {"case_id": "K", "sources": [{"source_id": "S1", "content": "Potassium 4.1 mmol/L."}]}
        p, m = pipe({"wrong_number": 1.0}, max_calls_per_case=1, on_unresolved="drop")
        r = p.run_case(parse_case(raw, 0))
        self.assertNotIn(m.fault_log[0]["needle"], r.record["case_features"])
        self.assertIn("clinician input required", r.record["case_features"])
        self.assertEqual(schema_errors(r.record), [])

    def test_mock_fault_needles_follow_later_mutations(self):
        raw = {"case_id": "K", "sources": [{"source_id": "S1", "content": "Potassium 4.1 mmol/L."}]}
        p, m = pipe({"wrong_number": 1.0, "unit_swap": 1.0}, pipeline="A1", max_calls_per_case=1)
        r = p.run_case(parse_case(raw, 0))
        self.assertEqual([e["fault"] for e in m.fault_log], ["wrong_number", "unit_swap"])
        for e in m.fault_log:                       # both faults are still in the unverified A1 output
            self.assertIn("mg/dL", e["needle"])
            self.assertIn(e["needle"], r.record["case_features"])

    def test_unusable_case_isolated(self):
        p, _ = pipe()
        r = p.run_case(parse_case({"case_id": "bad", "sources": []}, 0))
        self.assertEqual(r.status, "input_error")
        self.assertEqual(schema_errors(r.record), [])

    def test_chinese_case(self):
        raw = {"case_id": "Z", "sources": [{"source_id": "病史", "content": "患者男，45岁，上腹痛3天。否认呕血、黑便。血红蛋白146 g/L。胃镜未做。"}]}
        p, m = pipe({"negation_flip": 1.0})
        r = p.run_case(parse_case(raw, 0))
        self.assertEqual(r.status, "ok")
        self.assertTrue("自诉有呕血" not in r.record["case_features"] or any("自诉有呕血" in i["description"] for i in r.record["review_items"]))
        self.assertTrue(any("过敏" in i["description"] for i in r.record["review_items"]))    # undocumented allergy surfaced

    def test_output_contract_options(self):
        p, _ = pipe(output_field_map={"treatment_plan": "plan"}, output_fields=["case_features", "treatment_plan"], inline_citations=True)
        rec = p.run_case(parse_case(CASE, 0)).record
        self.assertEqual(set(rec), {"case_id", "case_features", "plan"})
        self.assertIn("[S1]", rec["case_features"])


class Update(unittest.TestCase):
    def test_diff(self):
        new = copy.deepcopy(CASE)
        new["sources"][2]["content"] = new["sources"][2]["content"].replace("Blood cultures pending.", "Blood cultures: no growth at 48 hours.")
        d = diff_cases(parse_case(CASE, 0), parse_case(new, 0))
        self.assertEqual([a["text"] for a in d["added"]], ["Blood cultures: no growth at 48 hours."])
        self.assertEqual([a["text"] for a in d["removed"]], ["Blood cultures pending."])


class ConfigParsing(unittest.TestCase):
    def _load(self, **env):
        d = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        keys = ("LLM_SEED", "LLM_ENABLE_THINKING")
        old = {k: os.environ.get(k) for k in keys}
        os.chdir(d)
        try:
            for k in keys:
                if k in env:
                    os.environ[k] = env[k]
                else:
                    os.environ.pop(k, None)
            return load_config(development=True)
        finally:
            os.chdir(old_cwd)
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_invalid_seed_and_thinking_are_ignored_with_warning(self):
        c = self._load(LLM_SEED="abc", LLM_ENABLE_THINKING="maybe")
        self.assertEqual(c.seed, 42)
        self.assertIsNone(c.enable_thinking)
        self.assertEqual(len(c.warnings), 2)

    def test_valid_seed_and_thinking_parse(self):
        c = self._load(LLM_SEED="7", LLM_ENABLE_THINKING="false")
        self.assertEqual((c.seed, c.enable_thinking, c.warnings), (7, False, []))


class Http(unittest.TestCase):
    def _serve(self, **faults):
        srv = make_server(0, mock=MockLLM(), http_faults=faults, seed=3)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}/v1"

    def test_roundtrip_and_retry(self):
        c = cfg(api_base=self._serve(http500=0.5), max_retries=6, retry_backoff=0.01)
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        self.assertEqual(r.status, "ok")

    def test_persistent_failure_falls_back(self):
        c = cfg(api_base=self._serve(http500=1.0), max_retries=1, retry_backoff=0.01)
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        self.assertEqual((r.status, r.log["retries"]), ("fallback", 1))
        self.assertEqual(schema_errors(r.record), [])

    def test_timeout_and_garbage(self):
        os.environ["MOCK_SLOW_SECONDS"] = "3"
        c = cfg(api_base=self._serve(slow=1.0), max_retries=0, timeout=0.5)
        self.assertRaises(LLMError, LLMClient(c).chat, "s", "u", CallStats())
        c = cfg(api_base=self._serve(garbage=1.0), max_retries=0)
        self.assertRaises(LLMError, LLMClient(c).chat, "s", "u", CallStats())
        c = cfg(api_base="http://127.0.0.1:9/v1", max_retries=0, timeout=2)          # nothing listening
        self.assertEqual(Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0)).status, "fallback")

    def _srv(self, **kw):
        srv = make_server(0, mock=MockLLM(), seed=3, **kw)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def _url(self, srv):
        return f"http://127.0.0.1:{srv.server_address[1]}/v1"

    def test_default_payload_fixes_seed_and_omits_thinking(self):
        srv = self._srv()
        c = cfg(api_base=self._url(srv))
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        self.assertEqual(r.status, "ok")
        self.assertTrue(srv.requests)
        for req in srv.requests:
            self.assertEqual(req["seed"], 42)
            self.assertNotIn("chat_template_kwargs", req)

    def test_seed_and_thinking_sent_when_configured(self):
        srv = self._srv()
        c = cfg(api_base=self._url(srv), seed=42, enable_thinking=False)
        Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        req = srv.requests[0]
        self.assertEqual(req["seed"], 42)
        self.assertEqual(req["chat_template_kwargs"], {"enable_thinking": False})

    def test_extra_body_overrides_seed_and_thinking(self):
        srv = self._srv()
        c = cfg(api_base=self._url(srv), seed=42, enable_thinking=False,
                extra_body={"seed": 7, "chat_template_kwargs": {"enable_thinking": True}})
        Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        req = srv.requests[0]
        self.assertEqual(req["seed"], 7)
        self.assertEqual(req["chat_template_kwargs"], {"enable_thinking": True})

    def test_usage_accumulates_in_case_log(self):
        srv = self._srv(usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12})
        c = cfg(api_base=self._url(srv))
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        self.assertEqual(r.status, "ok")
        n = r.log["calls"]
        self.assertEqual((r.log["prompt_tokens"], r.log["completion_tokens"], r.log["total_tokens"]), (5 * n, 7 * n, 12 * n))
        self.assertEqual(r.log["usage_missing"], 0)

    def test_partial_usage_derives_total(self):
        srv = self._srv(usage={"prompt_tokens": 3, "completion_tokens": 4})
        c = cfg(api_base=self._url(srv))
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        n = r.log["calls"]
        self.assertEqual((r.log["prompt_tokens"], r.log["completion_tokens"], r.log["total_tokens"]), (3 * n, 4 * n, 7 * n))
        self.assertEqual(r.log["usage_missing"], 0)

    def test_missing_usage_still_succeeds(self):
        srv = self._srv()
        c = cfg(api_base=self._url(srv))
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.log["total_tokens"], 0)
        self.assertEqual(r.log["usage_missing"], r.log["http_attempts"])
        self.assertEqual(schema_errors(r.record), [])

    def test_unusable_usage_counts_missing(self):
        srv = self._srv(usage={"prompt_tokens": "n/a"})
        c = cfg(api_base=self._url(srv))
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        self.assertEqual((r.log["total_tokens"], r.log["usage_missing"]), (0, r.log["http_attempts"]))

    def test_request_budget_counts_retries(self):
        srv = self._srv(http_faults={"http500": 1.0})
        c = cfg(api_base=self._url(srv), max_retries=5, retry_backoff=0.01, max_requests_per_case=2)
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0))
        self.assertEqual(r.status, "fallback")
        self.assertTrue(r.log.get("budget_exhausted"))
        self.assertEqual(len(srv.requests), 2)
        self.assertEqual(schema_errors(r.record), [])

    def test_reserve_skips_repair(self):
        p, _ = pipe({"wrong_number": 1.0}, repair_call=True, time_reserve=1.0)
        r = p.run_case(parse_case(CASE, 0), deadline=time.monotonic() + 0.5)
        self.assertEqual(r.status, "ok")
        self.assertIn("repair", r.log.get("time_budget_skipped", []))

    def test_no_deadline_never_skips(self):
        p, _ = pipe({"wrong_number": 1.0}, repair_call=True)
        r = p.run_case(parse_case(CASE, 0))
        self.assertNotIn("time_budget_skipped", r.log)

    def test_case_timeout_falls_back(self):
        os.environ["MOCK_SLOW_SECONDS"] = "3"
        srv = self._srv(http_faults={"slow": 1.0})
        c = cfg(api_base=self._url(srv), max_retries=0)
        r = Pipeline(c, LLMClient(c)).run_case(parse_case(CASE, 0), deadline=time.monotonic() + 2.0)
        self.assertEqual(r.status, "fallback")
        self.assertEqual(schema_errors(r.record), [])
        self.assertEqual(len(srv.requests), 1)


class EndToEnd(unittest.TestCase):
    def _run(self, doc, env=None, raw=None):
        d = tempfile.mkdtemp()
        inp, out = Path(d) / "input.json", Path(d) / "output.json"
        inp.write_text(raw if raw is not None else json.dumps(doc, ensure_ascii=False), "utf-8")
        e = {**os.environ, "LLM_API_BASE": "mock://", "OUTPUT_PROTOCOL": "legacy", "LOG_DIR": str(Path(d) / "logs"), "INPUT_PATH": str(inp), "OUTPUT_PATH": str(out), **(env or {})}
        p = subprocess.run([sys.executable, str(ROOT / "main.py"), "--development"], cwd=d, env=e, capture_output=True, text=True, timeout=120)
        return p, out, Path(d)

    def test_batch_order_and_isolation(self):
        cases = [dict(CASE, case_id=f"C{i}") for i in range(5)]
        cases.insert(2, {"case_id": "broken"})
        cases.insert(4, "not a case")
        p, out, d = self._run(cases, {"MOCK_FAULTS": "bad_json:0.4,wrong_number:0.5", "WORKERS": "3"})
        self.assertEqual(p.returncode, 0, p.stderr)
        recs = json.loads(out.read_text("utf-8"))
        self.assertEqual([r["case_id"] for r in recs], ["C0", "C1", "broken", "C2", None, "C3", "C4"])
        self.assertTrue(all(schema_errors(r) == [] for r in recs))
        self.assertFalse([f for f in os.listdir(d) if f.startswith(".tmp_")])
        events = [json.loads(l)["event"] for l in (d / "logs" / "run_log.jsonl").read_text("utf-8").splitlines()]
        self.assertEqual(events.count("case"), 7)

    def test_output_aliases_byte_identical(self):
        p, out, d = self._run([CASE, dict(CASE, case_id="C2")], {"OUTPUT_ALIASES": "results.json"})
        self.assertEqual(p.returncode, 0, p.stderr)
        alias = d / "results.json"
        self.assertTrue(alias.exists())
        self.assertEqual(alias.read_bytes(), out.read_bytes())
        self.assertEqual(schema_errors(json.loads(alias.read_text("utf-8"))[0]), [])
        self.assertFalse([f for f in os.listdir(d) if f.startswith(".tmp_")])

    def test_alias_same_dir_and_dedupe(self):
        p, out, d = self._run([CASE], {"OUTPUT_ALIASES": "sub/results.json,results.json,output.json"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((d / "results.json").exists())
        self.assertEqual((d / "results.json").read_bytes(), out.read_bytes())
        self.assertFalse((d / "sub").exists())

    def test_no_alias_unchanged(self):
        p, out, d = self._run([CASE])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(out.exists())
        self.assertFalse((d / "results.json").exists())

    def test_run_end_carries_totals(self):
        srv = make_server(0, mock=MockLLM(), seed=3, usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12})
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        p, out, d = self._run([CASE], {"LLM_API_BASE": url})
        self.assertEqual(p.returncode, 0, p.stderr)
        events = [json.loads(l) for l in (d / "logs" / "run_log.jsonl").read_text("utf-8").splitlines()]
        end = [e for e in events if e["event"] == "run_end"][-1]
        cases = [e for e in events if e["event"] == "case"]
        for k in ("prompt_tokens", "completion_tokens", "total_tokens", "usage_missing", "calls", "http_attempts", "retries"):
            self.assertEqual(end[k], sum(c.get(k, 0) for c in cases))
        self.assertGreater(end["total_tokens"], 0)

    def test_run_end_latency_summary(self):
        p, out, d = self._run([CASE, dict(CASE, case_id="C2")])
        self.assertEqual(p.returncode, 0, p.stderr)
        events = [json.loads(l) for l in (d / "logs" / "run_log.jsonl").read_text("utf-8").splitlines()]
        end = [e for e in events if e["event"] == "run_end"][-1]
        self.assertIn("latency_p50", end)
        self.assertIn("latency_max", end)
        self.assertGreaterEqual(end["latency_max"], end["latency_p50"])
        self.assertGreaterEqual(end["latency_p50"], 0.0)

    def test_output_independent_of_hash_seed(self):
        # regression: iterating a set made review-item order differ between runs (Python randomises str hashing)
        cases = [c["case"] for c in json.loads((ROOT / "eval" / "cases.json").read_text("utf-8"))[:8]]
        faults = {"MOCK_FAULTS": "negation_flip:0.6,undoc_negative:0.6,wrong_number:0.5"}
        outs = []
        for h in ("1", "2", "3"):
            p, out, _ = self._run(cases, {**faults, "PYTHONHASHSEED": h})
            self.assertEqual(p.returncode, 0, p.stderr)
            outs.append(out.read_bytes())
        self.assertEqual(len(set(outs)), 1)

    def test_fatal_inputs_exit_1(self):
        p, out, _ = self._run(None, raw="{broken")
        self.assertEqual(p.returncode, 1)
        self.assertFalse(out.exists())
        p, _, _ = self._run([CASE], {"LLM_API_BASE": ""})
        self.assertEqual(p.returncode, 1)

    def test_env_example_parses_to_defaults(self):
        # regression: `KEY=   # comment` is read by python-dotenv as the comment text, which once dropped output fields
        d = tempfile.mkdtemp()
        (Path(d) / ".env").write_text((ROOT / ".env.development.example").read_text("utf-8"), "utf-8")
        (Path(d) / "input.json").write_text(json.dumps([CASE]), "utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "OUTPUT_", "PIPELINE", "MOCK_"))}
        p = subprocess.run([sys.executable, str(ROOT / "main.py"), "--development"], cwd=d, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = json.loads((Path(d) / "output.json").read_text("utf-8"))[0]
        self.assertEqual(schema_errors(rec), [])  # development template retains the legacy contract

    def test_prompt_version_resolved_after_dotenv(self):
        # regression (review P2): PROMPT_VERSION was read at import time, before .env was loaded
        from medtrace import config as C
        from medtrace import pipeline as P
        d = tempfile.mkdtemp()
        (Path(d) / ".env").write_text("PROMPT_VERSION=v1\n", "utf-8")
        before = set(os.environ)
        old_cwd, old = os.getcwd(), os.environ.pop("PROMPT_VERSION", None)
        try:
            os.chdir(d)
            C.prompt_version.cache_clear()
            C.load_config(development=True)
            self.assertEqual(C.prompt_version(), "v1")
            self.assertEqual(P.prompt_dir().name, "v1")
            self.assertTrue((P.prompt_dir() / "en" / "a0.txt").is_file())
            self.assertTrue(P.prompt_fingerprint().startswith("v1:"))
        finally:
            os.chdir(old_cwd)
            C.prompt_version.cache_clear()
            for k in set(os.environ) - before:
                os.environ.pop(k, None)
            if old is not None:
                os.environ["PROMPT_VERSION"] = old

    def test_strict_exit_and_envelope(self):
        p, out, _ = self._run({"cases": [CASE]}, {"MOCK_FAULTS": "bad_json:1", "STRICT_EXIT": "1"})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(list(json.loads(out.read_text("utf-8"))), ["cases"])

    def test_total_timeout_still_writes_complete_output(self):
        p, out, _ = self._run([dict(CASE, case_id=i) for i in range(4)], {"TOTAL_TIMEOUT": "0.001"})
        self.assertEqual(p.returncode, 0)
        self.assertEqual([r["case_id"] for r in json.loads(out.read_text("utf-8"))], [0, 1, 2, 3])


class BasisField(unittest.TestCase):
    OBJ = {"case_features": [{"text": "Fever for 3 days.", "sources": ["S1"]}],
           "diagnostic_discussion": [{"kind": "assessment", "basis": "knowledge", "text": "Pneumonia is a common diagnosis.", "sources": ["S1"]}],
           "treatment_plan": [{"kind": "treatment", "basis": "inference", "text": "Consider antibiotics.", "sources": ["S1"]}]}

    def test_parse_and_copy_basis(self):
        n = note_from_model(self.OBJ)
        self.assertEqual(n.sections["diagnostic_discussion"][0].basis, "knowledge")
        self.assertEqual(n.sections["case_features"][0].basis, "")
        c = n.copy()
        self.assertEqual(c.sections["diagnostic_discussion"][0].basis, "knowledge")
        self.assertEqual(c.sections["treatment_plan"][0].basis, "inference")

    def test_replace_patch_preserves_basis(self):
        c = parse_case(CASE, 0)
        L = build_ledger(c)
        n = Note()
        n.sections["treatment_plan"] = [Statement("Consider antibiotics.", ["S1"], "treatment", "inference")]
        res = apply_patches(n, [{"section": "treatment_plan", "index": 0, "action": "replace",
                                 "text": "Consider appropriate antibiotics."}], c, L, "review", set())
        self.assertEqual(res["applied"], 1)
        self.assertEqual(n.sections["treatment_plan"][0].basis, "inference")

    def test_to_record_evidence_basis(self):
        rec = to_record(note_from_model(self.OBJ), parse_case(CASE, 0), cfg())
        disc = [e for e in rec["evidence"] if e["section"] == "diagnostic_discussion"]
        self.assertEqual(disc[0]["basis"], "knowledge")
        feat = [e for e in rec["evidence"] if e["section"] == "case_features"]
        self.assertNotIn("basis", feat[0])

    def test_invalid_basis_schema_error(self):
        rec = to_record(note_from_model(self.OBJ), parse_case(CASE, 0), cfg())
        rec["evidence"][0]["basis"] = "bogus"      # the schema guard still rejects an off-enum basis in a record
        self.assertTrue(schema_errors(rec))

    def test_off_enum_basis_dropped_at_parse(self):
        obj = json.loads(json.dumps(self.OBJ))
        obj["diagnostic_discussion"][0]["basis"] = "conflict"   # real model occasionally emits off-enum values
        n = note_from_model(obj)
        self.assertEqual(n.sections["diagnostic_discussion"][0].basis, "")
        self.assertEqual(schema_errors(to_record(n, parse_case(CASE, 0), cfg())), [])

    def test_knowledge_statement_with_record_value_flagged(self):
        c = parse_case(CASE, 0)
        L = build_ledger(c)
        st = Statement("Potassium 4.1 mmol/L is typical.", ["S2"], "assessment", "knowledge")
        self.assertIn("knowledge_record_value", {f.code for f in V.check_statement("diagnostic_discussion", 0, st, c, L)})
        st2 = Statement("A prevalence of 30% is reported.", ["S2"], "assessment", "knowledge")
        self.assertNotIn("knowledge_record_value", {f.code for f in V.check_statement("diagnostic_discussion", 0, st2, c, L)})

    def test_mock_a2_emits_record_basis(self):
        p, _ = pipe()
        r = p.run_case(parse_case(CASE, 0))
        self.assertEqual(r.status, "ok")
        self.assertEqual(schema_errors(r.record), [])
        ev = [e for e in r.record["evidence"] if e["section"] in ("diagnostic_discussion", "treatment_plan")]
        self.assertTrue(ev)
        self.assertTrue(all(e.get("basis") == "record" for e in ev))


class Wp8FalseAlarms(unittest.TestCase):
    """Regression guards for the false-alarm patterns fixed in WP-8 (real TypicalCase-DC prose)."""

    def test_glued_analyte_number_in_source(self):
        case = {"case_id": 1, "sources": [{"source_id": "a", "content": "动脉血气：PCO232.4 mmHg，PO246 mmHg，SO270%。维生素B12766.49pg/ml。"}]}
        self.assertEqual(codes("动脉血气：PCO2 32.4 mmHg，PO2 46 mmHg，SO2 70%。", sources=("a",), case=case) - {"missing_ref"}, set())
        self.assertNotIn("number_not_in_source", codes("维生素B12 766.49pg/ml。", sources=("a",), case=case))

    def test_glued_number_recovery_rejects_ordinary_labels(self):
        case = {"case_id": 1, "sources": [{"source_id": "a", "content": "Creatinine120 umol/L."}]}
        self.assertEqual(T.all_number_values("Creatinine120 umol/L."), {120.0})
        self.assertIn("number_not_in_source", codes("Creatinine 20 umol/L.", sources=("a",), case=case))

    def test_scientific_notation_unit(self):
        case = {"case_id": 1, "sources": [{"source_id": "a", "content": "白细胞计数 1.0×106/L。"}]}
        self.assertEqual(codes("白细胞1.0×10^6/L。", sources=("a",), case=case) - {"missing_ref"}, set())

    def test_serial_and_side_labels_not_mismatch(self):
        case = {"case_id": 1, "sources": [{"source_id": "a", "content": "血常规：白细胞 36.81×10⁹/L，血红蛋白 77g/L。现病史：白细胞（WBC）13.93×10⁹/L，血红蛋白（HBG）104g/L。眼压：右眼 19.3 mmHg。眼轴右眼 25.02 mm。"}]}
        self.assertNotIn("value_label_mismatch", codes("白细胞13.93×10⁹/L，血红蛋白104g/L。", sources=("a",), case=case))
        self.assertNotIn("value_label_mismatch", codes("眼轴右眼 25.02 mm。", sources=("a",), case=case))

    def test_single_swap_still_flagged(self):
        case = {"case_id": 1, "sources": [{"source_id": "a", "content": "血钾 3.1 mmol/L，血钠 138 mmol/L。"}]}
        self.assertIn("value_label_mismatch", codes("血钾 138 mmol/L。", sources=("a",), case=case))

    def test_buhui_negation(self):
        self.assertEqual(T.negated_terms("不会注视及追视"), ["注视", "追视"])

    def test_postfix_negation_scope(self):
        self.assertNotIn("家族", T.clearly_positive_text("家族史均无特殊"))
        self.assertNotIn("家族", T.clearly_positive_text("家族史无"))
        self.assertNotIn("病理征", T.clearly_positive_text("病理征未引出"))
        self.assertNotIn("检查检验", T.clearly_positive_text("检查检验结果暂无"))

    def test_section_header_not_finding(self):
        case = {"case_id": 1, "sources": [{"source_id": "a", "content": "个人史\n无特殊。\n体格检查\n无特殊。"}]}
        self.assertNotIn("negation_flip", codes("个人史无特殊。", sources=("a",), case=case))
        self.assertNotIn("negation_flip", codes("体格检查无特殊。", sources=("a",), case=case))


class Docs(unittest.TestCase):
    def test_no_commercial_endpoint_example(self):
        for f in ("README.md", ".env.example", "docs/REQUIREMENTS.md", "docs/REPORT.md"):
            self.assertNotIn("dashscope", (ROOT / f).read_text("utf-8").lower(), f)


class Packaging(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_submission as B
        self.B = B

    def test_requirements_in_sync(self):
        lines = lambda p: [l.strip() for l in (ROOT / p).read_text("utf-8").splitlines() if l.strip()]
        self.assertEqual(lines("requirements.txt"), lines("requires.txt"))

    def test_zip_whitelist(self):
        d = Path(tempfile.mkdtemp())
        names, total = self.B.build_zip(ROOT, d / "sub.zip")
        for expected in ("main.py", "medtrace/prompts/v2/zh/a1.txt", "docs/RESOURCE_REGISTRATION.md", "input.example.json"):
            self.assertIn(expected, names)
        self.assertNotIn(".env", names)
        for n in names:
            self.assertFalse(n.startswith(("eval/", "data/", "data_pipeline/", "tests/")))
            self.assertNotIn("__pycache__", n)
            self.assertNotIn(".DS_Store", n)
            self.assertFalse(n.endswith(".pyc"))
        self.assertGreater(total, 0)

    def test_packaged_env_example_is_minimal(self):
        # Tech spec 附件3 §1: the shipped .env.example contains only MODEL_NAME and ENDPOINT,
        # not the repo's rich development template.
        d = Path(tempfile.mkdtemp())
        self.B.build_zip(ROOT, d / "sub.zip")
        with zipfile.ZipFile(d / "sub.zip") as zf:
            env = zf.read(".env.example").decode("utf-8")
        keys = sorted(l.split("=", 1)[0].strip() for l in env.splitlines() if l.strip() and not l.startswith("#"))
        self.assertEqual(keys, ["ENDPOINT", "MODEL_NAME"])
        for banned in ("LLM_", "INPUT_PATH", "OUTPUT_", "PIPELINE", "KB_PATH", "dashscope"):
            self.assertNotIn(banned, env)

    def test_zip_smoke_run(self):
        d = Path(tempfile.mkdtemp())
        self.B.build_zip(ROOT, d / "sub.zip")
        ext = d / "unzipped"
        with zipfile.ZipFile(d / "sub.zip") as zf:
            zf.extractall(ext)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "OUTPUT_", "PIPELINE", "MOCK_"))}
        env["LLM_API_BASE"] = "mock://"
        env["OUTPUT_PROTOCOL"] = "official"
        p = subprocess.run([sys.executable, str(ext / "main.py"), "--development", "--input", str(ext / "input.example.json"), "--output", str(ext / "output.json")],
                           cwd=ext, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        recs = json.loads((ext / "output.json").read_text("utf-8"))
        self.assertEqual(official_schema_errors(recs[0]), [])   # package runs the default official protocol


class VerifierFalseAlarmFixes(unittest.TestCase):
    """Regressions for the two D5 false-alarm sources found on the 5-case scoring run."""

    def test_section_label_prefix_not_low_support(self):
        # "实验室检查：…" prefix once added out-of-vocabulary bigrams and tipped overlap below 0.35.
        case = parse_case({"case_id": "X", "sources": [
            {"source_id": "S1", "content": "钾3.7mmol/L，TSH结果待回报。"}]}, 0)
        L = build_ledger(case)
        st = Statement("实验室检查：钾3.7mmol/L，TSH结果待回报。", ["S1"])
        self.assertNotIn("low_support", {f.code for f in V.check_statement("case_features", 0, st, case, L)})

    def test_missing_cue_not_low_support(self):
        # "未提及" was not a recognised missing cue, so an absence-report was scored as a weak finding.
        case = parse_case({"case_id": "X", "sources": [
            {"source_id": "S1", "content": "男性，68岁，心悸。"}]}, 0)
        L = build_ledger(case)
        st = Statement("药物过敏史及当前用药情况记录中未提及。", ["S1"])
        self.assertTrue(T.has_missing_cue(st.text))
        self.assertNotIn("low_support", {f.code for f in V.check_statement("case_features", 0, st, case, L)})

    def test_knowledge_basis_normalised_to_inference(self):
        # A statement labelled 'knowledge' that reasons over a patient value is reclassified by the
        # pipeline so it neither fires knowledge_record_value nor mislabels the official evidence kind.
        from medtrace.pipeline import _normalise_basis
        from medtrace.note import SECTIONS
        c = parse_case({"case_id": "X", "sources": [
            {"source_id": "S1", "content": "肌酐132μmol/L。"}]}, 0)
        L = build_ledger(c)
        note = note_from_model({"case_features": ["肌酐132μmol/L"] ,
                                "diagnostic_discussion": [{"text": "肌酐132μmol/L提示肾功能受损。",
                                                            "basis": "knowledge", "sources": ["S1"]}],
                                "treatment_plan": ["复查肾功能。"]})
        self.assertEqual(note.sections["diagnostic_discussion"][0].basis, "knowledge")
        changed = _normalise_basis(note, L)
        self.assertEqual(changed, 1)
        self.assertEqual(note.sections["diagnostic_discussion"][0].basis, "inference")
        fs = V.check_statement("diagnostic_discussion", 0, note.sections["diagnostic_discussion"][0], c, L)
        self.assertNotIn("knowledge_record_value", {f.code for f in fs})

    def test_official_evidence_kind_by_section(self):
        # Features -> fact; discussion/plan -> inference even when the model left basis empty or set 'record'.
        n = note_from_model({"case_features": [{"text": "发热。", "sources": ["S1"]}],
                             "diagnostic_discussion": [{"text": "考虑感染，病因待查。", "sources": ["S1"], "basis": "record"}],
                             "treatment_plan": [{"text": "复查血常规。", "sources": ["S1"]}]})
        rec = to_official_record(n, parse_case(CASE, 0), status="success")
        kinds = {e["statement"]: e["kind"] for e in rec["medical_record"]["evidence"]}
        self.assertEqual(kinds["发热。"], "fact")
        self.assertEqual(kinds["考虑感染，病因待查。"], "inference")
        self.assertEqual(kinds["复查血常规。"], "inference")
        self.assertEqual(official_schema_errors(rec), [])


class OfficialProtocol(EndToEnd):
    """Provider-spec mode: MODEL_NAME/ENDPOINT, keyless, official output schema (Q3/Q8/Q9 + tech spec)."""

    def test_config_dual_mode_defaults(self):
        from unittest.mock import patch
        from medtrace import config as C
        d = Path(tempfile.mkdtemp())
        (d / ".env").write_text("MODEL_NAME=qwen-official\nENDPOINT=http://host:8000/v1/chat/completions\n")
        with patch.object(C, "ROOT", d), patch.object(Path, "cwd", return_value=d), patch.dict(os.environ, {}, clear=True):
            c = C.load_config()
            self.assertTrue(c.official)
            self.assertEqual(c.endpoint, "http://host:8000/v1/chat/completions")
            self.assertEqual(c.model, "qwen-official")
            self.assertFalse(C.load_config(development=True).official)

    def test_endpoint_used_verbatim_no_auth_header(self):
        # Official ENDPOINT is used verbatim (no path appended) and needs no key.
        c = Config(endpoint="http://host:8000/v1/chat/completions", model="qwen", api_key="")
        client = LLMClient(c)
        self.assertEqual(client.url, "http://host:8000/v1/chat/completions")
        self.assertFalse(client.cfg.api_key)
        # Legacy base still appends the path.
        c2 = Config(api_base="http://host:8000/v1", model="qwen")
        self.assertEqual(LLMClient(c2).url, "http://host:8000/v1/chat/completions")

    def test_endpoint_overrides_mock_base(self):
        # PR#4 P1: an explicit ENDPOINT must reach the real service even when LLM_API_BASE=mock:// (copied .env.example).
        c = Config(endpoint="http://host:8000/v1/chat/completions", api_base="mock://", model="qwen")
        client = LLMClient(c)
        self.assertIsNone(client.mock)
        self.assertEqual(client.url, "http://host:8000/v1/chat/completions")

    def test_endpoint_requires_model_name(self):
        # PR#4 P2: ENDPOINT without MODEL_NAME is a config error (official runner exits 2), not an empty model value.
        for bad in ("", "   "):
            with self.assertRaises(LLMError):
                LLMClient(Config(endpoint="http://host:8000/v1/chat/completions", model=bad))
        LLMClient(Config(endpoint="http://host:8000/v1/chat/completions", model="qwen", api_key=""))  # keyless + model OK
        self.assertIsNotNone(LLMClient(Config(api_base="mock://")).mock)                              # mock needs no model

    def test_official_record_success_shape(self):
        note = note_from_model({
            "case_features": ["Fever and cough [[S1]]", "No chest pain [[S1]]", "Temp 38.5 [[S2]]"],
            "diagnostic_discussion": ["Likely infection [[S2]]", "Uncertain source"],
            "treatment_plan": ["Observe and recheck [[S2]]", "Recheck labs [[S3]]"],
            "evidence": [{"statement": "Fever", "source_ids": ["S1"]}], "review_items": ["check allergy"]})
        rec = to_official_record(note, parse_case(CASE, 0), status="success")
        self.assertEqual(official_schema_errors(rec), [], official_schema_errors(rec))
        self.assertEqual(rec["status"], "success")
        self.assertIsNone(rec["error"])
        mr = rec["medical_record"]
        self.assertIn("plan", mr) and self.assertNotIn("treatment_plan", mr)
        self.assertTrue(all(isinstance(x, str) for x in mr["review_items"]))
        self.assertTrue(3 <= len(mr["evidence"]) <= 5)
        self.assertTrue(all(e["kind"] in ("fact", "inference") for e in mr["evidence"]))

    def test_official_record_failed_shape(self):
        rec = to_official_record(Note(), parse_case(CASE, 0), status="failed",
                                 error={"code": "MODEL_TIMEOUT", "message": "timed out"})
        self.assertEqual(rec["status"], "failed")
        self.assertIsNone(rec["medical_record"])
        self.assertEqual(rec["error"]["code"], "MODEL_TIMEOUT")

    def test_official_end_to_end(self):
        # Mock model via legacy LLM_API_BASE still works; OUTPUT_PROTOCOL=official only changes the output shape.
        p, out, d = self._run([CASE], {"OUTPUT_PROTOCOL": "official"})
        self.assertEqual(p.returncode, 0, p.stderr)
        recs = json.loads(out.read_text("utf-8"))
        self.assertIsInstance(recs, list)
        self.assertEqual(official_schema_errors(recs[0]), [], official_schema_errors(recs[0]))

    def test_official_exit_code_config_missing(self):
        from scripts.build_submission import build_zip
        d = Path(tempfile.mkdtemp())
        build_zip(ROOT, d / "package.zip")
        with zipfile.ZipFile(d / "package.zip") as z:
            z.extractall(d / "package")
        p = subprocess.run([sys.executable, str(d / "package/main.py")], cwd=d,
                           env={"PATH": os.environ.get("PATH", "")}, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2, p.stderr)


if __name__ == "__main__":
    unittest.main()
