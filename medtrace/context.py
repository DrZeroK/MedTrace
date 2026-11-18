"""Development-only Chinese ConText-style scopes; offsets refer to unchanged fact text.

Algorithm reference: Harkema et al., ConText (2009), doi:10.1016/j.jbi.2009.05.002.
Rules are self-authored; no pretrained model, spaCy resources or clinical ontology is loaded.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from . import textutil as T

VERSION = "zh_context_v1"
_BOUNDARY = re.compile(r"[，,。；;！？!?\n]|但是|然而|但|不过|本人|患者目前|现患者")
_LEFT = re.compile(r"[，,。；;！？!?\n：:]|但是|然而|但|不过")
_UNCERTAIN = re.compile(r"尚?(?:不能|无法|未能|未|难以)排除|为排除|(?:尚)?不能除外|不除外|待排(?:除)?|疑似|可疑|可能|考虑|倾向")
_MISSING = re.compile(r"未(?:见|提供|记录|记载|提及|获得)[^，,。；;！？!?\n]{0,20}?(?:记录|资料|信息|结果|报告)|未提供|未记录|未记载|未提及|未查|未做|待回报|待查|待完善|结果未回|未回报|不详|未知")
_FAMILY = re.compile(r"家族史|父亲|母亲|父母|祖父|祖母|外祖父|外祖母|兄弟|姐妹|哥哥|姐姐")
_PATIENT = re.compile(r"本人|患者|病人")
_HISTORY = re.compile(r"既往|曾经|曾患|既往史|病史\s*[:：]")
_CURRENT = re.compile(r"目前|当前|现有|现患|本次|入院时")
_HYPOTHETICAL = re.compile(r"若|如果|如出现|如有|一旦|为排除")
_PSEUDO = re.compile(r"不能否认|并非没有|并非无|不是没有|不是无|不能说没有")
_EXCLUSION = re.compile(r"(?:已|明确)排除|(?<!为)排除")
_POST_UNCERTAIN = re.compile(r"待排(?:除)?|不除外|尚未明确|不能除外|可能|[?？]")
_POST_MISSING = re.compile(r"不详|未知|未提供|未记录|未查|未做|待回报|未回报|结果未回")


@dataclass(frozen=True)
class ContextSpan:
    start: int
    end: int
    dimension: str
    value: str
    rule_id: str
    cue_start: int
    cue_end: int

    def as_dict(self):
        return asdict(self)


def _end(text: str, pos: int) -> int:
    boundary = _BOUNDARY.search(text, pos)
    return boundary.start() if boundary else len(text)


def _start(text: str, pos: int) -> int:
    return max((m.end() for m in _LEFT.finditer(text, 0, pos)), default=0)


def analyze(text: str) -> list[ContextSpan]:
    """Annotate modifier scopes, retaining overlaps so ambiguous cues stay auditable."""
    spans = []
    def add(start, end, dimension, value, rule, cue_start, cue_end):
        if end > start:
            spans.append(ContextSpan(start, end, dimension, value, rule, cue_start, cue_end))
    for start, end in T.neg_spans(text):
        add(start, end, "assertion", "negated", "legacy_negation", start, start)
    if T.detect_lang(text) != "zh":
        return spans
    for rx, dimension, value, rule in (
        (_UNCERTAIN, "assertion", "uncertain", "uncertainty"),
        (_MISSING, "assertion", "missing", "not_documented"),
        (_FAMILY, "experiencer", "family", "family_member"),
        (_PATIENT, "experiencer", "patient", "patient"),
        (_HISTORY, "temporality", "historical", "history"),
        (_CURRENT, "temporality", "current", "current"),
        (_HYPOTHETICAL, "temporality", "hypothetical", "condition"),
        (_PSEUDO, "assertion", "unknown", "double_negation"),
        (_EXCLUSION, "assertion", "negated", "excluded"),
    ):
        for m in rx.finditer(text):
            end = _end(text, m.end())
            # A later cue in the same dimension starts a new scope ("既往…目前…", "父亲…本人…").
            if dimension == "experiencer":
                stops = [x.start() for r in (_FAMILY, _PATIENT) for x in r.finditer(text, m.end(), end)]
                end = min(stops, default=end)
            if dimension == "temporality":
                stops = [x.start() for r in (_HISTORY, _CURRENT, _HYPOTHETICAL) for x in r.finditer(text, m.end(), end)]
                end = min(stops, default=end)
            add(m.start(), end, dimension, value, rule, m.start(), m.end())
    for rx, value, rule in ((_POST_UNCERTAIN, "uncertain", "post_uncertainty"),
                            (_POST_MISSING, "missing", "post_missing")):
        for m in rx.finditer(text):
            add(_start(text, m.start()), m.end(), "assertion", value, rule, m.start(), m.end())
    # Family/history section headings apply across commas, but never across a source or paragraph.
    for m in re.finditer(r"(家族史|既往史)\s*[:：]", text):
        stop = re.search(r"[。；;\n]|本人|患者目前|目前", text[m.end():])
        end = m.end() + stop.start() if stop else len(text)
        dim, val = ("experiencer", "family") if m.group(1) == "家族史" else ("temporality", "historical")
        add(m.start(), end, dim, val, "section_heading", m.start(), m.end())
    return sorted(set(spans), key=lambda s: (s.start, s.end, s.dimension, s.rule_id))


def attributes(text: str, start: int, end: int, spans=None) -> dict[str, str]:
    if not 0 <= start < end <= len(text):
        raise ValueError("context target must be a non-empty span within the text")
    scopes = analyze(text) if spans is None else spans
    result = {"assertion": "affirmed", "temporality": "unknown", "experiencer": "patient"}
    for dimension in result:
        matches = [s for s in scopes if s.dimension == dimension and s.start <= start and s.end >= end]
        if not matches:
            continue
        if dimension == "assertion":
            # Missing information and double-negation scopes must never become ordinary negatives.
            priority = {"unknown": 4, "missing": 3, "uncertain": 2, "negated": 1}
            level = max(priority[s.value] for s in matches)
            values = {s.value for s in matches if priority[s.value] == level}
        else:
            nearest = max(s.cue_start for s in matches)
            values = {s.value for s in matches if s.cue_start == nearest}
        result[dimension] = next(iter(values)) if len(values) == 1 else "unknown"
    return result


def term_attributes(text: str, term: str) -> list[dict]:
    if not term:
        return []
    scopes = analyze(text)
    return [dict(start=m.start(), end=m.end(), **attributes(text, m.start(), m.end(), scopes))
            for m in re.finditer(re.escape(term), text, re.I)]


def positive_text(text: str) -> str:
    if T.detect_lang(text) != "zh":
        return T.positive_text(text)
    scopes = analyze(text)
    chars = list(text)
    for i in range(len(text)):
        state = attributes(text, i, i + 1, scopes)
        if state["assertion"] != "affirmed" or state["experiencer"] == "family":
            chars[i] = " "
    return "".join(chars).lower()


def negated_terms(text: str) -> list[str]:
    if T.detect_lang(text) != "zh":
        return T.negated_terms(text)
    out = []
    for s in analyze(text):
        if s.dimension != "assertion" or s.value != "negated":
            continue
        for raw in T._TERM_SPLIT.split(text[s.start:s.end]):
            term = T._clean_term(raw)
            if 2 <= len(term) <= 12 and any(x["assertion"] == "negated" for x in term_attributes(text, term)):
                if term not in out:
                    out.append(term)
    return out


def context_conflicts(statement: str, facts) -> list[tuple[str, str]]:
    """Exact shared phrases are anchors, not inferred entities; findings remain review prompts."""
    from difflib import SequenceMatcher
    generic = {"患者", "病人", "记录", "资料", "病史", "检查", "目前", "明确", "相关", "提示", "未见", "考虑", "否认"}
    anchors = set()
    for f in facts:
        for block in SequenceMatcher(None, f.text, statement, autojunk=False).get_matching_blocks():
            term = statement[block.b:block.b + block.size].strip("，,。；;：: ")
            if len(term) >= 2 and term not in generic and re.fullmatch(r"[一-鿿A-Za-z]+", term):
                anchors.add(term)
    conflicts = set()
    for term in anchors:
        source_states = [s for f in facts for s in term_attributes(f.text, term)]
        for target in term_attributes(statement, term):
            if target["assertion"] != "affirmed":
                continue
            if source_states and all(s["assertion"] in ("uncertain", "missing", "unknown") for s in source_states):
                conflicts.add(("context_assertion", term))
            if target["experiencer"] == "patient" and source_states and all(s["experiencer"] == "family" for s in source_states):
                conflicts.add(("context_experiencer", term))
            if target["temporality"] == "current" and source_states and all(s["temporality"] == "historical" for s in source_states):
                conflicts.add(("context_temporality", term))
    return sorted(conflicts)
