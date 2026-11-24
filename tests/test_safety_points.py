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


if __name__ == "__main__":
    unittest.main()
