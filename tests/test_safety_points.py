import unittest
from unittest.mock import patch

from medtrace.config import Config
from medtrace.inputs import parse_case
from medtrace.llm import LLMClient
from medtrace.mock_llm import MockLLM
from medtrace.pipeline import Pipeline
from medtrace.safety_points import safety_points


def rules(*contents):
    case = parse_case({"case_id": "T", "record_cutoff": "T0",
                       "sources": [{"source_id": f"S{i}", "content": c} for i, c in enumerate(contents, 1)]}, 0)
    return [r for r, _ in safety_points(case)]


class SafetyPoints(unittest.TestCase):
    def test_each_rule_fires_on_its_situation(self):
        self.assertIn("allergy_class", rules("自述青霉素曾致皮疹。"))
        self.assertIn("allergy_class", rules("阿莫西林过敏史。"))
        self.assertIn("stroke_reperfusion", rules("左侧肢体无力、口角歪斜；最后一次明确正常为当日7时。", "头颅CT未见急性出血。"))
        self.assertIn("ectopic_unstable", rules("停经7周，心率108次/分。", "经阴道超声未见明确宫内孕囊，右附件区混合性包块。"))
        self.assertIn("thiamine_first", rules("持续恶心呕吐2周，近3天几乎不能进食。"))
        self.assertIn("hypokalaemia", rules("钾2.8 mmol/L。"))
        self.assertIn("hypoglycaemia_drug", rules("仍按平时使用胰岛素。", "指尖血糖2.1 mmol/L。"))
        self.assertIn("sepsis_shock", rules("寒战、发热2天。", "血压84/50 mmHg，乳酸4.8 mmol/L。"))

    def test_negated_or_absent_findings_do_not_fire(self):
        self.assertEqual(rules("否认药物过敏史。无肢体无力，头颅CT未见出血。", "钾4.1 mmol/L，血压128/76 mmHg。"), [])
        self.assertNotIn("ectopic_unstable", rules("停经7周，心率82次/分，血压118/70 mmHg。", "右附件区包块约2 cm。"))
        self.assertNotIn("thiamine_first", rules("呕吐、腹泻3天。"))           # short illness, still eating: no rule
        self.assertNotIn("sepsis_shock", rules("发热3天。", "血压132/78 mmHg。"))

    def test_pneumonia_severity_is_computed_not_guessed(self):
        from medtrace.safety_points import pneumonia_severity
        case = parse_case({"case_id": "T", "record_cutoff": "T0", "sources": [
            {"source_id": "S1", "content": "男性，56岁，发热伴意识错乱、定向障碍1天。"},
            {"source_id": "S2", "content": "T：38.4℃，R：20次/分，BP：136/88mmHg。"},
            {"source_id": "S3", "content": "BUN 7.34 mmol/L↑，血小板 132×10⁹/L，白细胞总数 13.1×10⁹/L；血气分析（未吸氧）PaO2 67mmHg；胸部X线提示“肺炎可能性大”。"}]}, 0)
        s = pneumonia_severity(case)
        self.assertIn("CURB-65 = 2分", s)                             # confusion + urea > 7
        self.assertIn("PaO2/FiO2≤250（否）", s)                       # 67 / 0.21 = 319
        self.assertIn("多肺叶浸润（资料未提供）", s)
        self.assertIn("满足2项次要标准、1项资料未提供", s)
        quiet = parse_case({"case_id": "Q", "record_cutoff": "T0", "sources": [
            {"source_id": "S1", "content": "男性，67岁，发热、咳嗽3天，胸片示右下肺斑片状浸润影。"}]}, 0)
        self.assertIn("意识障碍（资料未提供）", pneumonia_severity(quiet))   # silence is unknown, not "no"
        self.assertIsNone(pneumonia_severity(parse_case({"case_id": "N", "record_cutoff": "T0",
                                                         "sources": [{"source_id": "S1", "content": "腹痛2天，血压120/80 mmHg。"}]}, 0)))

    def test_planned_result_items_are_dropped_and_hedged_disposition_detected(self):
        from medtrace import verify as V
        from medtrace.note import Note, Statement
        case = parse_case({"case_id": "T", "record_cutoff": "T0", "sources": [
            {"source_id": "S1", "content": "发热伴意识障碍，痰培养已送检，结果待回报。"}]}, 0)
        n = Note()
        n.sections["treatment_plan"] = [Statement("拟行腰椎穿刺送脑脊液常规、生化检查；追踪痰培养结果。", ["S1"], "investigation"),
                                        Statement("收入ICU或普通病房加强监护。", ["S1"], "treatment")]
        n.review_items = [{"type": "missing", "description": "缺脑脊液检查结果，影响诊断。", "origin": "model"},
                          {"type": "missing", "description": "待痰培养结果回报以调整抗感染。", "origin": "model"},
                          {"type": "missing", "description": "缺既往用药史。", "origin": "model"}]
        self.assertEqual(V.drop_planned_result_items(n, case), ["缺脑脊液检查结果，影响诊断。"])
        self.assertEqual(len(n.review_items), 2)                       # pending result named in the records stays
        self.assertTrue(V.hedged_disposition(n))
        # the records may name a missing test more briefly than the review item: that item is about record content, keep it
        brief = parse_case({"case_id": "B", "record_cutoff": "T0", "sources": [
            {"source_id": "S1", "content": "反复喘息5年；未提供血气及胸部影像；甲状腺及肝功能结果未齐。"}]}, 0)
        m = Note()
        m.sections["treatment_plan"] = [Statement("拟行动脉血气分析；完善甲状腺功能检查。", ["S1"], "investigation")]
        m.review_items = [{"type": "missing", "description": "缺血气分析结果，影响分级。", "origin": "model"},
                          {"type": "missing", "description": "缺甲状腺功能结果，无法排除甲亢。", "origin": "model"}]
        self.assertEqual(V.drop_planned_result_items(m, brief), [])
        # package smoke run, SYN001: records "未提供血气分析", item "缺动脉血气分析结果" (core "动脉血气" differs)
        syn001 = parse_case({"case_id": "C", "record_cutoff": "T0", "sources": [
            {"source_id": "S1", "content": "入院初步考虑下呼吸道感染；未提供血气分析。"}]}, 0)
        m.sections["treatment_plan"] = [Statement("拟行动脉血气分析评估氧合。", ["S1"], "investigation")]
        m.review_items = [{"type": "missing", "description": "缺动脉血气分析结果，影响低氧程度分级。", "origin": "model"}]
        self.assertEqual(V.drop_planned_result_items(m, syn001), [])
        n.sections["treatment_plan"][1] = Statement("收入普通病房，若出现低血压或氧合恶化转ICU。", ["S1"], "treatment")
        self.assertFalse(V.hedged_disposition(n))

    def test_points_reach_the_generation_prompt(self):
        cfg = Config(development=True, api_base="mock://", repair_call=False)
        pipe = Pipeline(cfg, LLMClient(cfg, mock=MockLLM()))
        case = parse_case({"case_id": "T", "record_cutoff": "T0", "sources": [{"source_id": "S1", "content": "患者乏力伴四肢软弱2天，血钾2.8 mmol/L。"}]}, 0)
        with patch.object(pipe.client, "chat", wraps=pipe.client.chat) as chat:
            res = pipe.run_case(case)
        self.assertIn("<case_safety_points>", chat.call_args_list[0].args[1])
        self.assertEqual(res.log["safety_points"], ["hypokalaemia"])


