"""Case-triggered safety points for the generation prompt.

The fixed prompt states these rules in general form, and on the 30-case synthetic comparison the model still broke
them repeatedly; the rubric scores such a case 0 (harmful advice or a serious omission). When the records show one of
the situations below, a short instruction naming the case's own findings is added to the generation request, which the
model follows far more reliably than a general rule. Triggers are clinical features read from the records (never case
ids); the instructions state standard first-line handling, not diagnoses. Chinese records only for now.

Every threshold and instruction is checked against its source in docs/SAFETY_POINTS_SOURCES.zh-CN.md; trigger cut-offs
that are screening heuristics rather than guideline values are marked there. Update both together.
"""
from __future__ import annotations

import re

from . import textutil as T
from .inputs import Case
from .verify import recorded_allergies


def _num(rx: str, text: str) -> list[float]:
    return [float(x) for x in re.findall(rx, text)]


def _positive(terms: str, case: Case) -> bool:
    """Any of the `|`-separated terms stated as present (outside a negation) in some sentence of the records."""
    for s in case.sources:
        for sent in T.split_sentences(s.content):
            if any(t in sent and T.term_positive_in(t, sent) for t in terms.split("|")):
                return True
    return False


def safety_points(case: Case) -> list[tuple[str, str]]:
    """(rule id, instruction) for each situation the records show."""
    text = "\n".join(s.content for s in case.sources)
    hr = max(_num(r"心率\s*(\d{2,3})\s*次", text), default=0)
    sbp = min(_num(r"(?:血压|BP)\s*[:：]?\s*(\d{2,3})\s*/\s*\d{2,3}", text), default=999)
    lactate = max(_num(r"乳酸\s*(\d+(?:\.\d+)?)\s*mmol", text), default=0)
    potassium = min(_num(r"(?<![a-zA-Z])(?:血钾|钾)\s*(\d(?:\.\d+)?)\s*mmol", text), default=9)
    glucose = min(_num(r"血糖\s*(\d+(?:\.\d+)?)\s*mmol", text), default=99)
    out = []

    allergies = recorded_allergies(case)
    # records also describe allergies without the word 过敏 ("青霉素曾致皮疹")
    for m in re.finditer(r"(青霉素|阿莫西林|头孢[^\s，,。；]{0,4}|磺胺|[^\s，,。；]{1,4}霉素|[^\s，,。；]{1,4}沙星)"
                         r"[^。；\n]{0,6}(?:致|引起|后出现)[^。；\n]{0,4}(?:皮疹|荨麻疹|过敏|休克|喉头水肿|呼吸困难)", text):
        allergies.setdefault(m.group(1), m.group(1))
    if allergies:
        names = "、".join(dict.fromkeys(allergies.values()))
        out.append(("allergy_class", f"资料记录有{names}过敏：不得选用该药及同类药物；按过敏反应类型选择替代药——严重或速发型反应"
                                     "（过敏性休克、喉头水肿、严重皮肤反应）首选不同类药物，非严重反应（如单纯皮疹）可考虑结构不同的头孢菌素，"
                                     "须单列一条写明反应类型、交叉过敏评估及使用前提。同一条计划不得既写“避免某类药物”又推荐属于该类的药物。"))

    if (_positive("肢体无力|偏瘫|口角歪斜|言语含糊|失语|面瘫|肌力下降", case)
            and re.search(r"最后.{0,6}正常|发病.{0,6}(?:小时|时)|起病.{0,6}小时", text)
            and re.search(r"CT[^。；\n]{0,12}(?:未见|无)[^。；\n]{0,6}出血", text)):
        out.append(("stroke_reperfusion", "疑似急性缺血性卒中且头颅CT未见出血：诊疗计划须首先写再灌注评估——按距最后正常时间评估静脉溶栓"
                                          "（阿替普酶或替奈普酶，发病4.5小时内；超过4.5小时或醒后卒中须经高级影像评估可挽救脑组织）及血管内取栓"
                                          "（大血管闭塞：6小时内；6-24小时须经影像筛选；基底动脉闭塞可评估至24小时）"
                                          "的适应证与禁忌（抗凝药使用及末次服药时间、凝血结果；溶栓前血压须降至185/110 mmHg以下），"
                                          "尽快完成头颈血管影像；不得以“暂不予抗栓”代替再灌注评估。"))

    if (re.search(r"停经|妊娠|β-?hCG|hCG", text) and re.search(r"未见[^。；\n]{0,4}宫内孕囊|附件[^。；\n]{0,8}包块|异位妊娠", text)
            and (hr >= 100 or sbp < 90 or re.search(r"盆腔[^。；\n]{0,6}(?:游离液|积液)|腹腔内出血", text))):
        out.append(("ectopic_unstable", "疑似异位妊娠且有心率增快、低血压或腹盆腔积液：按可能破裂出血处理，诊疗计划首先写紧急妇产科评估及"
                                        "手术（腹腔镜）准备、配血、开放静脉通路和补液；血流动力学不稳定或疑破裂时不选择期待治疗或甲氨蝶呤，"
                                        "不安排CT、MRI等会延误处置的检查。"))

    if _positive("呕吐|进食|下咽|妊娠剧吐|饮酒", case) and re.search(
            r"呕吐[^。；\n]{0,8}(?:\d+|[一二两三四数])\s*周|(?:几乎|无法)?不能进食|难以下咽|妊娠剧吐|长期(?:大量)?饮酒|酗酒", text):
        out.append(("thiamine_first", "长期呕吐或进食差：静脉补液含葡萄糖前先补充维生素B1（预防韦尼克脑病），并在计划中写明；"
                                      "如需紧急纠正低血糖，葡萄糖与维生素B1同时给予，不因等待维生素B1延误葡萄糖。"))

    if potassium <= 3.0:
        out.append(("hypokalaemia", f"血钾{potassium:g} mmol/L：写明补钾途径（能口服者首选口服，严重者静脉）、静脉液体含钾浓度上限（外周一般不超过40 mmol/L）、"
                                    "按所在医院规程控制补钾速度（快速补钾须心电监护）、见尿补钾及复查血钾的时间；同时检测并纠正血镁。"))

    if (glucose < 3.9 or _positive("低血糖", case)) and re.search(r"胰岛素|格列|磺脲|降糖药", text):
        out.append(("hypoglycaemia_drug", "降糖药相关低血糖：计划写明暂停或减量原降糖药并持续监测血糖（磺脲类或肾功能不全时药物作用延长，监测须相应延长）；"
                                          "不得改用磺脲类等促泌剂，肾功能未评估时不改用二甲双胍；查找并纠正诱因。"))

    if (_positive("发热|寒战|感染", case) and (sbp < 90 or lactate >= 4)):
        out.append(("sepsis_shock", "疑似脓毒症伴低血压或乳酸升高：诊疗计划首先写1小时内留取血培养后启动经验性抗菌治疗、"
                                    "3小时内晶体液约30 ml/kg复苏（心肾功能不全者评估容量反应性后调整）、目标平均动脉压≥65 mmHg"
                                    "（复苏中或复苏后仍低时首选去甲肾上腺素）、初始乳酸>2 mmol/L时复查乳酸。"))
    severity = pneumonia_severity(case)
    if severity:
        out.append(("pneumonia_severity", severity))
    return out


