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
