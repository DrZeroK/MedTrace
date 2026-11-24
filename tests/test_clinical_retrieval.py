"""Regression checks for offline ranking and local textbook release boundaries."""

import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from eval.clinical_intake_retrieval import read_guides
from eval.practice_retrieval import _intake
from eval.rag_benchmark import ROOT, benchmark
from medtrace.knowledge import KnowledgeBase, KnowledgeError, adult_documented, alias_hit, build_database, search_tokens
from medtrace.retrieval import expand_findings, prepare_query, select_cards
from scripts.textbook_kb import organize_drafts
from test_knowledge import entry


class ClinicalRetrievalTests(unittest.TestCase):
    def test_offline_guideline_relevance(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network disabled")):
            result = benchmark()
        baseline = result["modes"]["bm25"]["at_k"][5]
        reranked = result["modes"]["reranked"]["at_k"][5]
        self.assertEqual(result["queries"], 50)
        self.assertGreater(reranked["recall"], .90)
        self.assertLess(reranked["irrelevant_ratio"], baseline["irrelevant_ratio"])
        self.assertEqual(reranked["negative_abstention"], 1)

    def test_finding_expansion_retains_scope_and_improves_paraphrase_recall(self):
        result = benchmark(question_path=ROOT / "eval/retrieval_variants.v2.jsonl")
        base = result["modes"]["reranked_without_expansion"]["at_k"][5]
        tuned = result["modes"]["reranked"]["at_k"][5]
        self.assertGreater(tuned["recall"], base["recall"])
        self.assertEqual(tuned["negative_abstention"], 1)
        for text in ("干咳持续一个月", "其父亲突然讲不出话，随后恢复说话", "否认腹腔游离液体"):
            with self.subTest(text=text):
                clauses, _ = prepare_query(text)
                self.assertEqual(expand_findings(clauses), clauses)

    def test_pregnancy_cards_require_a_patient_who_can_be_pregnant(self):
        lines = (ROOT / "knowledge/guidelines.v1.jsonl").read_text(encoding="utf-8").splitlines()
        rows = [(json.loads(line), -1.0) for line in lines if line.strip()]

        def hits(query):
            clauses, original = prepare_query(query)
            return [card["population"] for card in select_cards(
                rows, expand_findings(clauses), original, alias_hit=alias_hit,
                adult_documented=adult_documented, search_tokens=search_tokens)]

        for sex in ("男，58岁", "58岁男性", "性别：男 年龄：58岁", "患者男 58岁"):
            with self.subTest(sex=sex):
                self.assertNotIn("pregnancy", hits({"chief": sex + "，皮肤巩膜黄染2周", "labs": "总胆汁酸 85 μmol/L"}))
        self.assertIn("pregnancy", hits({"chief": "女，30岁，孕32周，手足心痒1周，男性伴侣体健",
                                         "labs": "总胆汁酸 85 μmol/L"}))

    def test_expanded_guidelines_validate_and_match_their_scopes(self):
        cards = ROOT / "knowledge" / "guidelines.v2.jsonl"
        entries = read_guides([cards])
        self.assertEqual({row["source_kind"] for row in entries.values()}, {"guideline", "consensus"})
        result = benchmark(cards, ROOT / "eval" / "retrieval_guidelines.v2.jsonl")
        ranked = result["modes"]["reranked"]["at_k"][5]
        self.assertEqual(ranked["recall"], 1)
        self.assertEqual(ranked["negative_abstention"], 1)
        self.assertEqual(ranked["irrelevant_ratio"], 0)

    def test_routine_results_and_pregnancy_scope_across_guideline_sets(self):
        rows = [(json.loads(line), -1.0) for name in ("v1", "v2")
                for line in (ROOT / f"knowledge/guidelines.{name}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]

        def hits(query):
            clauses, original = prepare_query(query)
            return [card["id"] for card in select_cards(
                rows, expand_findings(clauses), original, alias_hit=alias_hit,
                adult_documented=adult_documented, search_tokens=search_tokens)]

        # Test names present in every record must not pull in disease cards when results are normal.
        self.assertEqual(hits({"history": "男，45岁，体检",
                               "exams": "BMI 22.1 kg/m2，腰围 82 cm，心脏超声：心脏结构及功能正常，骨密度T值 -0.5，甲状腺超声未见结节",
                               "labs": "空腹血糖 5.1 mmol/L，HbA1c 5.4%，TSH 2.1 mIU/L，eGFR 98，UACR 8 mg/g，"
                                       "血淀粉酶 60 U/L，脂肪酶 30 U/L，LDL-C 2.6 mmol/L，乙肝核心抗体阴性"}), [])
        pregnant = hits({"chief": "女，29岁，孕26周，OGTT异常", "labs": "空腹血糖 5.3 mmol/L，高血糖"})
        self.assertIn("kb:hip-2022-i:ogtt", pregnant)
        self.assertFalse(any(card.startswith("kb:diabetes-cds-2024:") for card in pregnant))
        self.assertIn("kb:diabetes-cds-2024:diagnosis", hits({"chief": "女，52岁，口渴多饮3月，确诊糖尿病待分型"}))

    def test_population_labels_are_validated(self):
        with self.assertRaisesRegex(KnowledgeError, "population"):
            build_database([entry(population="pregnacy")], Path("/nonexistent/unused.sqlite"), "fixture")

    def test_unresolved_differential_is_not_masked_as_negated(self):
        for text in ("不能排除哮喘", "待排除哮喘", "考虑哮喘"):
            with self.subTest(text=text):
                self.assertIn("哮喘", " ".join(clause for clause, _ in prepare_query(text)[0]))
        for text in ("已排除哮喘", "排除哮喘", "否认哮喘", "母亲哮喘", "若出现哮喘"):
            with self.subTest(text=text):
                self.assertNotIn("哮喘", " ".join(clause for clause, _ in prepare_query(text)[0]))

    def test_practice_intake_keeps_only_disclosed_evidence(self):
        chart = "姓名：模拟姓名\n年龄：55岁\n主  诉：胸痛\n辅助检查\n心电图已查\n初步诊断：\n后续结论"
        self.assertEqual(_intake(chart), ["年龄：55岁", "主  诉：胸痛", "辅助检查", "心电图已查"])
        with self.assertRaises(ValueError):
            _intake("主诉：胸痛")
        with self.assertRaises(ValueError):
            _intake("初步诊断：\n主诉：胸痛")

    def test_measurement_unit_cannot_trigger_an_unrelated_card(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unit.sqlite"
            build_database([entry(title="甲状旁腺检查", aliases=["mmol/L"], scope="general")], path, "fixture")
            self.assertEqual(KnowledgeBase(path).retrieve("血糖 6 mmol/L"), [])

    def test_structured_query_and_negation_for_approved_cards(self):
        with TemporaryDirectory() as directory:
            db = Path(directory) / "fixture.sqlite"
            build_database([entry(source_id="fixture-v1", categories=["tests"])], db, "fixture")
            kb = KnowledgeBase(db)
            with patch.object(socket, "socket", side_effect=AssertionError("network disabled")):
                hits = kb.retrieve({"history": "50岁", "labs": "potassium 5 mmol/L"}, categories=["tests"])
                self.assertEqual(hits[0]["source_id"], "fixture-v1")
                self.assertIn("potassium", hits[0]["matched_terms"])
                self.assertEqual(kb.retrieve("50岁，未提供：potassium"), [])
                self.assertEqual(kb.retrieve("50岁 potassium", categories=["treatment"]), [])
                self.assertEqual(kb.retrieve("50岁 potassium1"), [])

    def test_textbook_rechunking_preserves_location_and_draft_status(self):
        content = ("这是为测试合成的较长段落，用于校验小节拆分。" * 38
                   + "检验检出限为0.65 μmol/L。")
        original = entry(text=content, status="draft", license="pending", source_id="fixture-v10",
                         structure={"chapter": "第一章", "label": "【诊断与鉴别诊断】"})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source.write_text(json.dumps(original) + "\n", encoding="utf-8")
            output = root / "cards.jsonl"
            stats = organize_drafts(source, output)
            cards = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertGreater(stats["chunks"], 1)
            self.assertTrue(any("0.65 μmol/L" in card["text"] for card in cards))
            for card in cards:
                self.assertEqual(card["parent_id"], original["id"])
                self.assertEqual(card["locator"], original["locator"])
                self.assertEqual(card["categories"], ["differential", "diagnosis"])
                self.assertEqual(card["source_id"], "fixture-v10")
            with self.assertRaisesRegex(KnowledgeError, "no approved entries"):
                build_database(cards, root / "release.sqlite", "draft")