# Pneumonia severity is computed here, not by the model: on the practice case the model left "严重程度待评估" although
# the records allowed grading. Criteria: CURB-65 (Lim et al., Thorax 2003) and the IDSA/ATS 2019 severe-CAP criteria as
# given in 内科学第10版 p48 (1 major or >=3 minor). Unrecorded items are reported as unknown, never assumed normal.
_PNEUMONIA = re.compile(r"肺炎|肺部感染|下呼吸道感染|(?:斑片|浸润|实变)影")
_CONFUSION = "意识障碍|意识模糊|意识错乱|神志恍惚|定向障碍|谵妄|嗜睡|反应迟钝|反应迟缓"


def pneumonia_severity(case: Case) -> str | None:
    text = "\n".join(s.content for s in case.sources)
    if not _PNEUMONIA.search(text):
        return None
    first = lambda rx: (_num(rx, text) or [None])[0]
    age = first(r"(\d{1,3})\s*岁")
    rr = first(r"(?:呼吸(?:频率)?|(?<![A-Za-z])R)\s*[:：]?\s*(\d{1,2})\s*次")
    bp = re.search(r"(?:血压|BP)\s*[:：]?\s*(\d{2,3})\s*/\s*(\d{2,3})", text)
    sbp, dbp = (int(bp.group(1)), int(bp.group(2))) if bp else (None, None)
    urea = first(r"(?:血尿素氮|尿素氮|BUN|血尿素|尿素)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*mmol")
    pao2 = re.search(r"PaO[2₂]\s*[:：]?\s*(\d{2,3})\s*mmHg", text)
    room_air = bool(pao2) and bool(re.search(r"未吸氧|室内空气|不吸氧", text[max(0, pao2.start() - 60):pao2.end() + 10]))
    wbc = first(r"(?:白细胞(?:总数|计数)?|WBC)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*[×x]")
    plt = first(r"(?:血小板(?:计数)?|PLT)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*[×x]")
    temp = first(r"(?:体温|(?<![A-Za-z])T)\s*[:：]?\s*(\d{2}(?:\.\d)?)\s*[℃°]")
    # documented clear consciousness counts as "no"; silence on mental status is unknown, not normal
    confusion = True if _positive(_CONFUSION, case) else False if re.search(r"神志清|意识清|神清", text) else None

    def item(name, value, met):
        return (name, None if value is None else bool(met))

    curb = [item("意识障碍", confusion, confusion),
            item("尿素>7 mmol/L", urea, urea is not None and urea > 7),
            item("呼吸频率≥30次/分", rr, rr is not None and rr >= 30),
            item("收缩压<90或舒张压≤60 mmHg", sbp, sbp is not None and (sbp < 90 or dbp <= 60)),
            item("年龄≥65岁", age, age is not None and age >= 65)]
    minor = [item("呼吸频率≥30次/分", rr, rr is not None and rr >= 30),
             item("PaO2/FiO2≤250", pao2 if room_air else None, room_air and int(pao2.group(1)) / 0.21 <= 250),
             item("多肺叶浸润", True if re.search(r"多(?:个)?肺叶|多叶|双肺[^。；\n]{0,8}(?:浸润|实变|斑片)", text) else None, True),
             item("意识障碍和/或定向障碍", confusion, confusion),
             item("血尿素氮≥7.14 mmol/L", urea, urea is not None and urea >= 7.14),
             item("白细胞<4×10⁹/L", wbc, wbc is not None and wbc < 4),
             item("血小板<100×10⁹/L", plt, plt is not None and plt < 100),
             item("体温<36℃", temp, temp is not None and temp < 36),
             item("低血压需积极液体复苏", sbp, sbp is not None and sbp < 90)]
    major = _positive("机械通气|气管插管|血管活性药|去甲肾上腺素|升压药", case)
    fmt = lambda items: "；".join(f"{n}{'（是）' if v else '（否）' if v is False else '（资料未提供）'}" for n, v in items)
    score = sum(v is True for _, v in curb)
    unknown_curb = sum(v is None for _, v in curb)
    met = sum(v is True for _, v in minor)
    unknown = sum(v is None for _, v in minor)
    if major or met >= 3:
        verdict = "符合重症肺炎标准"
    elif met + unknown < 3:
        verdict = f"不符合重症肺炎标准（已满足{met}项次要标准，即使未提供项均满足也不足3项）"
    else:
        verdict = f"目前满足{met}项次要标准、{unknown}项资料未提供，尚不能完成重症判定，须写明缺哪些项目"
    return (f"肺炎严重程度（程序按资料计算，供拟诊讨论直接引用，不得改动数值）：CURB-65 = {score}分"
            f"{f'（另有{unknown_curb}项资料未提供）' if unknown_curb else ''}，各项：{fmt(curb)}。"
            f"重症肺炎主要标准{'有' if major else '无'}；次要标准：{fmt(minor)}。结论：{verdict}。"
            "拟诊讨论须写出上述分级及依据，不得笼统写“严重程度待评估”；诊疗计划据此写明单一收治场所"
            "（CURB-65 0-1分可考虑门诊、2分住院、3-5分或符合重症标准考虑ICU）及升级条件，不得写“A或B”。")


def safety_block(points: list[tuple[str, str]]) -> str:
    if not points:
        return ""
    lines = "\n".join(f"- {text}" for _, text in points)
    return ("\n<case_safety_points>\n以下要点由程序根据本例资料触发，诊疗计划和拟诊讨论必须逐条落实（仍须忠于资料，不得编造数值）：\n"
            + lines + "\n</case_safety_points>\n")
