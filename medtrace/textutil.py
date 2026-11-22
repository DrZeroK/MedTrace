"""Deterministic text primitives shared by the fact ledger and the verifier.

Everything here is pure Python and language-aware for English and Chinese.
These are heuristics: they are used to *flag* statements, never to rewrite them.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_CJK = re.compile(r"[一-鿿]")


def detect_lang(text: str) -> str:
    if not text:
        return "en"
    return "zh" if len(_CJK.findall(text)) / max(1, len(text)) > 0.15 else "en"


# Full-width forms common in Chinese records (％ ／ ． ０-９ Ａ-Ｚ) are mapped 1:1 to ASCII for *matching only*;
# the mapping preserves length, so offsets into the original text stay valid and the text itself is never altered.
_FW = {0xFF05: "%", 0xFF0F: "/", 0xFF0E: ".", 0xFF0B: "+", 0xFF0D: "-", 0xFF1C: "<", 0xFF1E: ">", 0x3000: " "}
_FW.update({0xFF10 + i: str(i) for i in range(10)})
_FW.update({0xFF21 + i: chr(65 + i) for i in range(26)})
_FW.update({0xFF41 + i: chr(97 + i) for i in range(26)})


def fw(text: str) -> str:
    return (text or "").translate(_FW)


_WS = re.compile(r"[\s、，,；;。！？!?：:·•]+")


def squash(text: str) -> str:
    """Lower-case and remove whitespace and list/clause punctuation for literal term comparisons
    ("ST 段" == "ST段"; "恶心呕吐" matches "恶心、呕吐")."""
    return _WS.sub("", fw(text or "").lower())


# Abbreviations seen in generated notes for terms the records spell out. Explicit pairs only: a fuzzy match could
# hide a genuine contradiction. Extend only with pairs observed on real output.
_SYNONYMS = [("支扩", "支气管扩张"), ("rf", "类风湿因子"), ("aso", "抗链球菌溶血素o"), ("家族中", "家族"),
             ("吸烟", "嗜烟"), ("饮酒", "嗜酒")]


def term_variants(term_norm: str) -> set[str]:
    """`term_norm` (squashed) plus its spelling variants under the explicit abbreviation map."""
    out = {term_norm}
    for a, b in _SYNONYMS:
        for t in list(out):
            if a in t:
                out.add(t.replace(a, b))
            if b in t:
                out.add(t.replace(b, a))
    return out


def concat_of(term_norm: str, parts: set[str]) -> bool:
    """True if `term_norm` is a concatenation of two or more `parts` ("吸烟饮酒" = "吸烟" + "饮酒")."""
    ok = [False] * (len(term_norm) + 1)
    ok[0] = True
    for i in range(1, len(term_norm) + 1):
        ok[i] = any(ok[j] and term_norm[j:i] in parts and term_norm[j:i] != term_norm for j in range(i))
    return ok[-1] and term_norm not in parts


# ---------------------------------------------------------------- sentences
_SPLIT = re.compile(r"(?<=[。！？!?；;])|\n+|(?<=\.)\s+(?=[A-Z0-9\[(])")
_ENUM = re.compile(r"^\s*(?:\(?\d{1,2}[.)、．]\s*(?!\d)|[-*•]\s+)")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(text or "") if s and s.strip()]


def strip_enum(text: str) -> str:
    return _ENUM.sub("", text or "").strip()


# -------------------------------------------------------------------- dates
_MON = "jan feb mar apr may jun jul aug sep oct nov dec".split()
_MON_RE = "(" + "|".join(_MON) + ")"
_HM = r"(?:\s*T?\s*(\d{1,2})\s*[:：时]\s*(\d{2})(?::\d{2})?)?"
_ISO = re.compile(r"(?<!\d)(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?!\d)\s*日?" + _HM)   # (?!\d): "2023.9-2023.12" is a range, not a date
_MD_ZH = re.compile(r"(?<![\d年])(\d{1,2})月(\d{1,2})日" + _HM)
_EN1 = re.compile(r"\b" + _MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
                  r"(?:[,\s]+(?:at\s+)?(\d{1,2}):(\d{2}))?", re.I)
_EN2 = re.compile(r"\b(\d{1,2})\s+" + _MON_RE + r"[a-z]*\.?,?\s+(\d{4})"
                  r"(?:[,\s]+(?:at\s+)?(\d{1,2}):(\d{2}))?", re.I)
_TIME = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3])[:：][0-5]\d(?::[0-5]\d)?(?!\d)")


def _mk(y, mo, d, h, mi):
    try:
        return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0)), h is not None
    except (ValueError, TypeError):
        return None


def find_dates(text: str, default_year: int | None = None):
    """Return [(datetime, has_time, start, end)] for explicit dates in text."""
    out, taken = [], []
    text = fw(text)

    def add(m, parts):
        if any(s < m.end() and m.start() < e for s, e in taken):
            return
        r = _mk(*parts)
        if r:
            out.append((r[0], r[1], m.start(), m.end()))
            taken.append((m.start(), m.end()))

    for m in _ISO.finditer(text or ""):
        add(m, m.groups())
    for m in _EN1.finditer(text or ""):
        add(m, (m.group(3), _MON.index(m.group(1).lower()[:3]) + 1, m.group(2), m.group(4), m.group(5)))
    for m in _EN2.finditer(text or ""):
        add(m, (m.group(3), _MON.index(m.group(2).lower()[:3]) + 1, m.group(1), m.group(4), m.group(5)))
    if default_year:
        for m in _MD_ZH.finditer(text or ""):
            add(m, (default_year, m.group(1), m.group(2), m.group(3), m.group(4)))
    return sorted(out, key=lambda x: x[2])


def mask_dates(text: str, default_year: int | None = 2000) -> str:
    """Blank out dates and clock times so they are not mistaken for measurements."""
    chars = list(text or "")
    for _, _, s, e in find_dates(text, default_year):
        chars[s:e] = " " * (e - s)
    return _TIME.sub(lambda m: " " * len(m.group()), "".join(chars))


def parse_instant(raw, ref_tz=None):
    """Parse a timestamp. Returns (naive datetime | None, ok, tzinfo | None).

    A timestamp carrying a UTC offset is an absolute instant. It is converted to `ref_tz` (the cutoff's own
    offset) before the offset is dropped, so that instants with different offsets compare correctly; without a
    `ref_tz` its own local clock is kept and its tzinfo returned. Date-only values mean the end of that day.
    The protocol marker T0 is valid but has no calendar mapping: (None, True, None), with no date filtering.
    """
    if raw is None or raw == "":
        return None, True, None
    tz = None
    if isinstance(raw, bool):
        return None, False, None
    if isinstance(raw, (int, float)):
        try:
            dt = datetime.fromtimestamp(raw / 1000 if raw > 1e11 else raw, timezone.utc)
            has_time = True
        except (ValueError, OverflowError, OSError):
            return None, False, None
    else:
        s = str(raw).strip()
        if s == "T0":
            return None, True, None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
            has_time = len(s) > 10
        except ValueError:
            found = find_dates(s)
            if not found:
                return None, False, None
            dt, has_time = found[0][0], found[0][1]
    if dt.tzinfo is not None:
        if ref_tz is not None:
            dt = dt.astimezone(ref_tz)
        tz = dt.tzinfo
        dt = dt.replace(tzinfo=None)
    if not has_time:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt, True, tz


def parse_cutoff(raw):
    """Parse record_cutoff. Returns (datetime | None, ok), expressed in the cutoff's own local clock."""
    dt, ok, _ = parse_instant(raw)
    return dt, ok


