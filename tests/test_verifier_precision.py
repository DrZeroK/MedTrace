"""Regression tests for verifier / ledger precision and clinician-facing review items (2026-11-20 practice run).

Every record below is synthetic; the phrasing reproduces the false-positive classes, not any patient's data.
Each class has a matching true-positive check so the fix cannot be a blanket suppression.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from medtrace import textutil as T                                    # noqa: E402
from medtrace import verify as V                                      # noqa: E402
from medtrace import pipeline as P                                    # noqa: E402
from medtrace.config import Config                                    # noqa: E402
from medtrace.inputs import parse_case                                # noqa: E402
from medtrace.ledger import build_ledger                              # noqa: E402
from medtrace.llm import LLMClient                                    # noqa: E402
from medtrace.note import Note, Statement, to_official_record         # noqa: E402


def case(*contents, cutoff=None):
    raw = {"case_id": "SYN", "sources": [{"source_id": f"S{i + 1}", "content": c} for i, c in enumerate(contents)]}
    if cutoff:
        raw["record_cutoff"] = cutoff
    return parse_case(raw, 0)


def findings(c, text, section="case_features"):
    return V.check_statement(section, 0, Statement(text, ["S1"]), c, build_ledger(c))


def coded(c, text, section="case_features"):
    return {(f.code, f.term) for f in findings(c, text, section)}


def codes(c, text, section="case_features"):
    return {f.code for f in findings(c, text, section)}


class NegationScope(unittest.TestCase):
    def test_coordinated_item_after_ji_is_negated(self):
        c = case("既往史：否认心脑血管、肺、肾、内分泌系统等重要脏器疾病史及传染病史。邻居曾患肺结核。"
                 "地方病或传染病流行地区：未到过。")
        self.assertIn("传染病", T.negated_terms("否认心脑血管、肺、肾、内分泌系统等重要脏器疾病史及传染病史"))
        self.assertNotIn("negation_flip", codes(c, "否认重要脏器疾病及传染病史。"))

    def test_true_flip_still_flagged(self):
        c = case("既往患肺结核，已规律治疗。")
        self.assertIn("negation_flip", codes(c, "否认肺结核史。"))

    def test_post_negation_list(self):
        self.assertEqual(T.negated_terms("吸烟、饮酒均否认"), ["吸烟", "饮酒"])
        c = case("嗜烟：无。嗜酒：无。过敏史：否认药物、食物过敏史。")
        got = codes(c, "吸烟饮酒史均否认；否认药物食物过敏史。")
        self.assertFalse(got & {"negation_flip", "undocumented_negative"}, got)
        c = case("否认吸烟史，否认饮酒史。")
        self.assertFalse(codes(c, "吸烟饮酒史均否认。") & {"negation_flip", "undocumented_negative"})

    def test_post_negation_does_not_hide_true_flip(self):
        c = case("吸烟20年，每日1包。")
        self.assertIn("negation_flip", codes(c, "吸烟、饮酒均否认。"))
        # an unseparated compound cannot be split by rule: still flagged, as an undocumented negative
        self.assertIn("undocumented_negative", codes(c, "吸烟饮酒史均否认。"))

    def test_punctuation_variants(self):
        c = case("无濒死感，否认恶心、呕吐、晕厥、抽搐。")
        self.assertNotIn("undocumented_negative", codes(c, "无濒死感、恶心呕吐、晕厥抽搐。"))

    def test_undocumented_negative_still_flagged(self):
        c = case("无濒死感，否认恶心、呕吐。")
        self.assertIn(("undocumented_negative", "咯血"), coded(c, "无濒死感、恶心呕吐、咯血。"))

    def test_collective_suffix_and_family_scope(self):
        c = case("否认家族中癫痫、遗传代谢性疾病史。", "膝反射存在，Kernig征阴性，Babinski征阴性，Brudzinski征阴性。")
        self.assertIn("brudzinski征", T.negated_terms("Kernig征、Babinski征、Brudzinski征均阴性"))
        got = codes(c, "否认家族癫痫及遗传代谢性疾病史；Kernig征、Babinski征、Brudzinski征均阴性。")
        self.assertNotIn("undocumented_negative", got)

    def test_test_panel_collective_result(self):
        c = case("肝炎病毒标志物：乙肝表面抗原阴性，丙肝抗体阴性，甲戊肝抗体阴性。")
        self.assertFalse(codes(c, "肝炎病毒标志物均阴性。") & {"negation_flip", "undocumented_negative"})
        c = case("血常规：HGB 108g/L。")                       # the panel was never done: still flagged
        self.assertIn("undocumented_negative", codes(c, "肝炎病毒标志物均阴性。"))

    def test_abbreviation_map(self):
        c = case("否认哮喘、支气管扩张病史。")
        self.assertNotIn("undocumented_negative", codes(c, "无哮喘或支扩史。"))
        c = case("支气管扩张病史10年。")
        self.assertIn("negation_flip", codes(c, "无支扩史。"))

    def test_non_surgical_risk_group_is_not_an_assertion(self):
        c = case("否认手术史。", "非手术患者Padua评分1分，低危。")
        self.assertNotIn("negation_flip", codes(c, "非手术患者，Padua评分1分。"))


class Certainty(unittest.TestCase):
    C = ("现病史：呕吐腹泻2天。", "初步诊断：1. 急性胃肠炎\n轻-中度脱水\n2. 冠心病？\n记录医师：")

    def test_negated_and_planned_certainty_is_not_definitive(self):
        c = case(*self.C)
        for text in ("空腹血糖升高，但未完善OGTT，不能确诊糖尿病。", "真菌性肺炎待排，需G/GM试验及培养确诊。",
                     "需待病理结果明确诊断。"):
            self.assertNotIn("overconfident", codes(c, text, "diagnostic_discussion"), text)

    def test_definitive_claim_supported_by_record_diagnosis(self):
        c = case(*self.C)
        self.assertNotIn("overconfident", codes(c, "急性胃肠炎伴轻-中度脱水：依据呕吐、腹泻，支持诊断明确。", "diagnostic_discussion"))

    def test_unsupported_definitive_claim_still_flagged(self):
        c = case(*self.C)
        self.assertIn("overconfident", codes(c, "冠心病诊断明确。", "diagnostic_discussion"))   # listed only with "？"
        self.assertIn("overconfident", codes(c, "社区获得性肺炎诊断明确。", "diagnostic_discussion"))


class LedgerConflicts(unittest.TestCase):
    def kinds(self, c):
        return {(x["kind"], x["term"]) for x in build_ledger(c).conflicts}

    def test_serial_values_at_documented_times_are_a_trend(self):
        c = case("10天前外院发现肝功能异常，ALT 86U/L，AST 72U/L。",
                 "辅助检查：2026-05-23 外院\n肝功能：ALT 86U/L，AST 72U/L\n2026-05-23至2026-05-28 我院\n肝功能：ALT 65U/L，AST 54U/L")
        self.assertFalse({k for k in self.kinds(c) if k[0] == "numeric"})

    def test_undated_different_values_still_conflict(self):
        c = case("血钾3.1mmol/L。", "血钾5.8mmol/L。")
        self.assertIn(("numeric", "血钾"), self.kinds(c))

    def test_scope_before_polarity(self):
        self.assertFalse(self.kinds(case("手术外伤史：否认手术史。", "非手术患者Padua评分1分，低危。")))
        self.assertFalse(self.kinds(case("慢性疾病史：否认高血压、糖尿病（孕前）。", "孕24周行OGTT，诊断妊娠期糖尿病。")))
        self.assertIn(("polarity", "糖尿病"), self.kinds(case("否认糖尿病史。", "糖尿病5年，口服二甲双胍。")))
        self.assertIn(("polarity", "手术"), self.kinds(case("否认手术史。", "2019年行阑尾切除手术。")))

    def test_intra_source_contradiction(self):
        c = case("现病史：上腹痛2月，无食欲减退、乏力、体重下降。自发病以来体重近2月下降约2kg。")
        self.assertIn(("internal", "体重下降"), self.kinds(c))
        self.assertNotIn("negation_flip", codes(c, "近2月体重下降约2kg。"))   # the note is faithful to one statement


def _finalise(c, note, official=True):
    conf = Config(api_base="mock://", pipeline="A2", max_calls_per_case=2, output_protocol="official" if official else "legacy")
    p = P.Pipeline(conf, LLMClient(conf))
    L = build_ledger(c)
    p._finalise(note, c, L, V.verify_note(note, c, L) + V.omission_findings(note, L), P._I18N["zh"], "zh")
    return p, L


def _note(features, discussion="考虑消化性溃疡。", plan="完善胃镜检查。"):
    n = Note()
    n.sections["case_features"] = [Statement(t, ["S1"]) for t in features]
    n.sections["diagnostic_discussion"] = [Statement(discussion, ["S1"])]
    n.sections["treatment_plan"] = [Statement(plan, ["S1"])]
    return n


class ClinicianReviewItems(unittest.TestCase):
    def test_internal_contradiction_surfaces_with_clean_wording(self):
        c = case("现病史：上腹痛2月，无食欲减退、乏力、体重下降。自发病以来体重近2月下降约2kg。过敏史：否认药物过敏史。"
                 "血压120/80mmHg。服用奥美拉唑。")
        n = _note(["上腹痛2月，近2月体重下降约2kg。"])
        _finalise(c, n)
        items = to_official_record(n, c)["medical_record"]["review_items"]
        self.assertTrue(any("体重下降" in x and "不一致" in x for x in items), items)
        self.assertFalse(any(x.startswith("请核实：“") for x in items))

    def test_high_flip_is_clinician_visible_without_draft_quote(self):
        c = case("既往患肺结核，已规律治疗。过敏史：否认药物过敏史。血压120/80mmHg。服用异烟肼。")
        n = _note(["否认肺结核史，血压120/80mmHg。"])
        _finalise(c, n)
        items = to_official_record(n, c)["medical_record"]["review_items"]
        self.assertTrue(any("肺结核" in x for x in items), items)
        self.assertFalse(any("否认肺结核史，血压" in x for x in items))      # no draft quote

    def test_dev_items_quote_with_sources_and_official_hides_medium_qa(self):
        c = case("无濒死感，否认恶心、呕吐。过敏史：否认药物过敏史。血压120/80mmHg。服用阿司匹林。")
        n = _note(["无濒死感、恶心呕吐、咯血。否认药物过敏史。"])
        _finalise(c, n, official=False)
        dev = [r for r in n.review_items if r["origin"] == "verifier"]
        self.assertTrue(dev and all(r["source_ids"] == ["S1"] for r in dev))
        self.assertEqual(to_official_record(n, c)["medical_record"]["review_items"], [])

    def test_ranked_and_capped(self):
        c = case("既往患肺结核，已规律治疗。过敏史：否认药物过敏史。血压120/80mmHg。服用异烟肼。")
        n = _note(["否认肺结核史。"])
        n.review_items = [{"type": "verify", "description": f"模型事项{i}", "source_ids": [], "origin": "model"} for i in range(8)]
        p, _ = _finalise(c, n)
        # run_case applies the ranking; reproduce it on the finalised list
        ranked = sorted(n.review_items, key=P._review_rank)[:P.MAX_REVIEW_ITEMS]
        self.assertEqual(len(ranked), 6)
        self.assertEqual(ranked[0]["origin"], "verifier")
        self.assertLessEqual(len(to_official_record(n, c)["medical_record"]["review_items"]), 6)

    def test_trend_and_scoped_statements_create_no_items(self):
        c = case("手术外伤史：否认手术史。过敏史：否认药物过敏史。服用二甲双胍。",
                 "2026-05-23 外院\n肝功能：ALT 86U/L\n2026-05-28 我院\n肝功能：ALT 65U/L\n非手术患者Padua评分1分。血压120/80mmHg。")
        n = _note(["ALT由86U/L降至65U/L。"])
        _finalise(c, n)
        self.assertEqual([r for r in n.review_items if r["type"] == "conflict"], [])


class ContentGuards(unittest.TestCase):
    def test_copied_diagnosis_list_is_dropped(self):
        c = case("初步诊断：1. 胃黏膜病变\n慢性萎缩性胃炎伴肠化\n胃早期癌待排\n2. 腹痛原因待查\n记录医师：")
        L = build_ledger(c)
        n = Note()
        n.sections["diagnostic_discussion"] = [
            Statement("初步诊断：1. 胃黏膜病变（慢性萎缩性胃炎伴肠化）；"), Statement("2. 胃早期癌待排；"),
            Statement("3. 腹痛原因待查。"), Statement("胃早期癌：病理提示腺体不典型增生，需内镜下切除明确性质。")]
        self.assertIn("copied_diagnosis_list", {f.code for f in V.check_statement("diagnostic_discussion", 0, n.sections["diagnostic_discussion"][0], c, L)})
        self.assertEqual(V.drop_copied_diagnosis(n, L), 3)
        self.assertEqual([s.text[:4] for s in n.sections["diagnostic_discussion"]], ["胃早期癌"])
        self.assertFalse(V.is_copied_diagnosis_list("胃早期癌：病理提示腺体不典型增生。", L))

    def test_only_statement_is_kept(self):
        c = case("初步诊断：1. 胃黏膜病变\n2. 腹痛原因待查")
        n = Note()
        n.sections["diagnostic_discussion"] = [Statement("初步诊断：1. 胃黏膜病变；2. 腹痛原因待查。")]
        self.assertEqual(V.drop_copied_diagnosis(n, build_ledger(c)), 0)

    def test_long_statements_split_at_sentence_boundaries(self):
        long = "急诊检验：WBC 10.79×10⁹/L，Hb 146g/L，PLT 456×10⁹/L；" * 3 + "心肌标志物基本正常。"
        n = Note()
        n.sections["case_features"] = [Statement(long, ["S1"]), Statement("短句。", ["S2"])]
        self.assertGreater(V.split_long_statements(n), 0)
        stmts = n.sections["case_features"]
        self.assertTrue(all(len(s.text) <= 100 for s in stmts))
        self.assertEqual("".join(s.text for s in stmts[:-1]), long)
        self.assertTrue(all(s.sources == ["S1"] for s in stmts[:-1]))


class LiveRunFollowUps(unittest.TestCase):
    """False positives found on the live qwen run after the first round of fixes."""

    def test_completed_action_scored_on_its_own_clause(self):
        c = case("外院予阿司匹林300mg、氯吡格雷300mg口服，症状无缓解。")
        text = "已给予阿司匹林和氯吡格雷，鉴于主动脉壁间血肿诊断，需重新评估抗血小板治疗的必要性及出血风险。"
        self.assertNotIn("unsupported_completed", codes(c, text, "treatment_plan"))
        self.assertIn("unsupported_completed", codes(c, "已行冠状动脉造影，需评估支架情况。", "treatment_plan"))

    def test_deng_bing_shi_suffix(self):
        self.assertIn("肝炎", T.negated_terms("否认高血压、糖尿病、肝炎等病史"))
        c = case("否认高血压、糖尿病、肝炎、结核病史。")
        self.assertNotIn("undocumented_negative", codes(c, "否认高血压、糖尿病、肝炎等病史。"))


class OmittedCritical(unittest.TestCase):
    def test_omitted_item_cites_its_record_source_and_stays_in_dev_output(self):
        c = case("过敏史：青霉素过敏（皮疹）。血压120/80mmHg。服用阿司匹林。")
        n = _note(["血压120/80mmHg。"])
        _finalise(c, n, official=False)
        item = next(r for r in n.review_items if "omitted_critical" in r.get("codes", []))
        self.assertEqual(item["source_ids"], ["S1"])
        self.assertFalse(item["official_visible"])

    def test_copied_list_with_stripped_enumeration(self):
        c = case("初步诊断：1. 胃黏膜病变\n胃早期癌待排\n2. 腹痛原因待查\n记录医师：")
        n = Note()
        n.sections["diagnostic_discussion"] = [Statement("初步诊断：1. 胃黏膜病变；"), Statement("胃早期癌待排；"),
                                               Statement("腹痛原因待查。"), Statement("胃早期癌：需内镜下切除明确性质。")]
        self.assertEqual(V.drop_copied_diagnosis(n, build_ledger(c)), 3)


if __name__ == "__main__":
    unittest.main()