def pneumonia(age=56, rr=20, bp="120/80", bun="5.0", pao2="80", wbc="8.0", plt="200", temp="37.5",
              mental="神志清楚", lobes="右下肺单叶斑片影"):
    """A pneumonia record with every severity item recorded unless a field is set to None."""
    parts = [f"男性，{age}岁，发热咳嗽3天。" if age else "男性，发热咳嗽3天。",
             mental and f"{mental}。", rr and f"R {rr}次/分。", bp and f"血压{bp} mmHg。", temp and f"体温{temp}℃。",
             bun and f"BUN {bun} mmol/L。", wbc and f"白细胞{wbc}×10⁹/L。", plt and f"血小板{plt}×10⁹/L。",
             pao2 and f"血气分析（未吸氧）PaO2 {pao2} mmHg。", f"胸部CT示{lobes}，考虑肺炎。" if lobes else "胸片示右下肺斑片影，考虑肺炎。"]
    return parse_case({"case_id": "P", "record_cutoff": "T0",
                       "sources": [{"source_id": "S1", "content": "".join(p for p in parts if p)}]}, 0)


class PneumoniaGrade(unittest.TestCase):
    def grade(self, **kw):
        from medtrace.safety_points import pneumonia_grade
        return pneumonia_grade(pneumonia(**kw))

    def guard(self, case, *texts, plan=()):
        from medtrace.note import Note, Statement
        from medtrace.safety_points import enforce_pneumonia_grade
        n = Note()
        n.sections["diagnostic_discussion"] = [Statement(t, ["S1"], "assessment") for t in texts]
        n.sections["treatment_plan"] = [Statement(t, ["S1"], "treatment") for t in plan] or [Statement("拟完善血气分析。", ["S1"])]
        items = enforce_pneumonia_grade(n, case)
        return [s.text for s in n.sections["diagnostic_discussion"]], [s.text for s in n.sections["treatment_plan"]], [r["code"] for r in items]

    def test_incomplete_grading_is_never_rendered_as_not_severe(self):
        # SYN001 pattern: mental status, urea, PaO2 and lobes not recorded; the model concluded "非重症" anyway
        case = pneumonia(age=67, rr=23, bp="132/78", bun=None, pao2=None, plt=None, mental=None, lobes=None)
        self.assertEqual(self.grade(age=67, rr=23, bp="132/78", bun=None, pao2=None, plt=None, mental=None, lobes=None)["status"],
                         "incomplete")
        disc, plan, codes = self.guard(case, "社区获得性肺炎（可能性大）：CURB-65评分1分，非重症，但需完善评估。",
                                       "目前为轻症肺炎。", plan=["可门诊治疗，密切随访。"])
        joined = "".join(disc + plan)
        for word in ("非重症", "轻症", "可门诊"):
            self.assertNotIn(word, joined)
        self.assertIn("严重程度暂无法完整分级（缺", disc[0])
        self.assertIn("风险分层暂无法确定（CURB-65缺", plan[0])          # score 1 + 2 unknown items could reach 2
        self.assertEqual(codes, ["pneumonia_grade_incomplete"])
        kept, _, codes = self.guard(case, "资料不足，不能判定为非重症。")    # a negated mention is not a conclusion
        self.assertEqual((kept, codes), (["资料不足，不能判定为非重症。"], []))

    def test_complete_grading_must_match_the_computed_value(self):
        mild = pneumonia()                                                   # every item recorded, none met
        self.assertEqual(self.guard(mild, "社区获得性肺炎，符合重症肺炎标准。")[2], ["pneumonia_grade_mismatch"])
        self.assertEqual(self.guard(mild, "社区获得性肺炎，不符合重症肺炎标准（重症肺炎主要标准无，次要标准0项）。")[2], [])
        severe = pneumonia(rr=32, mental="意识模糊", bun="8.2")             # 3 minor criteria met
        disc, _, codes = self.guard(severe, "社区获得性肺炎，非重症。")
        self.assertEqual((disc, codes), (["社区获得性肺炎，非重症。"], ["pneumonia_grade_mismatch"]))   # flagged, not rewritten

    def test_boundary_values(self):
        g = self.grade
        self.assertEqual(g(rr=30)["minor"][0][1], True)
        self.assertEqual(g(rr=29)["minor"][0][1], False)
        self.assertEqual(g(bun="7.0")["curb"][1][1], False)                 # CURB-65: urea > 7
        self.assertEqual(g(bun="7.1")["curb"][1][1], True)
        self.assertEqual(g(bun="7.1")["minor"][4][1], False)                # severe CAP: BUN >= 7.14
        self.assertEqual(g(bun="7.14")["minor"][4][1], True)
        self.assertEqual(g(pao2="52")["minor"][1][1], True)                 # 52 / 0.21 = 247.6 <= 250
        self.assertEqual(g(pao2="53")["minor"][1][1], False)                # 252.4
        self.assertEqual(g(bp="90/70")["curb"][3][1], False)                # SBP < 90
        self.assertEqual(g(bp="120/60")["curb"][3][1], True)                # DBP <= 60
        self.assertEqual(g(age=65)["curb"][4][1], True)
        self.assertEqual(g(age=64)["curb"][4][1], False)
        self.assertEqual(g(rr=31, mental="意识模糊")["status"], "not_severe")            # 2 met, 0 unknown
        self.assertEqual(g(rr=31, mental="意识模糊", lobes=None)["status"], "incomplete") # 2 met + 1 unknown could be 3
        self.assertEqual(g(rr=31, mental="意识模糊", bun="7.2")["status"], "severe")      # 3 met


if __name__ == "__main__":
    unittest.main()
