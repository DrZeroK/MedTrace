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
    # A vital sign counts only when a value follows the label directly. The old {0,10} gap let
    # "高血压病史10年" count as a blood-pressure reading; allow only punctuation/spacing/copulas.
    ("vitals", r"(?i)(?:(?<![a-z])(?:bp|blood pressure|hr|heart rate|pulse|temp(?:erature)?|t|p|rr?|resp(?:iration)?|spo[₂2])(?![a-z])|血压|心率|体温|脉搏|血氧(?:饱和度)?|呼吸(?:频率)?)\s*(?::|：|=|约?为?|是)?\s*\d", "Vital signs", "生命体征"),
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
    as_of: tuple = ()               # dates of this sentence, else of the latest dated line before it in the same source


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
    pos_text_norm: str = ""                             # whitespace-insensitive copies for term matching
    clear_pos_text_norm: str = ""
    all_text_norm: str = ""
    neg_terms_norm: set = field(default_factory=set)
    tokens_all: set = field(default_factory=set)
    tokens_by_source: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)       # [{kind, detail, sources}]
    label_values: dict = field(default_factory=dict)    # measurement label -> {values recorded under that label}
    undocumented: list = field(default_factory=list)    # core elements with no mention at all
    diagnoses: list = field(default_factory=list)       # the records' own diagnosis list items (verbatim, enumeration removed)
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
        as_of = ()
        L.diagnoses += _diagnosis_items(src.content)
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
            if f.dates:
                as_of = tuple(sorted({d.date() for d in f.dates}))
            f.as_of = as_of
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
    L.pos_text_norm = T.squash(L.pos_text)
    L.clear_pos_text_norm = T.squash(L.clear_pos_text)
    L.all_text_norm = T.squash(case.text)
    L.neg_terms_norm = {T.squash(t) for t in L.neg_terms}
    L.tokens_all = set().union(*L.tokens_by_source.values()) if L.tokens_by_source else set()
    _find_conflicts(L)
    # a term the same source also asserts (e.g. "无…体重下降" / "体重近2月下降约1.5kg") is a record conflict, surfaced as
    # such; it is not "documented only as absent", so a note that reports the positive statement is not a negation flip
    internal = {c["term"] for c in L.conflicts if c["kind"] == "internal"}
    L.neg_only = {t for t in L.neg_terms if t not in L.pos_text and t not in internal}
    for key, rx, en, zh in _CORE:
        if not re.search(rx, case.text):
            L.undocumented.append({"key": key, "en": en, "zh": zh})
    return L


# A denied history is only contradicted by a statement that asserts the condition. Seen on 2,578 real case reports:
# most "contradictions" were the term inside a test name ("肝炎标志物…未见异常", "肿瘤指标…无异常", "丙型肝炎病毒抗体 0.12").
_TEST_SUFFIX = re.compile(r"^(?:病毒)?(?:标志物|抗体|抗原|指标|相关|检测|筛查|系列|全套|谱|dna|rna|病毒|史|家族史"
                          r"|流行|疫区|接触)", re.I)    # "传染病流行地区情况", "疫区居住史", "接触史": exposure, not disease
_NEG_RESULT = re.compile(r"(?i)未见(?:明显)?异常|无异常|阴性|无阳性|正常|排除|除外|待排|negative|normal|unremarkable|ruled out")


_GENERIC_TERMS = {"药物", "食物", "其他", "其它", "异常", "不适", "特殊", "家族", "drug", "food", "other"}   # list fragments, not conditions


_DX_HEAD = re.compile(r"(?:初步|入院|门诊|临床|目前)?诊断\s*[：:]")
# A denial scoped to before pregnancy ("糖尿病（孕前）", "孕前否认糖尿病") is not contradicted by a pregnancy-period
# diagnosis ("妊娠期糖尿病"): a normal temporal distinction, not a conflict.
_PRE_PREG = re.compile(r"孕前")
_PREG_PREFIX = re.compile(r"(?:妊娠期?|孕期)$")


def _diagnosis_items(text: str) -> list[str]:
    """Items of a "初步诊断：1. …\n2. …" list (one per line, or "；"-separated on the header line)."""
    out = []
    for m in _DX_HEAD.finditer(text):
        lines = text[m.end():].split("\n")
        first = [x for x in re.split(r"[；;]\s*(?=\d{1,2}[.)、．])", lines[0]) if x.strip()]
        rest = []
        for line in lines[1:]:          # numbered items and their un-numbered sub-items, up to the next labelled line
            if not line.strip() or re.search(r"[：:]", line):
                break
            rest.append(line)
        out += [T.strip_enum(x).rstrip("；;。 ") for x in first + rest if T.strip_enum(x).strip()]
    return out