def is_after(dt: datetime, has_time: bool, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return False
    return dt > cutoff if has_time else dt.date() > cutoff.date()


# ------------------------------------------------------------------ numbers
_UNITS = ["mmHg", "mmol/L", "µmol/L", "μmol/L", "umol/L", "mg/dL", "g/dL", "g/L", "mg/L", "ng/mL",
          "pg/mL", "ng/L", "µg/L", "μg/L", "ug/L", "mIU/L", "IU/L", "U/L", "mEq/L", "mOsm/kg",
          "×10^9/L", "x10^9/L", "*10^9/L", "10^9/L", "×10^12/L", "x10^12/L", "*10^12/L", "10^12/L",
          "×10⁹/L", "×10¹²/L", "×109/L", "×1012/L", "X109/L", "X1012/L", "L/min", "/min", "次/分", "bpm", "kPa", "%", "℃", "°C", "°F",
          "cm", "mm", "kg", "mL", "fL", "ms",
          # added after profiling real Chinese notes (MedCT-clinical-notes): doses, rates, immunoassay and pressure units
          "mg/kg", "mg/g", "mg/d", "mg", "μg", "µg", "ug", "g", "mL/kg/h", "mL/kg", "mL/min", "m/s", "cm/s", "mm/h",
          "cmH2O", "/μL", "/µL", "/uL", "mV", "mIU/mL", "IU/mL", "U/mL", "AU/mL", "nmol/L", "pmol/L", "copies/mL",
          "次/天", "次/日", "h", "min", "s", "IU", "U"]
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
_UNIT_ALT += r"|[×xX*]10(?:\^\d+|\d+|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)/[Ll]"   # scientific-notation counts (×10^6/L, ×106/L, ×10⁶/L …)
_NUM_STRICT = re.compile(r"(?<![A-Za-z0-9_.\-])(\d+(?:\.\d+)?)(?:\s*(" + _UNIT_ALT + r")(?![A-Za-z]))?", re.I)
_UNIT_ONLY = re.compile(_UNIT_ALT, re.I)
_NUM_ANY = re.compile(r"\d+(?:\.\d+)?")
# Only unambiguous analyte subscripts: the digits after the recognised prefix are the complete value.
# A generic letter+digit suffix is unsafe ("Creatinine120" must not manufacture 20 and 0).
_GLUED_NUM = re.compile(r"(?i)(?<![A-Za-z0-9])(PCO2|PO2|SO2|B12)(\d+(?:\.\d+)?)")
_SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


_ZH_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    u = u.lower().replace(" ", "").replace("μ", "u").replace("µ", "u")
    u = u.translate(_SUPER)                                  # superscript digits -> ascii
    u = u.replace("x10", "×10").replace("*10", "×10")
    u = re.sub(r"×10\^?(\d+)", r"×10^\1", u)                 # ×109 / ×10^9 / ×10⁹ -> ×10^9 (superscript lost in source)
    if u.startswith("10^"):
        u = "×" + u
    return {"℃": "°c", "次/分": "/min", "bpm": "/min"}.get(u, u)


def is_measurement_only(text: str) -> bool:
    value = fw(text).strip()
    return bool(_UNIT_ONLY.fullmatch(value) or _NUM_STRICT.fullmatch(value))


def extract_numbers(text: str) -> list[tuple[float, str | None, str]]:
    """Conservative extraction for *generated* text: (value, normalised unit, raw)."""
    return [(float(m.group(1)), norm_unit(m.group(2)), m.group(0).strip())
            for m in _NUM_STRICT.finditer(fw(text))]


_NUM_UNIT_ANY = re.compile(r"(\d+(?:\.\d+)?)\s*(" + _UNIT_ALT + r")(?![A-Za-z])", re.I)


def all_number_units(text: str) -> dict:
    """Permissive value -> {units} map for *source* text. Records often glue the label to the number ("R20次/分"),
    which the strict extractor skips; missing that unit made a correct "R 20次/分" look like a unit mismatch."""
    out: dict = {}
    for m in _NUM_UNIT_ANY.finditer(fw(text)):
        out.setdefault(float(m.group(1)), set()).add(norm_unit(m.group(2)))
    return out


def all_number_values(text: str) -> set[float]:
    """Permissive extraction for *source* text (superset => fewer false alarms)."""
    t = fw(text)
    vals = {float(x) for x in _NUM_ANY.findall(t)}
    # Some records glue an analyte subscript to its complete value ("PCO232.4 mmHg" means PCO2 = 32.4,
    # "维生素B12766.49pg/ml" means B12 = 766.49). Recover only these recognised forms; arbitrary suffix slicing
    # would accept incorrect clinical measurements ("Creatinine120" must not make 20 or 0 source-supported).
    for m in _GLUED_NUM.finditer(t):
        vals.add(float(m.group(2)))
    vals |= {float(_ZH_NUM[ch]) for ch in set(text or "") if ch in _ZH_NUM}
    return vals


# ----------------------------------------------------------------- negation
_NEG_PRE = re.compile(
    r"(?i)\b(?:no evidence of|no history of|no known|no signs? of|negative for|absence of|free of|"
    r"denies|denied|deny|without|never had|(?:does|did|do|has|have|had|is|was|are|were)\s+not|no|nor)\b"
    # Chinese cues, tuned on CHIP-CDEE train (real EMR sentences with polarity labels):
    #  - "无明显诱因出现咳嗽" is a fixed phrase (no obvious precipitant); it does not negate what follows
    #  - "无尿" alone is anuria (a positive finding) but "无尿频、尿急、尿痛" is a negated list
    r"|否认|未(?:再)?(?:见|[\u4e00-\u9fff]?及|发现|引出|诉|述|出现|查见|发生|检出|检验出|闻|触)|不伴|不会|没有"
    r"|无(?!力|菌|创|法|效|关|名|需|论|痛性|(?:明显|任何|特殊)?(?:诱因|原因)|意中|意间|尿(?:[，,。；;、\s\d]|$|约|[一二三四五六七八九十半数]))")
_NEG_POST = re.compile(r"(?i)\b(?:negative(?!\s+for)|absent|denied|not present)\b|阴性(?!表现|体征|结果|症状|发现|记录|信息|所见|资料|病史)|[（(]\s*[-－—]\s*[）)]|[:：]\s*(?:无|未见|未及|否认)(?=[\s，,。；;]|$)"
                       r"|未引出|(?:均|暂|尚)?无特殊|暂无|无殊|(?<=[\u4e00-\u9fff])史无(?=[。；;，,、]|$)"
                       r"|(?<=[一-鿿A-Za-z])(?:均|亦|也)?否认(?=[。；;，,]|$)")   # postfix absence predicates negate the preceding subject ("病理征未引出", "家族史均无特殊")
_END_EN = re.compile(r"(?i)[;!?]|\.(?!\d)|—|\b(?:but|however|although|though|except|whereas|while|reports?|"
                     r"reported|has|had|presents?|complains?|with|positive|present)\b")
_END_ZH = re.compile(r"[，,；;。！？（(]|但|伴有")
# Inside a "、"-list after a Chinese negation cue, an item that is itself a statement ("闭合良好", "肌力5级",
# "偶有恶心", "腹腔干…为真腔供血") is not part of the negated list. Found on the first real-model run.
_POS_ITEM = re.compile(r"正常|良好|存在|尚可|欠|增高|升高|降低|减低|阳性|灵敏|对称|通畅|清楚|\d\s*级|供血|偶有|时有|伴|有(?!无)|为|呈|示|可见|可及|可闻")
_CLAUSE_START = re.compile(r"[,，;；。:：]|\s{2,}|\t")     # runs of spaces separate columns in tabular exam records
_TERM_SPLIT = re.compile(r"(?i)、|/|及|或|和|与|,|\bor\b|\band\b|\bnor\b")
_TERM_CUT = re.compile(r"(?i)\s+(?:on|at|in|since|for|during|prior|before|after|to|of the)\b.*$")
_TERM_LEAD = re.compile(r"(?i)^(?:any|a|an|the|known|prior|previous|recent|history of|明显|既往|其他|其它)\s*")
_TERM_TAIL = re.compile(r"(?i)(?:\s+history|史|等|均)$")   # "Brudzinski征均阴性": 均 is a quantifier, not the term
_TERM_BING = re.compile(r"(?<=[^尿心肝肾肺胃脑肠胆疾脏])病$")   # "高血压病(史)" -> "高血压", but keep 糖尿病 / 冠心病 / 疾病


def neg_spans(sentence: str) -> list[tuple[int, int]]:
    """Character spans of a sentence that fall under a negation cue."""
    spans = []
    for m in _NEG_PRE.finditer(sentence):
        ender = _END_ZH if _CJK.search(m.group()) else _END_EN
        e = ender.search(sentence, m.end())
        end = e.start() if e else len(sentence)
        if ender is _END_ZH:
            pos = m.end()
            for item in sentence[m.end():end].split("、"):
                # judged per coordinated part: "内分泌系统等重要脏器疾病史及传染病史" is two list items, not one long statement
                if pos > m.end() and (_POS_ITEM.search(item) or max(len(x) for x in re.split(r"及|和|与|或", item)) > 14):
                    end = pos - 1
                    break
                pos += len(item) + 1
        spans.append((m.end(), end))
    for m in _NEG_POST.finditer(sentence):
        # "移动性浊音：阴性" / "皮下捻发感：无": the label before the colon is what is negated
        limit = len(sentence[:m.start()].rstrip(" \t:："))
        start = 0
        for c in _CLAUSE_START.finditer(sentence, 0, limit):
            start = c.end()
        spans.append((start, m.start()))
    return spans


def _clean_term(t: str) -> str:
    t = t.strip(" \t.。:：()（）\"'").lower()
    t = _TERM_CUT.sub("", t)
    prev = None
    while prev != t:
        prev = t
        t = _TERM_LEAD.sub("", t)
        t = _TERM_TAIL.sub("", t).strip()
        if len(t) >= 4:
            t = _TERM_BING.sub("", t)          # inside the loop: "肝炎等病史" -> "肝炎等病" -> "肝炎等" -> "肝炎"
    return t


def negated_terms(sentence: str) -> list[str]:
    out = []
    for s, e in neg_spans(sentence):
        for raw in _TERM_SPLIT.split(sentence[s:e]):
            t = _clean_term(raw)
            if not t:
                continue
            cjk = bool(_CJK.search(t))
            if (cjk and 2 <= len(t) <= 12) or (not cjk and 4 <= len(t) <= 40):
                out.append(t)
    return out


_DENIAL = re.compile(r"(?i)\b(?:denies|denied|deny|no history of|no known)\b|否认")


def denied_terms(sentence: str) -> list[str]:
    """Terms under an explicit denial of history ("否认糖尿病史", "denies diabetes"). Unlike a site- or time-specific
    negative finding ("未扪及肿块"), a denied history that is asserted elsewhere is a genuine record conflict."""
    out = []
    for m in _DENIAL.finditer(sentence):
        e = (_END_ZH if _CJK.search(m.group()) else _END_EN).search(sentence, m.end())
        for raw in _TERM_SPLIT.split(sentence[m.end():e.start() if e else len(sentence)]):
            t = _clean_term(raw)
            cjk = bool(_CJK.search(t))
            if t and ((cjk and 2 <= len(t) <= 12) or (not cjk and 4 <= len(t) <= 40)):
                out.append(t)
    return out


def positive_text(sentence: str) -> str:
    """Sentence with negated spans blanked out (lower-cased)."""
    chars = list(sentence)
    for s, e in neg_spans(sentence):
        chars[s:e] = " " * (e - s)
    return "".join(chars).lower()


def clearly_positive_text(sentence: str) -> str:
    """Only the part of a sentence before its first negation cue (and outside postfix-negated clauses). Record
    sentences often continue a negated list across commas ("未见乳头凹陷，皮肤改变、酒窝征等"), so anything after a
    cue is ambiguous; use this view when a false alarm is worse than a miss."""
    m = _NEG_PRE.search(sentence)
    pos = positive_text(sentence)          # computed on the whole sentence so that "X：无" still negates X
    return pos[:m.start()] if m else pos


def term_positive_in(term: str, sentence: str) -> bool:
    """True if `term` occurs in `sentence` outside every negation span."""
    return term in positive_text(sentence)


# ------------------------------------------------------------ lexical support
_STOP = set("the and for with was were has had have are that this from not but his her their patient pt "
            "who which also been being there than then into onto about over under after before during "
            "per via will would should could may might can".split())
_STOP_ZH = {"患者", "病人", "目前", "考虑", "予以", "进行", "以及", "因为", "所以", "的是"}


def tokens(text: str) -> set[str]:
    text = fw(text).lower()
    toks = {w[:6] for w in re.findall(r"[a-z]{3,}", text) if w not in _STOP}
    toks |= {("#%g" % float(n)) for n in _NUM_ANY.findall(text)}
    for run in re.findall(r"[一-鿿]+", text):
        toks |= {run[i:i + 2] for i in range(len(run) - 1)} - _STOP_ZH
    return toks


def support(statement: str, source_tokens: set[str]) -> float:
    """Fraction of a statement's content tokens that occur in the source tokens (0..1)."""
    st = tokens(statement)
    return 1.0 if not st else len(st & source_tokens) / len(st)


_NORMAL = re.compile(r"(?i)\b(?:normal|unremarkable|within normal limits|wnl)\b|正常|未见异常|无异常|无殊")
_DONE = re.compile(r"(?i)\b(?:was|were|has been|have been|had been)\s+(?:\w+ly\s+)?(?:performed|done|given|"
                   r"administered|started|initiated|completed|obtained|placed|transfused|inserted)\b"
                   r"|已行|已予|已给予|已完成|已完善|已开始|已输注|已置入")
_CERTAIN = re.compile(r"(?i)\b(?:confirmed|definite(?:ly)?|definitive|diagnostic of|certainly)\b|确诊|明确诊断|诊断(?:已)?明确|诊断成立|确定诊断|可确诊")
_MISSING = re.compile(r"(?i)\b(?:pending|not (?:yet )?(?:available|done|performed|obtained|documented|resulted|known|recorded)|"
                      r"unknown|unavailable|awaiting|unable to (?:obtain|recall)|not on file|to be (?:obtained|confirmed))\b"
                      r"|未查|未做|未提供|不详|未测|待查|结果未回|未回报|待回报|未记录|未记载|未提及|未说明|未描述|未载|未问及"
                      r"|无法提供|待完善|缺少|缺失|尚缺|暂缺"
                      r"|(?:无|未见|未获得|没有)[^，,。；;]{0,30}(?:记录|资料|结果|报告|信息|描述)")
_UNCERTAIN = re.compile(r"(?i)\b(?:possibl[ey]|probabl[ey]|suspected|suspicious|likely|cannot (?:be )?exclude[d]?|"
                        r"rule out|r/o|query|questionable|appears?|may (?:be|represent)|\?)\b|\?|？|可能|考虑|疑似|待排|不除外|可疑")

has_normal_cue = lambda t: bool(_NORMAL.search(t or ""))
has_done_cue = lambda t: bool(_DONE.search(t or ""))
has_certain_cue = lambda t: bool(_CERTAIN.search(t or ""))
# A certainty word in a negated, pending or planned clause is not a definitive claim: "不能确诊糖尿病",
# "需G/GM试验及培养确诊", "待病理明确诊断".
_CERTAIN_VOID = re.compile(r"(?i)不能|不可|无法|未能|尚未|未|难以|不足以|需|须|有待|待|拟|建议|以便|以|进一步|方可|才能"
                           r"|\b(?:not|cannot|no|until|pending|to be|needs?|requires?|awaiting)\b")
_CLAUSE = re.compile(r"[，,；;。！？!?：:\n]")


def definitive_claims(text: str) -> list[str]:
    """Clauses that make a definitive diagnostic claim: a certainty cue not voided by negation, intent or uncertainty."""
    out = []
    for clause in _CLAUSE.split(text or ""):
        m = _CERTAIN.search(clause)
        if m and not _CERTAIN_VOID.search(clause[:m.start()]) and not has_uncertain_cue(clause):
            out.append(clause.strip())
    return out
has_missing_cue = lambda t: bool(_MISSING.search(t or ""))
has_uncertain_cue = lambda t: bool(_UNCERTAIN.search(t or ""))
