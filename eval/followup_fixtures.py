"""Predeclared synthetic inputs and narrow source assertions for the capped study."""
import copy
import re

NORMAL = ("SYN001", "SYN012", "SYN023", "SYN045", "SYN056", "SYN089")
PRESSURE = ("QUOTE01", "QUOTE02", "LONG01", "LONG02", "DOSE01", "DOSE02")
CONTEXT = ("STATE01", "ONSET01", "NEG01")
RAG = ("SYN001", "SYN012", "SYN045", "SYN100")
CHECKS = [
    ("SYN001", "S01", "应保留无胸痛", r"(?:无|否认|不伴)(?:明显)?胸痛", r"伴有胸痛|出现胸痛"),
    ("SYN012", "S01", "应保留近期夜间憋醒", r"憋醒|夜间阵发性呼吸困难", r"(?:突发|突然出现)呼吸困难"),
    ("SYN023", "S03", "应保留超声所示8 mm", r"8\s*mm", r"(?<!\d)18\s*mm"),
    ("SYN045", "S03", "尿培养应保留待回报", r"尿培养[^。；\n]{0,14}(?:待回报|待报告|尚未|未回报|结果未出)", r"尿培养(?:提示|证实|为阳性|为阴性)"),
    ("SYN056", "S03", "应保留血红蛋白79 g/L", r"79\s*g/L", r"血红蛋白\s*97\s*g/L"),
    ("SYN089", "S01", "药名应保留待核状态", r"(?:药名|药品名称|具体药物|具体抗癫痫药)[^。；\n]{0,16}(?:核实|不详|不明|未明|未明确|未知)", r"服用卡马西平后|服用拉莫三嗪后"),
    ("QUOTE01", "S03", "应保留NT-proBNP 4680 pg/mL", r"4680\s*pg/mL", r"NT-proBNP\s*4860\s*pg/mL"),
    ("QUOTE02", "S03", "应保留CRP 65 mg/L", r"65\s*mg/L", r"CRP\s*56\s*mg/L"),
    ("LONG01", "S03", "应保留白蛋白25 g/L", r"25\s*g/L", r"白蛋白\s*52\s*g/L"),
    ("LONG02", "S03", "应保留磷0.62 mmol/L", r"0\.62\s*mmol/L", r"磷\s*0\.26\s*mmol/L"),
    ("DOSE01", "PX", "允许省略未核实剂量，若提及须保留不确定性", "", r"10\s*mg"),
    ("DOSE02", "PX", "允许省略未核实剂量，若提及须保留不确定性", "", r"20\s*mg"),
    ("STATE01", "S02", "尿培养已采样，结果待回报", r"尿培养[^。；\n]{0,20}(?:待回报|尚无结果|结果未出|结果未回报)", r"未(?:行|做|查)尿培养|尿培养[^。；\n]{0,6}(?:为阳性|为阴性|结果正常)"),
    ("ONSET01", "S01", "起病迁延且近期加重", r"胸闷[^。；\n]{0,12}(?:半|六|6)个?月|半年[^。；\n]{0,12}胸闷", r"(?:突发|突然出现)胸闷"),
    ("NEG01", "S01", "明确否认胸痛，咯血另有肯定谓词", r"(?:无|否认|不伴)胸痛", r"(?:无|否认)(?:胸痛[、及和，,])?咯血"),
    ("NEG01", "S02", "应保留少量咯血并引用观察来源", r"(?:观察到|有|见到|出现|诉|一过性|少量)咯血", r"(?:无|否认)(?:胸痛[、及和，,])?咯血"),
]


def _case(case_id, *texts):
    return {"case_id": case_id, "record_cutoff": "T0",
            "sources": [{"source_id": f"S{i:02d}", "content": t} for i, t in enumerate(texts, 1)]}


def cases_from(reviewed):
    assert [c["case_id"] for c in reviewed] == [f"SYN{i:03d}" for i in range(1, 101)]
    by_id = {c["case_id"]: c for c in reviewed}
    cases = {k: by_id[k] for k in (*NORMAL, "SYN100")}

    def extend(case_id, original, additions, first=False):
        c = copy.deepcopy(by_id[original])
        c["case_id"] = case_id
        c["sources"] = additions + c["sources"] if first else c["sources"] + additions
        cases[case_id] = c

    extend("QUOTE01", "SYN012", [{"source_id": "PX", "content": '家属说曾被告知“心功能不好"，原报告未提供。'}])
    extend("QUOTE02", "SYN007", [{"source_id": "PX", "content": '转诊文字含“检测路径 C:\\转诊\\结果，标记 "R2"”；检验仍待回报。'}])
    for case_id, original in (("LONG01", "SYN034"), ("LONG02", "SYN100")):
        historical = [{"source_id": f"H{i:02d}", "content":
                       (f"历史资料转录第{i}页。以下是转诊交接的目录与附件状态。"
                        "外院纸质检查附件尚未扫描，目录仅用于后续联系核对。"
                        "交接内容涉及登记、接收和回执，具体检查结果须以独立报告为准。"
                        "此页没有新增患者体征、数值、诊断、用药或处置记录。") }
                      for i in range(1, 65)]
        extend(case_id, original, historical, first=True)
    extend("DOSE01", "SYN018", [{"source_id": "PX", "content": '家属猜测原药“约10 mg”，药名及剂量均未核实。'}])
    extend("DOSE02", "SYN089", [{"source_id": "PX", "content": '纸条上有“20 mg”，与本次药物是否对应不详，实际剂量未核实。'}])
    cases["STATE01"] = _case("STATE01", "女性，46岁，尿痛及右腰痛2天。",
                             "尿培养已采样，结果待回报；本次尿常规报告未提供。", "前天血培养未采样。")
    cases["ONSET01"] = _case("ONSET01", "男性，63岁，胸闷反复半年，近3天活动后加重。",
                             "昨晚突然出现头痛约10分钟，已自行缓解。", "今日心电图完成，报告待回报。")
    cases["NEG01"] = _case("NEG01", "男性，52岁，自述否认胸痛，咯血。",
                           "护士今晨观察到少量咯血。", "入院鼻部未见活动性出血，药物使用资料不详。",
                           "血常规报告尚未提供。")
    return cases


def check_anchors(case_id, sections):
    rows = []
    for key, source, goal, desired, unsupported in CHECKS:
        if key != case_id:
            continue
        matches = []
        for section, statements in sections.items():
            for st in statements:
                allowed = bool(re.search(desired, st["text"], re.I)) if desired else False
                risky = bool(re.search(unsupported, st["text"], re.I))
                if allowed or risky:
                    matches.append({"section": section, **st, "desired_match": allowed, "potential_error": risky})
        rows.append({"source": source, "goal": goal, "desired_match": any(m["desired_match"] for m in matches)
                     if desired else None,
                     "source_match": any(m["desired_match"] and source in m["source_ids"] for m in matches)
                     if desired else None, "matches": matches})
    return rows
