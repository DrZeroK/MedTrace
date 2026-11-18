"""Module B - clinical fact ledger.

A deterministic, source-preserving index of the admission records. Every fact keeps
its verbatim sentence and source id, so extraction mistakes stay traceable. The ledger
feeds (1) the evidence-grounded prompt, (2) the deterministic verifier, (3) the
incremental-update diff.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from . import textutil as T
from .inputs import Case

_CATS = [
    ("allergy", r"(?i)allerg|nkda|过敏"),
    ("medication", r"(?i)\bmedications?\b|\bmeds\b|\btaking\b|\bdaily\b|\bmg\b|\bprescribed\b|\bon (?:warfarin|apixaban|insulin|metformin)|用药|服用|口服|长期服"),
    ("lab", r"(?i)\b(?:wbc|hb|hgb|hemoglobin|platelets?|creatinine|troponin|lactate|glucose|sodium|potassium|"
            r"crp|inr|hba1c|bnp|d-dimer|ph|bicarbonate|ketones?|urinalysis|culture)\b|白细胞|血红蛋白|肌酐|血糖|血钾|"
            r"肌钙蛋白|化验|血常规|生化|尿常规|糖化"),
    ("imaging", r"(?i)\b(?:x-?ray|cxr|ct|mri|ultrasound|echo(?:cardiogra\w+)?|ecg|ekg)\b|胸片|超声|心电图|彩超|核磁"),
    ("exam", r"(?i)\b(?:bp|hr|rr|spo2|temp(?:erature)?|gcs|exam(?:ination)?|auscultation|palpation|tender\w*|"
             r"murmur|crackles|oedema|edema)\b|查体|体温|血压|心率|呼吸|脉搏|压痛|反跳痛|啰音|神志"),
    ("history", r"(?i)\bhistory\b|\bpmh\b|\bsmok|\balcohol\b|\bfamily\b|既往|病史|个人史|家族史|吸烟|饮酒"),
    ("complaint", r"(?i)chief complaint|presents? with|presented with|complain|主诉|因.{1,30}入院"),
]
_CATS = [(n, re.compile(p)) for n, p in _CATS]

# Core admission elements whose *absence* is clinically relevant and must be surfaced, never assumed normal.
_CORE = [
    ("allergy", r"(?i)allerg|nkda|过敏", "Drug allergy status", "药物过敏史"),
    ("medication", r"(?i)\bmedications?\b|\bmeds\b|\btaking\b|\bon [a-z]+ \d|\bmg\b|用药|服用|口服|服药", "Current medications", "当前用药情况"),
    # a vital sign counts as documented only with a value next to it ("高血压病史" is not a blood pressure reading)
    ("vitals", r"(?i)(?:\b(?:bp|blood pressure|hr|heart rate|pulse|spo2|temp(?:erature)?|t|p|r)\b|血压|心率|体温|脉搏|血氧)[^\n，,。；;]{0,10}?\d", "Vital signs", "生命体征"),
]
_LABEL_EN = re.compile(r"([A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*)?)\s*(?:[:=(]|is|was|of|at)?\s*$")
_LABEL_ZH = re.compile(r"([一-鿿A-Za-z0-9]{2,8})\s*[:：为是]?\s*$")
_LABEL_STOP = {"and", "to", "the", "then", "from", "with", "at", "of", "is", "was", "for", "on", "in", "about", "aged", "age"}


@dataclass
class Fact:
    fid: str
    sid: str
    text: str
    category: str = "other"
    polarity: str = "positive"      # positive | negative | mixed | missing | uncertain
    numerics: list = field(default_factory=list)       # [{label, value, unit, raw}]
    dates: list = field(default_factory=list)
    neg_terms: list = field(default_factory=list)
    contexts: list = field(default_factory=list)


@dataclass
class Ledger:
    context_mode: str = "legacy"
    facts: list[Fact] = field(default_factory=list)
    numbers: set = field(default_factory=set)           # every numeric value present in the sources
    units: dict = field(default_factory=dict)           # value -> {normalised units}
    dates: set = field(default_factory=set)             # date objects present in the sources
    neg_terms: dict = field(default_factory=dict)       # term -> [fid]
    neg_only: set = field(default_factory=set)          # negated and never asserted positively
    pos_text: str = ""                                  # all source text with negated spans blanked
    clear_pos_text: str = ""                            # only text that is positive beyond doubt (see textutil)
    all_text: str = ""
    tokens_all: set = field(default_factory=set)
    tokens_by_source: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)       # [{kind, detail, sources}]
    label_values: dict = field(default_factory=dict)    # measurement label -> {values recorded under that label}
    undocumented: list = field(default_factory=list)    # core elements with no mention at all
    lang: str = "en"
    knowledge_cards: dict = field(default_factory=dict)

    def by_polarity(self, p):
        return [f for f in self.facts if f.polarity == p]


def _category(sent: str) -> str:
    for name, rx in _CATS:
        if rx.search(sent):
            return name
    return "other"


def _label(prefix: str) -> str:
    m = _LABEL_ZH.search(prefix) if T.detect_lang(prefix[-12:]) == "zh" else _LABEL_EN.search(prefix)
    if not m:
        return ""
    words = [w for w in m.group(1).lower().split() if w not in _LABEL_STOP]
    return " ".join(words)[-24:]


def numerics(sent: str, year) -> list[dict]:
    masked = T.fw(T.mask_dates(sent, year))
    out = []
    for m in T._NUM_STRICT.finditer(masked):
        unit = T.norm_unit(m.group(2))
        if unit is None:
            continue  # only unit-bearing measurements enter the measurement table
        out.append({"label": _label(masked[:m.start()]), "value": float(m.group(1)), "unit": unit,
                    "raw": (masked[max(0, m.start() - 28):m.start()].split(",")[-1].split("，")[-1] + m.group(0)).strip()})
    return out


def build_ledger(case: Case, *, context_mode: str = "legacy") -> Ledger:
    if context_mode not in ("legacy", "zh_context_v1"):
        raise ValueError("unknown context mode")
    from . import context as C
    L = Ledger(lang=case.lang, context_mode=context_mode)
    year = case.cutoff.year if case.cutoff else None
    n = 0
    pos_parts, clear_parts = [], []
    for src in case.sources:
        L.tokens_by_source[src.sid] = T.tokens(src.content)
        L.numbers |= T.all_number_values(src.content)
        for val, units in T.all_number_units(src.content).items():
            L.units.setdefault(val, set()).update(units)
        for dt, _, _, _ in T.find_dates(src.content, year):
            L.dates.add(dt.date())
        for sent in T.split_sentences(src.content):
            n += 1
            f = Fact(fid=f"F{n}", sid=src.sid, text=sent, category=_category(sent))
            f.numerics = numerics(sent, year)
            f.dates = [d[0] for d in T.find_dates(sent, year)]
            enhanced = context_mode == C.VERSION and T.detect_lang(sent) == "zh"
            f.contexts = [s.as_dict() for s in C.analyze(sent)] if enhanced else []
            f.neg_terms = C.negated_terms(sent) if enhanced else T.negated_terms(sent)
            pos = C.positive_text(sent) if enhanced else T.positive_text(sent)
            pos_parts.append(pos)
            clear_parts.append(pos if enhanced else T.clearly_positive_text(sent))
            if T.has_missing_cue(sent):
                f.polarity = "missing"
            elif f.neg_terms:
                f.polarity = "mixed" if T.tokens(pos) - T.tokens(" ".join(f.neg_terms)) and len(pos.strip()) > len(sent) * 0.6 else "negative"
            elif T.has_uncertain_cue(sent):
                f.polarity = "uncertain"
            for num in f.numerics:
                L.units.setdefault(num["value"], set()).add(num["unit"])
                if len(num["label"]) >= 2:
                    L.label_values.setdefault(num["label"], set()).add(num["value"])
            for t in f.neg_terms:
                L.neg_terms.setdefault(t, []).append(f.fid)
            L.facts.append(f)
    L.all_text = case.text.lower()
    L.pos_text = "\n".join(pos_parts)
    L.clear_pos_text = "\n".join(clear_parts)
    L.tokens_all = set().union(*L.tokens_by_source.values()) if L.tokens_by_source else set()
    L.neg_only = {t for t in L.neg_terms if t not in L.pos_text}
    _find_conflicts(L)
    for key, rx, en, zh in _CORE:
        if not re.search(rx, case.text):
            L.undocumented.append({"key": key, "en": en, "zh": zh})
    return L


# A denied history is only contradicted by a statement that asserts the condition. Seen on 2,578 real case reports:
# most "contradictions" were the term inside a test name ("肝炎标志物…未见异常", "肿瘤指标…无异常", "丙型肝炎病毒抗体 0.12").
_TEST_SUFFIX = re.compile(r"^(?:病毒)?(?:标志物|抗体|抗原|指标|相关|检测|筛查|系列|全套|谱|dna|rna|病毒|史|家族史)", re.I)
_NEG_RESULT = re.compile(r"(?i)未见(?:明显)?异常|无异常|阴性|无阳性|正常|排除|除外|待排|negative|normal|unremarkable|ruled out")


_GENERIC_TERMS = {"药物", "食物", "其他", "其它", "异常", "不适", "特殊", "家族", "drug", "food", "other"}   # list fragments, not conditions


def _asserts(term: str, text: str) -> bool:
    pos = T.positive_text(text)
    i = pos.find(term)
    while i >= 0:
        after = pos[i + len(term):]
        if not _TEST_SUFFIX.match(after) and not _NEG_RESULT.search(after[:60]):
            return True
        i = pos.find(term, i + 1)
    return False


def _find_conflicts(L: Ledger) -> None:
    from . import context as C
    fact = {f.fid: f for f in L.facts}
    seen = set()
    # (1) a history the patient explicitly denies in one source but that another source asserts.
    #     Plain negative findings ("无头晕", "未扪及肿块") are deliberately excluded: on real records they are
    #     site- or time-specific and "conflict" with other mentions almost always spuriously
    #     (measured on CMB-Clin: 35 polarity flags in 74 cases, essentially all false).
    for f in L.facts:
        for term in T.denied_terms(f.text):
            if term in seen or term in _GENERIC_TERMS:
                continue
            if L.context_mode != "legacy" and not any(s["assertion"] == "negated" and s["experiencer"] == "patient"
                                                      for s in C.term_attributes(f.text, term)):
                continue
            pos = [g for g in L.facts if g.sid != f.sid and _asserts(term, g.text)
                   and (L.context_mode == "legacy" or any(s["assertion"] == "affirmed" and s["experiencer"] == "patient"
                                                        for s in C.term_attributes(g.text, term)))]
            if pos:
                seen.add(term)
                L.conflicts.append({"kind": "polarity", "term": term, "detail": f'"{f.text}" vs "{pos[0].text}"',
                                    "sources": sorted({f.sid, pos[0].sid})})
    # (2) same labelled measurement, same unit, different value, different source
    table: dict = {}
    for f in L.facts:
        for num in f.numerics:
            if len(num["label"]) >= 2:
                table.setdefault((num["label"], num["unit"]), []).append((num["value"], f))
    for (label, unit), rows in table.items():
        vals = {v for v, _ in rows}
        sids = {f.sid for _, f in rows}
        if len(vals) > 1 and len(sids) > 1:
            L.conflicts.append({"kind": "numeric", "term": label,
                                "detail": "; ".join(f'{f.sid}: "{f.text}"' for _, f in rows[:4]),
                                "sources": sorted(sids)})


def digest(L: Ledger, max_items: int = 40) -> str:
    """Compact ledger view for the evidence-grounded prompt."""
    zh = L.lang == "zh"
    h = (lambda e, z: z if zh else e)
    out = []
    if L.context_mode != "legacy":
        out.append("【中文上下文作用域：仅为规则标注；unknown需核实，不得据此补造事实】")
        for f in L.facts:
            for s in f.contexts:
                if len(out) > max_items:
                    break
                out.append(f"- ({f.sid}/{f.fid}) {s['dimension']}={s['value']}: {f.text[s['start']:s['end']]}")
    nums = [(f.sid, n["raw"]) for f in L.facts for n in f.numerics][:max_items]
    if nums:
        out.append(h("[Measurements - reproduce value AND unit exactly]", "【数值指标——数值与单位须原样引用】"))
        out += [f"- ({sid}) {raw}" for sid, raw in nums]
    negs = [(f.sid, f.text) for f in L.facts if f.neg_terms][:max_items]
    if negs:
        out.append(h("[Documented negatives - keep as negatives]", "【明确记录的阴性信息——须保持为阴性】"))
        out += [f"- ({sid}) {t}" for sid, t in negs]
    miss = [(f.sid, f.text) for f in L.by_polarity("missing")][:max_items]
    if miss or L.undocumented:
        out.append(h("[Pending / unavailable / not documented - never treat as normal]", "【待回报/未获得/未记录——不得视为正常】"))
        out += [f"- ({sid}) {t}" for sid, t in miss]
        out += [h(f"- (no source) {u['en']}: not documented anywhere in the records", f"- （无来源）{u['zh']}：记录中未提及")
                for u in L.undocumented]
    unc = [(f.sid, f.text) for f in L.by_polarity("uncertain")][:max_items]
    if unc:
        out.append(h("[Statements the records themselves mark as uncertain - keep uncertain]", "【记录本身标注为不确定的信息——须保持不确定】"))
        out += [f"- ({sid}) {t}" for sid, t in unc]
    if L.conflicts:
        out.append(h("[Candidate conflicts or serial values - decide from timing; if unresolved, list under review_items]",
                     "【可能矛盾或系列变化的信息——结合时间判断；无法判定则列入review_items】"))
        out += [f"- {c['term']}: {c['detail']}" for c in L.conflicts[:12]]
    return "\n".join(out) if out else h("(no structured items extracted)", "（未提取到结构化条目）")