def _asserts(term: str, text: str, pre_pregnancy: bool = False) -> bool:
    pos = T.positive_text(text)
    i = pos.find(term)
    while i >= 0:
        after, before = pos[i + len(term):], pos[:i]
        if (not _TEST_SUFFIX.match(after) and not _NEG_RESULT.search(after[:60])
                and not before.endswith("非")                      # "非手术患者Padua评分" names a risk group
                and not (pre_pregnancy and _PREG_PREFIX.search(before))):
            return True
        i = pos.find(term, i + 1)
    return False


def _gapped(term: str) -> re.Pattern | None:
    """A 4+ character Chinese finding written with a short interjection: "体重下降" ~ "体重近2月下降".
    shortcut: head = first two characters, gap <= 6 non-punctuation characters; extend only on observed misses."""
    if len(term) < 4 or not all("\u4e00" <= ch <= "\u9fff" for ch in term):
        return None
    return re.compile(re.escape(term[:2]) + r"[^，,；;。！？、\s]{0,6}?" + re.escape(term[2:]))


def _patient_span(text: str, start: int, end: int, mode: str) -> bool:
    """True if text[start:end] is about the patient. Experiencer scopes ("家族史：", "父亲…") apply in every mode;
    zh_context_v1 additionally requires the mention to be affirmed (not uncertain or missing)."""
    from . import context as C
    state = C.attributes(text, start, end)
    return state["experiencer"] == "patient" and (mode == "legacy" or state["assertion"] == "affirmed")


def _patient_mention(text: str, term: str) -> bool:
    """True if a negated term is said of the patient; a relative's absent finding is not the patient's."""
    from . import context as C
    states = C.term_attributes(text, term)
    return not states or any(s["experiencer"] == "patient" for s in states)


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
            pre = bool(_PRE_PREG.search(f.text))
            # a relative's condition ("家族史：母亲有2型糖尿病") does not contradict the patient's denial, in any mode
            pos = [g for g in L.facts if g.sid != f.sid and _asserts(term, g.text, pre)
                   and _patient_mention(g.text, term)
                   and (L.context_mode == "legacy" or any(s["assertion"] == "affirmed" and s["experiencer"] == "patient"
                                                        for s in C.term_attributes(g.text, term)))]
            if pos:
                seen.add(term)
                L.conflicts.append({"kind": "polarity", "term": term, "detail": f'"{f.text}" vs "{pos[0].text}"',
                                    "sources": sorted({f.sid, pos[0].sid})})
    # (2) a finding one source records as absent and, in another sentence of the SAME source, as present
    #     ("无…体重下降" then "体重近2月下降约1.5kg"). Only 4+ character findings: 2-character symptoms recur
    #     in site- or time-specific negatives and produce noise.
    for f in L.facts:
        for term in f.neg_terms:
            rx = _gapped(term)
            if term in seen or not rx or term in _GENERIC_TERMS:
                continue
            if not _patient_mention(f.text, term):
                continue
            g = next((g for g in L.facts if g.sid == f.sid and g is not f
                      and any(_patient_span(g.text, m.start(), m.end(), L.context_mode)
                              for m in rx.finditer(T.positive_text(g.text)))), None)
            if g:
                seen.add(term)
                L.conflicts.append({"kind": "internal", "term": term, "detail": f'"{f.text}" vs "{g.text}"',
                                    "sources": [f.sid], "values": []})
    # (3) same labelled measurement, same unit, different value, different source, at the same or an unknown time.
    #     Values at distinct documented times are a trend (ALT 86 -> 65 U/L), not a conflict; an undated value equal
    #     to a dated one is the same result restated (HPI quoting the outside lab).
    table: dict = {}
    for f in L.facts:
        for num in f.numerics:
            if len(num["label"]) >= 2:
                table.setdefault((num["label"], num["unit"]), []).append((num["value"], f))
    for (label, unit), rows in table.items():
        dated = {v for v, f in rows if f.as_of}
        rows = [(v, f) for v, f in rows if f.as_of or v not in dated]
        clash = [(a, b) for i, a in enumerate(rows) for b in rows[i + 1:]
                 if a[0] != b[0] and (not a[1].as_of or not b[1].as_of or a[1].as_of == b[1].as_of)]
        sids = {f.sid for pair in clash for _, f in pair}
        if len(sids) > 1:
            involved = [r for pair in clash for r in pair]
            L.conflicts.append({"kind": "numeric", "term": label, "unit": unit,
                                "values": sorted({v for v, _ in involved}),
                                "detail": "; ".join(dict.fromkeys(f'{f.sid}: "{f.text}"' for _, f in involved[:4])),
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
