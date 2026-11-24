"""Acute aortic syndrome antithrombotic screen (medtrace/aortic.py): the A01-A36 regression set and the P05 fixed
regression from docs/AORTIC_ANTITHROMBOTIC_RULE.md §10. Every record here is synthetic; the P05 excerpt reproduces
the practice case's wording. Passing these tests shows the spec scenarios are met, not clinical validity."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from medtrace import aortic as A                                       # noqa: E402
from medtrace import verify as V                                       # noqa: E402
from medtrace.config import Config                                     # noqa: E402
from medtrace.inputs import parse_case                                 # noqa: E402
from medtrace.ledger import build_ledger                               # noqa: E402
from medtrace.note import Note, Statement                              # noqa: E402
from medtrace.pipeline import Pipeline                                 # noqa: E402


def case(*contents):
    return parse_case({"case_id": "A", "record_cutoff": "T0", "sources": [{"source_id": f"S{i + 1}", "content": c}
                                                   for i, c in enumerate(contents)]}, 0)


def screen(record, plan, lang="zh"):
    """(screened plan statement, events, full plan texts) for `plan` placed between two unrelated safe items."""
    c = case(*([record] if isinstance(record, str) else record))
    n = Note()
    n.sections["treatment_plan"] = [Statement("控制血压及心率。", ["S1"]), Statement(plan, ["S1"]), Statement("监测生命体征。", ["S1"])]
    events = A.screen_plan(n, c, lang)
    texts = [s.text for s in n.sections["treatment_plan"]]
    return texts[1], events, texts


IMH = "突发胸背痛5小时。急诊大血管CTA示主动脉壁内血肿，以“主动脉壁内血肿”收入CCU。"
AD = "突发撕裂样胸痛3小时。急诊CTA示急性主动脉夹层（Stanford B型）。"

# id, record, plan, expected state, expected actions, must-contain / must-not-contain in the screened text
CASES = [
    ("A01", IMH, "继续阿司匹林100mg/日，氯吡格雷75mg/日。", A.CONFIRMED_ACTIVE, {A.BLOCK}, ["不建议常规双联抗血小板治疗"], ["mg"]),
    ("A02", (IMH, "外院予阿司匹林300mg、氯吡格雷300mg口服。"), "外院已予阿司匹林300mg、氯吡格雷300mg。",
     A.CONFIRMED_ACTIVE, set(), ["外院已予阿司匹林300mg、氯吡格雷300mg"], []),
    ("A03", AD, "予阿替普酶全身溶栓。", A.CONFIRMED_ACTIVE, {A.BLOCK}, ["属全身溶栓禁忌"], ["阿替普酶"]),
    ("A04", "胸痛伴双上肢血压差。高度怀疑主动脉夹层，急查CTA。", "予替奈普酶全身溶栓。", A.SUSPECTED_ACTIVE, {A.BLOCK},
     ["属全身溶栓禁忌"], ["替奈普酶"]),
    ("A05", "胸痛。考虑主动脉夹层可能，待CTA。", "给予肝素抗凝。", A.SUSPECTED_ACTIVE, {A.BLOCK}, ["尚未排除的急性主动脉综合征"], ["给予肝素"]),
    ("A06", "胸痛。本次CTA明确排除主动脉夹层。诊断急性冠脉综合征。", "予阿司匹林100mg、氯吡格雷75mg双抗治疗。",
     A.RULED_OUT, set(), ["予阿司匹林100mg、氯吡格雷75mg双抗治疗"], []),
    ("A07", ("慢性主动脉夹层，病情稳定。", "持续性房颤，CHA2DS2-VASc 4分，有抗凝指征。"), "继续利伐沙班20mg qd。",
     A.STABLE_CHRONIC, set(), ["继续利伐沙班20mg qd"], []),
    ("A08", ("主动脉夹层修复术后5年，病情稳定。", "机械瓣置换术后。"), "继续华法林抗凝，INR目标2.0-3.0。",
     A.STABLE_POST_REPAIR, set(), ["继续华法林抗凝"], []),
    ("A09", (AD, "机械瓣置换术后长期服用华法林。"), "继续华法林。", A.CONFIRMED_ACTIVE, {A.REVIEW_URGENT},
     ["机械瓣膜相关血栓栓塞风险", "紧急联合评估抗凝方案"], ["继续华法林", "停用"]),
    ("A10", IMH, "依诺肝素40mg皮下注射预防DVT。", A.CONFIRMED_ACTIVE, {A.REVIEW}, ["考虑机械性预防"], ["依诺肝素40mg"]),
    ("A11", "主动脉夹层修复术后第3天，止血稳定。", "低分子肝素预防VTE。", A.PERIOPERATIVE, {A.REVIEW}, ["考虑机械性预防"], ["绝对禁忌", "低分子肝素预防VTE"]),
    ("A12", "急诊CTA示急性A型主动脉夹层累及冠脉开口。", "予阿司匹林100mg、氯吡格雷75mg双抗治疗。", A.CONFIRMED_ACTIVE,
     {A.BLOCK}, ["不建议常规双联抗血小板治疗"], ["75mg"]),
    ("A13", (AD, "1周前冠脉支架植入。"), "继续氯吡格雷75mg qd。", A.CONFIRMED_ACTIVE, {A.REVIEW_URGENT},
     ["近期冠脉支架相关血栓风险", "紧急联合评估抗血小板方案"], ["继续氯吡格雷"]),
    ("A14", IMH, "若排除夹层进展，可考虑恢复抗血小板治疗。", A.CONFIRMED_ACTIVE, {A.REVIEW},
     ["结合复查影像、主动脉病变稳定性及抗血小板适应证，由专科医师评估恢复治疗的必要性和时机"], ["若排除夹层进展"]),
    ("A15", IMH, "监测凝血功能及出血风险。", A.CONFIRMED_ACTIVE, set(), ["监测凝血功能及出血风险"], []),
    ("A16", IMH, "双联降压治疗。", A.CONFIRMED_ACTIVE, set(), ["双联降压治疗"], []),
    ("A17", "家族史：父亲患主动脉夹层。", "阿司匹林100mg qd二级预防。", A.HISTORY_ONLY, set(), ["阿司匹林100mg qd二级预防"], []),
    ("A18", "CT示主动脉附壁血栓。", "按适应证评估抗凝。", A.ABSENT, set(), ["按适应证评估抗凝"], []),
    ("A19", "既往主动脉夹层术后5年。本次出现新发壁内血肿。", "继续抗栓治疗。", A.CONFIRMED_ACTIVE, {A.BLOCK},
     ["不建议常规抗栓治疗"], ["继续抗栓"]),
    ("A20", (IMH, "外院已给予肝素治疗。"), "评估是否需要抗凝逆转。", A.CONFIRMED_ACTIVE, set(), ["评估是否需要抗凝逆转"], []),
    ("A21", IMH, "建议暂停或谨慎使用抗血小板药物。", A.CONFIRMED_ACTIVE, {A.REVIEW}, ["抗血小板治疗的必要性及安全性需由专科医师评估确定"],
     ["暂停", "谨慎使用"]),
    ("A22", IMH, "暂禁用抗凝药物，继续阿司匹林100mg/日。", A.CONFIRMED_ACTIVE, {A.BLOCK, A.REVIEW},
     ["不建议常规抗血小板治疗"], ["暂禁用", "100mg"]),
    ("A23", "2年前CTA未见主动脉夹层。本次新发胸痛，高度怀疑主动脉夹层，待CTA。", "予阿替普酶全身溶栓。", A.SUSPECTED_ACTIVE,
     {A.BLOCK}, ["属全身溶栓禁忌"], ["阿替普酶"]),
    ("A24", ("本次胸痛，考虑主动脉夹层可能。急诊CTA明确排除主动脉夹层。", "阵发性房颤，CHA2DS2-VASc 3分。"), "继续利伐沙班20mg qd。",
     A.RULED_OUT, set(), ["继续利伐沙班20mg qd"], []),
    ("A25", ("外院CT示主动脉夹层。", "我院CTA明确排除主动脉夹层，发病时间不详。"), "继续抗凝治疗。", A.UNKNOWN, {A.REVIEW},
     ["存在潜在冲突"], ["继续抗凝"]),
    ("A26", IMH, "肝素封管；采集枸橼酸抗凝血标本。", A.CONFIRMED_ACTIVE, set(), ["肝素封管；采集枸橼酸抗凝血标本"], []),
    ("A28", (IMH, "心内科会诊意见：继续氯吡格雷75mg qd。"), "继续氯吡格雷75mg qd。", A.CONFIRMED_ACTIVE, {A.REVIEW},
     ["继续氯吡格雷75mg qd"], []),
    ("A30", IMH, "DAPT with ASA and clopidogrel.", A.CONFIRMED_ACTIVE, {A.BLOCK}, ["Given the current aortic lesion"], ["ASA"]),
    ("A31", IMH, "Tirofiban / bivalirudin / fondaparinux.", A.CONFIRMED_ACTIVE, {A.BLOCK}, ["not recommended"], ["Tirofiban"]),
    ("A32", "急性主动脉壁内血肿。CTPA确诊急性肺栓塞。", "启动治疗性抗凝。", A.CONFIRMED_ACTIVE, {A.REVIEW_URGENT},
     ["急性肺栓塞的抗凝需求"], ["启动治疗性抗凝"]),
    ("A36", "否认既往主动脉夹层病史。本次急诊CTA示主动脉壁内血肿。", "继续双抗治疗。", A.CONFIRMED_ACTIVE, {A.BLOCK},
     ["不建议常规双联抗血小板治疗"], ["继续双抗"]),
]


class SpecRegression(unittest.TestCase):
    def test_cases(self):
        for cid, record, plan, state, actions, must, must_not in CASES:
            with self.subTest(cid):
                lang = "en" if plan[:1].isascii() else "zh"
                c = case(*([record] if isinstance(record, str) else record))
                self.assertEqual(A.aortic_state(c)[0], state)
                text, events, texts = screen(record, plan, lang)
                self.assertEqual({e.action for e in events}, actions, text)
                for s in must:
                    self.assertIn(s, text)
                for s in must_not:
                    self.assertNotIn(s, text)
                self.assertEqual((texts[0], texts[2]), ("控制血压及心率。", "监测生命体征。"))   # unrelated items intact
                self.assertTrue(text.strip() and text.rstrip("。")[-1:] not in "，,；;：:")      # no dangling fragment
                for e in events:
                    self.assertEqual((e.rule_id, e.disease_state), (A.RULE_ID, state))
                    self.assertTrue(e.reason_code and e.reference_ids)

    def test_intent_and_source(self):
        get = lambda text, src="": A.units(text, src)[0]
        u = get("继续阿司匹林100mg/日，氯吡格雷75mg/日")
        self.assertEqual((u.action, u.category), ("CONTINUE", "DUAL_ANTIPLATELET"))
        self.assertEqual(get("依诺肝素40mg皮下注射预防DVT").category, "PROPHYLACTIC_ANTICOAGULATION")
        self.assertEqual(get("启动治疗性抗凝").category, "THERAPEUTIC_ANTICOAGULATION")
        self.assertEqual(get("若病情稳定，可考虑恢复双抗").modality, "CONDITIONAL")
        self.assertEqual(get("建议暂停或谨慎使用抗血小板药物").modality, "OPTION")
        self.assertEqual(get("评估是否需要给药，由医生决定抗凝").action, "ASSESS_ONLY")
        self.assertEqual(get("低分子肝素预防DVT").action, "START")          # a noun-phrase plan item is still an order
        # A33: a history claim the records do not support is not a source fact
        self.assertEqual(get("外院已予阿司匹林", IMH).source, "GENERATED_PLAN")
        self.assertEqual(get("外院已予阿司匹林", IMH + "外院予阿司匹林300mg。").source, "SOURCE_FACT")
        text, events, _ = screen(IMH, "外院已予阿司匹林。")
        self.assertEqual((text, events), ("外院已予阿司匹林。", []))

    def test_dictionary(self):
        hit = lambda t: {c for c, *_ in A.drug_mentions(t)}
        self.assertLessEqual({"tirofiban", "bivalirudin", "fondaparinux"}, hit("Tirofiban / bivalirudin / fondaparinux"))
        self.assertEqual(hit("拜阿司匹灵、波立维、倍林达、拜瑞妥、泰毕全、克赛"),
                         {"aspirin", "clopidogrel", "ticagrelor", "rivaroxaban", "dabigatran", "enoxaparin"})
        self.assertEqual(hit("重组人尿激酶原"), {"prourokinase"})
        for trap in ("双联降压", "双联抗感染", "凝血功能检查", "抗凝血酶III测定", "枸橼酸抗凝采血管", "肝素封管", "导管局部溶栓",
                     "抗栓风险评估", "鱼精蛋白逆转", "维生素K1", "依达赛珠单抗", "主动脉附壁血栓", "aspirate"):
            with self.subTest(trap):
                self.assertEqual(hit(trap), set())

    def test_entities_need_aortic_context(self):
        for record in ("肠壁间血肿。", "AD病史10年（阿尔茨海默病）。", "主动脉瘤，直径45mm。", "CT示主动脉附壁血栓。"):
            with self.subTest(record):
                self.assertEqual(A.aortic_state(case(record))[0], A.ABSENT)
        self.assertEqual(A.aortic_state(case("CTA示主动脉弓降部IMH。"))[0], A.CONFIRMED_ACTIVE)
        self.assertEqual(A.aortic_state(case("既往主动脉夹层病史。"))[0], A.UNKNOWN)   # history without stability
        self.assertEqual(A.aortic_state(case("急诊CTA示主动脉夹层，生命体征稳定。"))[0], A.CONFIRMED_ACTIVE)

    def test_a27_multi_decision_sentence(self):
        c = case(IMH)
        n = Note()
        n.sections["treatment_plan"] = [Statement("控制血压；若病情稳定，考虑恢复双抗；监测生命体征。", ["S1"])]
        events = A.screen_plan(n, c, "zh")
        self.assertEqual({e.action for e in events}, {A.REVIEW})
        out = n.sections["treatment_plan"][0].text
        self.assertTrue(out.startswith("控制血压；结合复查影像"), out)
        self.assertTrue(out.endswith("；监测生命体征。"), out)
        self.assertNotIn("若病情稳定", out)

    def test_a29_dose_rule_without_aas(self):
        c = case("胸痛。诊断急性冠脉综合征。")
        text, events, _ = screen("胸痛。诊断急性冠脉综合征。", "阿司匹林300mg/日，氯吡格雷300mg/日。")
        self.assertEqual(events, [])
        codes = {f.code for f in V.check_statement("treatment_plan", 0, Statement(text, ["S1"]), c, build_ledger(c))}
        self.assertIn("loading_dose_as_maintenance", codes)
        self.assertEqual(A.loading_as_maintenance("阿司匹林300mg负荷后100mg/日维持"), [])
        self.assertEqual(A.loading_as_maintenance("氯吡格雷75mg/日"), [])

    def test_a34_a35_nonempty_and_idempotent(self):
        c = case(IMH)
        n = Note()
        n.sections["treatment_plan"] = [Statement("继续双抗治疗。", ["S1"])]
        first = A.screen_plan(n, c, "zh")
        self.assertTrue(first and n.sections["treatment_plan"][0].text.strip())
        after = [s.text for s in n.sections["treatment_plan"]]
        self.assertEqual(A.screen_plan(n, c, "zh"), [])
        self.assertEqual([s.text for s in n.sections["treatment_plan"]], after)
        for cid, record, plan, *_ in CASES:               # a second screening changes no text (real orders stay flagged)
            with self.subTest(cid):
                lang = "en" if plan[:1].isascii() else "zh"
                text, _, _ = screen(record, plan, lang)
                again, events, _ = screen(record, text, lang)
                self.assertEqual(again, text)
                self.assertTrue(all(e.replacement == e.original_candidate for e in events))

    def test_review_messages(self):
        _, events, _ = screen("急诊CTA示急性A型主动脉夹层累及冠脉开口。", "予阿司匹林100mg、氯吡格雷75mg双抗治疗。")
        msgs = A.review_messages(events, "zh")
        self.assertTrue(any("未作为可执行给药方案输出" in m for m in msgs))
        self.assertTrue(any("冠脉开口" in m and "紧急联合评估" in m for m in msgs))          # A12
        _, events, _ = screen((AD, "1周前冠脉支架植入。"), "继续氯吡格雷75mg qd。")
        self.assertIn("近期冠脉支架相关血栓风险与当前主动脉病变出血风险并存，需心内科与心血管外科紧急联合评估抗血小板方案。",
                      A.review_messages(events, "zh"))
        _, events, _ = screen((IMH, "心内科会诊意见：继续氯吡格雷75mg qd。"), "继续氯吡格雷75mg qd。")   # A28
        self.assertTrue(any("原医嘱未作改动" in m for m in A.review_messages(events, "zh")))
        for m in A.review_messages(events, "zh"):
            self.assertFalse(any(w in m for w in ("已停用", "已停药", "已会诊", "已确诊")))


class P05Regression(unittest.TestCase):
    record = ("患者突发胸痛5小时，就诊于外院，考虑急性冠脉综合征，予阿司匹林300mg、氯吡格雷300mg口服。急诊大血管CTA提示主动脉壁间血肿可能。"
              "急诊以“主动脉壁内血肿”收入CCU。", "初步诊断：1. 主动脉壁内血肿（Stanford B型可能）")
    plans = {
        "qwen3:8b": "抗血小板聚集：继续阿司匹林300mg/日，氯吡格雷300mg/日。",
        "cloud-27b": ("抗血小板治疗调整：鉴于已确诊主动脉壁内血肿可能，且已服用阿司匹林和氯吡格雷，需权衡出血与血栓风险，"
                      "建议暂停或谨慎使用抗血小板药物，具体方案需多学科会诊决定。"),
    }

    def test_state_and_rewrites(self):
        c = case(*self.record)
        self.assertEqual(A.aortic_state(c)[0], A.CONFIRMED_ACTIVE)
        text, events, _ = screen(self.record, self.plans["qwen3:8b"])
        self.assertEqual([e.action for e in events], [A.BLOCK])
        self.assertEqual(events[0].reason_code, "AAS_WITHOUT_INDEPENDENT_INDICATION")
        self.assertNotIn("300mg/日", text)
        self.assertIn("不建议常规继续双联抗血小板治疗", text)
        self.assertFalse(any(w in text for w in ("已停", "已会诊")))
        text, events, _ = screen(self.record, self.plans["cloud-27b"])
        self.assertEqual([e.action for e in events], [A.REVIEW])
        self.assertEqual(text, "抗血小板治疗调整：鉴于已确诊主动脉壁内血肿可能，且已服用阿司匹林和氯吡格雷，需权衡出血与血栓风险；"
                               "抗血小板治疗的必要性及安全性需由专科医师评估确定。")

    def test_cloud_definite_stop_becomes_assessment(self):
        # cloud run 2: a definite stop instruction is not authorised (spec §6 row 2); the MDT deferral stays as written
        plan = "抗血小板治疗调整：鉴于主动脉壁间血肿风险，暂停氯吡格雷和阿司匹林，避免加重出血风险，待病情稳定后由多学科讨论决定后续抗栓策略。"
        text, events, _ = screen(self.record, plan)
        self.assertEqual([e.reason_code for e in events], ["AUTOMATIC_STOP_NOT_AUTHORISED"])
        self.assertIn("评估暂停抗血小板治疗的必要性及时机", text)
        self.assertTrue(text.endswith("待病情稳定后由多学科讨论决定后续抗栓策略。"), text)
        self.assertNotIn("恢复治疗", text)

    def test_real_history_not_retensed(self):
        # cloud run 3: F3 turned "鉴于已使用抗血小板药物" (a documented loading dose) into "鉴于拟使用…"
        c = case(*self.record)
        n = Note()
        n.sections["treatment_plan"] = [Statement("鉴于已使用抗血小板药物且存在主动脉病变，需评估出血风险。", ["S1"])]
        self.assertEqual(V.retense_completed(n, build_ledger(c)), 0)
        self.assertIn("已使用抗血小板药物", n.sections["treatment_plan"][0].text)

    def test_dose_finding_is_separate(self):
        c = case(*self.record)
        codes = {f.code for f in V.check_statement("treatment_plan", 0, Statement(self.plans["qwen3:8b"], ["S1"]), c, build_ledger(c))}
        self.assertLessEqual({"aortic_antithrombotic", "loading_dose_as_maintenance"}, codes)

    def test_official_output_end_to_end(self):
        """The pipeline's official record: no executable daily DAPT, history kept, visible high-priority review item."""
        reply = {"case_features": ["突发胸痛5小时，外院予阿司匹林300mg、氯吡格雷300mg口服 [[S1]]",
                                   "急诊大血管CTA提示主动脉壁间血肿可能 [[S1]]"],
                 "diagnostic_discussion": ["主动脉壁内血肿（Stanford B型可能） [[S2]]"],
                 "treatment_plan": ["控制血压及心率 [[S1]]", self.plans["qwen3:8b"] + " [[S1]]"],
                 "evidence": [{"statement": "主动脉壁间血肿可能", "source_ids": ["S1"]}], "review_items": []}

        class Client:
            def chat(self, system, user, stats, deadline=None, thinking=None):
                return json.dumps(reply, ensure_ascii=False)

        c = Config(api_base="mock://", pipeline="A2", max_calls_per_case=2, output_protocol="official")
        res = Pipeline(c, Client()).run_case(case(*self.record))
        mr = res.record["medical_record"]
        self.assertNotIn("300mg/日", mr["plan"])
        self.assertIn("不建议常规继续双联抗血小板治疗", mr["plan"])
        self.assertIn("阿司匹林300mg", mr["case_features"])                    # the real loading dose is kept
        self.assertTrue(any("未作为可执行给药方案输出" in r for r in mr["review_items"]), mr["review_items"])
        self.assertEqual(res.log["aortic_postcheck_changes"], 0)
        self.assertTrue(all(e["rule_id"] == A.RULE_ID for e in res.log["aortic_rule_events"]))


if __name__ == "__main__":
    unittest.main()
