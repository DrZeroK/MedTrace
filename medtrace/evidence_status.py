"""Conservative Chinese checks for unsupported assertions about tests and onset."""
import re

from .textutil import fw, split_sentences

_EXAMS = re.compile(r"动脉血气(?:分析)?|血气(?:分析)?|尿培养|血培养|痰培养|胸片|超声心动图|心电图|肝功能|肾功能")
_SYMPTOMS = re.compile(r"呼吸困难|气促|气短|憋醒|端坐呼吸|头痛|胸痛|胸闷|腹痛|心悸|眩晕")
_TIME = re.compile(r"今日|今天|昨日|昨天|昨晚|今晨|本次|既往|入院前|入院后|\d{1,2}月\d{1,2}日")
_TIME_ALIASES = {"今天": "今日", "昨天": "昨日"}
_CONDITIONAL = re.compile(r"若|如果|如有|如未|一旦|倘若|假如|必要时|可能出现|警惕|需核实|待核实")
_MISSING = re.compile(r"未提供|未记录|未见(?:相关)?(?:报告|结果)|没有(?:[^，,]{0,12})?(?:结果|报告)|(?:报告|结果)(?:不详|缺失)")
_PENDING = re.compile(r"待回报|待出|尚无(?:正式)?(?:结果|报告)|尚未出具|未回报|未出结果|未出报告")
_NOT_DONE = r"(?:尚)?未(?:行|做|查|开展|进行|完成)|(?:尚|还)没(?:有)?(?:做|查)"
_DONE = r"已(?:经)?(?:行|做|完成|采样|送检)"
_REPORTED = r"(?:报告|结果|分析)(?:示|提示|显示|为|正常|异常)|(?:结果|报告)已(?:出|回报)"
_SUDDEN = r"(?:突发|突然(?:出现|发生)?|骤然(?:出现|发生)?)"
_NEGATED_SUDDEN = re.compile(r"(?:否认|并无|未出现|未见|从未|无)(?:[^，,]{0,4})" + _SUDDEN)


def _clauses(text, subject):
    for sentence in split_sentences(fw(text)):
        parts = re.split(r"[，,]", sentence)
        for i, clause in enumerate(parts):
            for match in subject.finditer(clause):
                when = _TIME.search(clause)
                time = _TIME_ALIASES.get(when[0], when[0]) if when else ""
                condition = _CONDITIONAL.search(clause) or (i > 0 and _CONDITIONAL.search(parts[i - 1]) and clause.lstrip().startswith("则"))
                yield clause, match, time, bool(condition)


def _exam_name(term):
    return "血气" if "血气" in term else term


def _exam_state(clause, match):
    # Look locally around the named exam to avoid borrowing a neighboring exam's predicate.
    prefix = clause[max(0, match.start() - 7):match.start()]
    suffix = clause[match.end():match.end() + 13]
    nearby = prefix + match[0] + suffix
    if _MISSING.search(nearby):
        return "missing"
    if _PENDING.search(nearby):
        return "pending"
    if re.search(r"(?:" + _NOT_DONE + r")\s*$", prefix) or re.match(r"(?:检查)?(?:" + _NOT_DONE + ")", suffix):
        return "not_done"
    if re.match(_REPORTED, suffix):
        return "reported"
    if re.search(r"(?:" + _DONE + r")\s*$", prefix) or re.match(_DONE, suffix):
        return "done"
    return None


def _symptom_name(term):
    return "呼吸困难" if term in ("气促", "气短", "憋醒", "端坐呼吸") else term


def _sudden(clause, match):
    return (not _NEGATED_SUDDEN.search(clause)
            and bool(re.search(_SUDDEN + r"[\s地]{0,2}$", clause[:match.start()])
                     or re.match(r"(?:为|呈)?(?:突然(?:发作)?|突发|骤起)", clause[match.end():])))


def _same_episode(left, right):
    return not left or not right or left == right


def unsupported_claims(text, facts):
    # shortcut: a fixed exam/symptom vocabulary and explicit time markers; expand only against labeled contrasts.
    for clause, match, when, condition in _clauses(text, _EXAMS):
        state = _exam_state(clause, match)
        if condition or state not in ("done", "not_done", "reported"):
            continue
        relevant = [(fact, _exam_state(src, m)) for fact in facts
                    for src, m, time, hypothetical in _clauses(fact.text, _EXAMS)
                    if not hypothetical and _exam_name(m[0]) == _exam_name(match[0]) and _same_episode(when, time)]
        unsupported = {"missing", "pending", "not_done"}
        supported = {state}
        if state == "not_done":
            unsupported = {"missing", "pending", "done", "reported"}
        elif state == "reported":
            unsupported.add("done")
        else:
            supported.add("reported")
        checked = [(fact, value) for fact, value in relevant if value in unsupported]
        if checked and not any(value in supported for _, value in relevant):
            fact = checked[0][0]
            kind = {"done": "已实施", "reported": "已有结果", "not_done": "未实施"}[state]
            yield "unsupported_test_status", f"{fact.sid}「{fact.text}」不足以支持{match[0]}{kind}，请核对检查状态。"
    for clause, match, when, condition in _clauses(text, _SYMPTOMS):
        if condition or not _sudden(clause, match):
            continue
        relevant = [(fact, _sudden(src, m)) for fact in facts
                    for src, m, time, hypothetical in _clauses(fact.text, _SYMPTOMS)
                    if not hypothetical and _symptom_name(m[0]) == _symptom_name(match[0]) and _same_episode(when, time)]
        if relevant and not any(sudden for _, sudden in relevant):
            fact = relevant[0][0]
            yield "unsupported_sudden_onset", f"{fact.sid}「{fact.text}」不足以支持{match[0]}为突发，请核对起病时间。"
