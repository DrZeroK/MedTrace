"""Case-triggered safety points for the generation prompt.

The fixed prompt states these rules in general form, and on the 30-case synthetic comparison the model still broke
them repeatedly; the rubric scores such a case 0 (harmful advice or a serious omission). When the records show one of
the situations below, a short instruction naming the case's own findings is added to the generation request, which the
model follows far more reliably than a general rule. Triggers are clinical features read from the records (never case
ids); the instructions state standard first-line handling, not diagnoses. Chinese records only for now.
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
    sbp = min(_num(r"血压\s*(\d{2,3})\s*/\s*\d{2,3}", text), default=999)
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
        out.append(("allergy_class", f"资料记录有{names}过敏：抗感染等用药首选与过敏药物不同类的药物；若仍考虑可能交叉过敏的药物"
                                     "（如青霉素过敏时的头孢菌素、碳青霉烯类），须单列一条写明交叉过敏评估及使用前提。"
                                     "同一条计划不得既写“避免某类药物”又推荐属于该类的药物。"))

    if (_positive("肢体无力|偏瘫|口角歪斜|言语含糊|失语|面瘫|肌力下降", case)
            and re.search(r"最后.{0,6}正常|发病.{0,6}(?:小时|时)|起病.{0,6}小时", text)
            and re.search(r"CT[^。；\n]{0,12}(?:未见|无)[^。；\n]{0,6}出血", text)):
        out.append(("stroke_reperfusion", "疑似急性缺血性卒中且头颅CT未见出血：诊疗计划须首先写再灌注评估——按距最后正常时间评估静脉溶栓"
                                          "（发病4.5小时内）及血管内取栓（大血管闭塞，可评估至24小时）的适应证与禁忌（抗凝药使用及末次服药时间、"
                                          "凝血结果、血压是否超过185/110 mmHg），尽快完成头颈血管影像；不得以“暂不予抗栓”代替再灌注评估。"))

    if (re.search(r"停经|妊娠|β-?hCG|hCG", text) and re.search(r"未见[^。；\n]{0,4}宫内孕囊|附件[^。；\n]{0,8}包块|异位妊娠", text)
            and (hr >= 100 or sbp < 90 or re.search(r"盆腔[^。；\n]{0,6}(?:游离液|积液)|腹腔内出血", text))):
        out.append(("ectopic_unstable", "疑似异位妊娠且有心率增快、低血压或腹盆腔积液：按可能破裂出血处理，诊疗计划首先写紧急妇产科评估及"
                                        "手术（腹腔镜）准备、配血、开放静脉通路和补液；血流动力学不稳定或疑破裂时不选择期待治疗或甲氨蝶呤，"
                                        "不安排CT、MRI等会延误处置的检查。"))

    if _positive("呕吐|进食|下咽|妊娠剧吐|饮酒", case) and re.search(
            r"呕吐[^。；\n]{0,8}(?:\d+|[一二两三四数])\s*周|(?:几乎|无法)?不能进食|难以下咽|妊娠剧吐|长期(?:大量)?饮酒|酗酒", text):
        out.append(("thiamine_first", "长期呕吐或进食差：静脉补液含葡萄糖前先补充维生素B1（预防韦尼克脑病），并在计划中写明。"))

    if potassium <= 3.0:
        out.append(("hypokalaemia", f"血钾{potassium:g} mmol/L：写明补钾途径、浓度/速度上限、心电监护及复查血钾的时间；"
                                    "伴呕吐腹泻时同时评估血镁。"))

    if (glucose < 3.9 or _positive("低血糖", case)) and re.search(r"胰岛素|格列|磺脲|降糖药", text):
        out.append(("hypoglycaemia_drug", "降糖药相关低血糖：计划写明暂停或减量原降糖药并持续监测血糖至少24小时（肾功能不全时药物作用延长）；"
                                          "不得改用磺脲类等促泌剂，肾功能未评估时不改用二甲双胍；查找并纠正诱因。"))

    if (_positive("发热|寒战|感染", case) and (sbp < 90 or lactate >= 4)):
        out.append(("sepsis_shock", "疑似脓毒症伴低血压或乳酸升高：诊疗计划首先写1小时内留取血培养后启动经验性抗菌治疗、"
                                    "晶体液30 ml/kg复苏、目标平均动脉压≥65 mmHg（复苏后仍低时用去甲肾上腺素）、2-4小时内复查乳酸。"))
    return out


def safety_block(points: list[tuple[str, str]]) -> str:
    if not points:
        return ""
    lines = "\n".join(f"- {text}" for _, text in points)
    return ("\n<case_safety_points>\n以下要点由程序根据本例资料触发，诊疗计划和拟诊讨论必须逐条落实（仍须忠于资料，不得编造数值）：\n"
            + lines + "\n</case_safety_points>\n")
