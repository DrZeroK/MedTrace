"""Self-authored scope contrasts. No real clinical text or external inference."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from medtrace import context as C
from medtrace.config import Config, ConfigError, load_config
from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger, digest
from medtrace.llm import LLMClient
from medtrace.mock_llm import MockLLM
from medtrace.note import Statement
from medtrace.pipeline import Pipeline, prompt_fingerprint
from medtrace.verify import check_statement


class EvidenceStatusTests(unittest.TestCase):
    def test_assertion_drift_and_controls_in_features_and_discussion(self):
        examples = [
            ("痰培养待回报，未提供血气分析。", "未行血气分析评估缺氧。", "unsupported_test_status"),
            ("活动耐量下降1个月，近3天夜间憋醒、需垫高枕头。",
             "表现为突发呼吸困难和低氧。", "unsupported_sudden_onset"),
            ("血气分析已采样，结果待回报。", "血气分析结果正常。", "unsupported_test_status"),
            ("未行血气分析。", "未行血气分析。", None),
            ("劳力性气促2个月，今日突发呼吸困难。", "今日突发呼吸困难。", None),
            ("胸闷2个月。", "若突发胸闷则考虑进一步复核。", None),
            ("胸闷2个月，昨晚突发头痛。", "昨晚突发头痛。", None),
            ("既往肝功能结果待回报。", "本次未行肝功能检查。", None),
            ("尿培养结果待回报。", "未行血培养。", None),
            # New wording and entities exercise the same boundaries independently.
            ("胸片已完成，报告尚未出具。", "胸片未做。", "unsupported_test_status"),
            ("头痛反复半年，近两日加重。", "患者突然出现头痛。", "unsupported_sudden_onset"),
            ("昨晚头痛，否认突发头痛。", "昨晚突发头痛。", "unsupported_sudden_onset"),
            ("今日未做胸片，昨日报告未提供。", "今日未做胸片。", None),
            ("昨日尿培养报告未提供。", "今日确认未行尿培养。", None),
            ("本次没有血气结果。", "如未行血气分析，可核对医嘱。", None),
        ]
        for source, claim, expected in examples:
            case = parse_case({"case_id": "scope", "record_cutoff": "T0",
                               "sources": [{"source_id": "S", "content": source}]}, 0)
            ledger = build_ledger(case, context_mode="zh_context_v1")
            for section in ("case_features", "diagnostic_discussion"):
                with self.subTest(claim=claim, section=section):
                    findings = check_statement(section, 0, Statement(claim, ["S"]), case, ledger)
                    found = {f.code for f in findings if f.code in
                             ("unsupported_test_status", "unsupported_sudden_onset")}
                    self.assertEqual(found, {expected} if expected else set())
                    self.assertTrue(all(f.text == claim and "S" in f.message for f in findings if f.code in found))


CONTRASTS = [
    ("患者发热。", "发热", "affirmed"), ("否认发热。", "发热", "negated"),
    ("没有咳嗽。", "咳嗽", "negated"), ("不伴胸痛。", "胸痛", "negated"),
    ("未见肺炎征象。", "肺炎", "negated"), ("肺炎可能。", "肺炎", "uncertain"),
    ("考虑肺炎。", "肺炎", "uncertain"), ("肺炎待排。", "肺炎", "uncertain"),
    ("不能排除肺炎。", "肺炎", "uncertain"), ("尚不能除外肺炎。", "肺炎", "uncertain"),
    ("不除外肺炎。", "肺炎", "uncertain"), ("疑似肺炎。", "肺炎", "uncertain"),
    ("肺炎尚未明确。", "肺炎", "uncertain"), ("可疑肺炎。", "肺炎", "uncertain"),
    ("未能排除肺炎。", "肺炎", "uncertain"), ("为排除肺炎拟行检查。", "肺炎", "uncertain"),
    ("未见肺炎相关记录。", "肺炎", "missing"), ("未提供过敏史。", "过敏", "missing"),
    ("过敏史不详。", "过敏", "missing"), ("培养结果待回报。", "培养", "missing"),
    ("未查血钾。", "血钾", "missing"), ("未记录血压。", "血压", "missing"),
    ("无明显诱因出现咳嗽。", "咳嗽", "affirmed"), ("患者无尿。", "无尿", "affirmed"),
    ("患者乏力。", "乏力", "affirmed"), ("无痛性包块。", "包块", "affirmed"),
    ("不能否认肺炎。", "肺炎", "unknown"), ("并非没有咳嗽。", "咳嗽", "unknown"),
    ("不是无胸痛。", "胸痛", "unknown"), ("不能说没有发热。", "发热", "unknown"),
    ("否认胸痛，但有咳嗽。", "胸痛", "negated"), ("否认胸痛，但有咳嗽。", "咳嗽", "affirmed"),
    ("考虑肺炎，血压正常。", "血压", "affirmed"), ("未见肺炎记录，但有发热。", "发热", "affirmed"),
    ("无咳嗽、咳痰。", "咳痰", "negated"), ("无咳嗽、咳痰，现有发热。", "发热", "affirmed"),
    ("胸部压痛阴性。", "压痛", "negated"), ("反跳痛未引出。", "反跳痛", "negated"),
    ("已排除肺炎。", "肺炎", "negated"), ("排除肺炎后观察。", "肺炎", "negated"),
    ("父亲有糖尿病。", "糖尿病", "affirmed"), ("母亲否认糖尿病。", "糖尿病", "negated"),
    ("既往有哮喘。", "哮喘", "affirmed"), ("既往无哮喘。", "哮喘", "negated"),
    ("若出现发热需复查。", "发热", "affirmed"), ("目前发热。", "发热", "affirmed"),
    ("否认发热；考虑肺炎。", "肺炎", "uncertain"), ("未见异常记录。", "异常", "missing"),
    ("未提供肾功能结果。", "肾功能", "missing"), ("肾功能结果未回。", "肾功能", "missing"),
    ("胸痛不除外。", "胸痛", "uncertain"), ("血糖未知。", "血糖", "missing"),
    ("无菌敷料覆盖伤口。", "伤口", "affirmed"), ("无创检查提示异常。", "异常", "affirmed"),
    ("尚未排除肺炎。", "肺炎", "uncertain"), ("没有胸痛，然而咳嗽明显。", "咳嗽", "affirmed"),
    ("否认咳嗽，不过存在胸痛。", "胸痛", "affirmed"), ("药物过敏史：无。", "过敏", "negated"),
    ("无尿频、尿急。", "尿频", "negated"), ("无尿频、尿急。", "尿急", "negated"),
]


class ContextTests(unittest.TestCase):
    def test_official_config_ignores_development_candidates(self):
        directory = Path(tempfile.mkdtemp(prefix="medtrace-official-context-"))
        (directory / ".env").write_text("MODEL_NAME=test\nENDPOINT=http://127.0.0.1/test\n")
        with patch("medtrace.config.ROOT", directory), patch.dict(os.environ, {
            "CONTEXT_MODE": C.VERSION, "PROMPT_CANDIDATE_PATH": "/absent/candidate.json"}):
            cfg = load_config()
        self.assertEqual(cfg.context_mode, "legacy")
        self.assertEqual(cfg.prompt_candidate_path, "")
        self.assertFalse(cfg.development)

    def test_sixty_assertion_contrasts(self):
        self.assertEqual(len(CONTRASTS), 60)
        for text, term, value in CONTRASTS:
            with self.subTest(text=text, term=term):
                states = C.term_attributes(text, term)
                self.assertTrue(states)
                self.assertEqual(states[0]["assertion"], value)
                for s in C.analyze(text):
                    self.assertTrue(0 <= s.start < s.end <= len(text))

    def test_person_and_time_do_not_cross_boundaries(self):
        text = "父亲有糖尿病，本人无高血压。既往有哮喘，目前出现胸痛，若出现发热需复查。"
        for term, dimension, value in (("糖尿病", "experiencer", "family"), ("高血压", "experiencer", "patient"),
                                       ("哮喘", "temporality", "historical"), ("胸痛", "temporality", "current"),
                                       ("发热", "temporality", "hypothetical")):
            self.assertEqual(C.term_attributes(text, term)[0][dimension], value)

    def test_bare_comma_continuations_are_ambiguous_not_inferred_negative(self):
        cases = [("否认哮喘，高脂血症史，否认手术史。", "高脂血症", "unknown"),
                 ("不伴胸痛，恶心呕吐。", "恶心呕吐", "unknown"),
                 ("无胸痛，咳嗽，咳痰。", "咳痰", "unknown"),
                 ("否认胸痛，咳嗽3天。", "咳嗽", "affirmed"),
                 ("无发热，咳嗽明显。", "咳嗽", "affirmed"),
                 ("无发热，但有咳嗽。", "咳嗽", "affirmed"),
                 ("无发热，患者咳嗽。", "咳嗽", "affirmed"),
                 ("无皮疹，巩膜中度黄染。", "巩膜", "affirmed"),
                 ("无腹痛，左上腹可触及肿块。", "肿块", "affirmed"),
                 ("否认胸痛，无尿。", "无尿", "affirmed"),
                 ("无发热，无痛性包块。", "包块", "affirmed"),
                 ("无胸痛，无咳嗽。", "咳嗽", "negated"),
                 ("无发热，否认咳嗽史。", "咳嗽", "negated"),
                 ("无发热，双肺未闻及啰音。", "啰音", "negated"),
                 ("未见肺炎，未提供培养结果。", "培养", "missing"),
                 ("未见胸痛记录，咳嗽。", "咳嗽", "affirmed"),
                 ("无发热；咳嗽。", "咳嗽", "affirmed")]
        for text, term, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(C.term_attributes(text, term)[0]["assertion"], expected)

    def test_ambiguous_source_yields_review_instead_of_definite_flip(self):
        for source, statement in (("否认哮喘，高脂血症史，否认手术史。", "否认哮喘、高脂血症及手术史。"),
                                  ("不伴胸痛，恶心呕吐。", "不伴胸痛、恶心呕吐。")):
            case = parse_case({"case_id": "T", "record_cutoff": "T0", "sources": [{"source_id": "S", "content": source}]}, 0)
            L = build_ledger(case, context_mode=C.VERSION)
            findings = check_statement("case_features", 0, Statement(statement, ["S"]), case, L)
            self.assertNotIn("negation_flip", {f.code for f in findings})
            self.assertIn("context_scope_ambiguous", {f.code for f in findings})
            self.assertTrue(all(f.severity != "high" for f in findings))

    def test_legacy_is_unchanged_and_new_scopes_are_traceable(self):
        case = parse_case({"case_id": "T", "record_cutoff": "T0", "sources": [{"source_id": "S", "content": "父亲有糖尿病。患者未见肺炎相关记录。"}]}, 0)
        legacy = build_ledger(case)
        self.assertEqual(legacy, build_ledger(case, context_mode="legacy"))
        self.assertTrue(all(not f.contexts for f in legacy.facts))
        enhanced = build_ledger(case, context_mode=C.VERSION)
        self.assertEqual([f.text for f in enhanced.facts], [f.text for f in legacy.facts])
        self.assertIn("上下文作用域", digest(enhanced))
        codes = {f.code for f in check_statement("case_features", 0, Statement("患者有糖尿病。", ["S"]), case, enhanced)}
        self.assertIn("context_experiencer", codes)
        self.assertNotIn("context_experiencer", {f.code for f in check_statement("case_features", 0, Statement("父亲有糖尿病。", ["S"]), case, enhanced)})

    def test_development_candidate_is_validated_and_fixed_prompt_survives(self):
        d = Path(tempfile.mkdtemp(prefix="medtrace-context-test-"))
        p = d / "candidate.json"
        instruction = "先列出病例核心问题，再按问题组织鉴别分析和诊疗计划。"
        candidate = {"schema_version": 1, "instruction": instruction, "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
                     "base_prompt": prompt_fingerprint(Config().prompt_version)}
        p.write_text(json.dumps(candidate))
        cfg = Config(development=True, api_base="mock://", context_mode=C.VERSION, prompt_candidate_path=str(p), repair_call=False)
        pipe = Pipeline(cfg, LLMClient(cfg, mock=MockLLM()))
        self.assertEqual(pipe.candidate["instruction"], instruction)
        case = parse_case({"case_id": "T", "record_cutoff": "T0", "sources": [{"source_id": "S", "content": "患者发热。"}]}, 0)
        with patch.object(pipe.client, "chat", wraps=pipe.client.chat) as chat:
            pipe.run_case(case)
            user = chat.call_args.args[1]
            self.assertLess(user.index(instruction), user.index("[task:a1/v3]"))
            self.assertIn("资料截止时间：T0", user)
            self.assertIn("缺失不等于正常", user)
            self.assertIn('"case_features":', user)
        cfg.development = False
        with self.assertRaises(ConfigError):
            Pipeline(cfg, LLMClient(cfg, mock=MockLLM()))
        cfg.development = True
        candidate["base_prompt"] = "wrong"
        p.write_text(json.dumps(candidate))
        with self.assertRaises(ConfigError):
            Pipeline(cfg, LLMClient(cfg, mock=MockLLM()))

