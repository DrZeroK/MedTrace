"""Deterministic text primitives shared by the fact ledger and the verifier.

Everything here is pure Python and language-aware for English and Chinese.
These are heuristics: they are used to *flag* statements, never to rewrite them.
"""
from __future__ import annotations

import re
from datetime import datetime

_CJK = re.compile(r"[一-鿿]")


def detect_lang(text: str) -> str:
    if not text:
        return "en"
    return "zh" if len(_CJK.findall(text)) / max(1, len(text)) > 0.15 else "en"


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
_ISO = re.compile(r"(?<!\d)(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?" + _HM)
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


def parse_cutoff(raw):
    """Parse record_cutoff. Returns (datetime | None, ok). Date-only => end of that day."""
    if raw is None or raw == "":
        return None, True
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            v = raw / 1000 if raw > 1e11 else raw
            return datetime.utcfromtimestamp(v), True
        except (ValueError, OverflowError, OSError):
            return None, False
    s = str(raw).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        has_time = len(s) > 10
        dt = dt.replace(tzinfo=None)
    except ValueError:
        found = find_dates(s)
        if not found:
            return None, False
        dt, has_time = found[0][0], found[0][1]
    if not has_time:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt, True


def is_after(dt: datetime, has_time: bool, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return False
    return dt > cutoff if has_time else dt.date() > cutoff.date()


# ------------------------------------------------------------------ numbers
_UNITS = ["mmHg", "mmol/L", "µmol/L", "μmol/L", "umol/L", "mg/dL", "g/dL", "g/L", "mg/L", "ng/mL",
          "pg/mL", "ng/L", "µg/L", "μg/L", "ug/L", "mIU/L", "IU/L", "U/L", "mEq/L", "mOsm/kg",
          "×10^9/L", "x10^9/L", "*10^9/L", "10^9/L", "×10^12/L", "x10^12/L", "*10^12/L", "10^12/L",
          "×10⁹/L", "×10¹²/L", "L/min", "/min", "次/分", "bpm", "kPa", "%", "℃", "°C", "°F",
          "cm", "mm", "kg", "mL", "fL", "ms"]
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
_NUM_STRICT = re.compile(r"(?<![A-Za-z0-9_.\-])(\d+(?:\.\d+)?)(?:\s*(" + _UNIT_ALT + r")(?![A-Za-z]))?", re.I)
_NUM_ANY = re.compile(r"\d+(?:\.\d+)?")


def norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    u = u.lower().replace(" ", "").replace("μ", "u").replace("µ", "u")
    u = u.replace("x10", "×10").replace("*10", "×10").replace("⁹", "^9").replace("¹²", "^12")
    if u.startswith("10^"):
        u = "×" + u
    return {"℃": "°c", "次/分": "/min", "bpm": "/min"}.get(u, u)


def extract_numbers(text: str) -> list[tuple[float, str | None, str]]:
    """Conservative extraction for *generated* text: (value, normalised unit, raw)."""
    return [(float(m.group(1)), norm_unit(m.group(2)), m.group(0).strip())
            for m in _NUM_STRICT.finditer(text or "")]


def all_number_values(text: str) -> set[float]:
    """Permissive extraction for *source* text (superset => fewer false alarms)."""
    return {float(x) for x in _NUM_ANY.findall(text or "")}


# ----------------------------------------------------------------- negation
_NEG_PRE = re.compile(
    r"(?i)\b(?:no evidence of|no history of|no known|no signs? of|negative for|absence of|free of|"
    r"denies|denied|deny|without|never had|(?:does|did|do|has|have|had|is|was|are|were)\s+not|no|nor)\b"
    r"|否认|未见|未闻及|未触及|未扪及|未及|未发现|未引出|未诉|不伴|没有|无(?!力|尿|菌|创|法|效|关|名|需|论|痛性)")
_NEG_POST = re.compile(r"(?i)\b(?:negative(?!\s+for)|absent|denied|not present)\b|阴性|[（(]\s*[-－—]\s*[）)]")
_END_EN = re.compile(r"(?i)[;!?]|\.(?!\d)|—|\b(?:but|however|although|though|except|whereas|while|reports?|"
                     r"reported|has|had|presents?|complains?|with|positive|present)\b")
_END_ZH = re.compile(r"[，,；;。！？]|但|伴有")
_CLAUSE_START = re.compile(r"[,，;；。:：]")
_TERM_SPLIT = re.compile(r"(?i)、|/|及|或|和|与|,|\bor\b|\band\b|\bnor\b")
_TERM_CUT = re.compile(r"(?i)\s+(?:on|at|in|since|for|during|prior|before|after|to|of the)\b.*$")
_TERM_LEAD = re.compile(r"(?i)^(?:any|a|an|the|known|prior|previous|recent|history of|明显|既往|其他|其它)\s*")
_TERM_TAIL = re.compile(r"(?i)(?:\s+history|病史|史|等)$")


def neg_spans(sentence: str) -> list[tuple[int, int]]:
    """Character spans of a sentence that fall under a negation cue."""
    spans = []
    for m in _NEG_PRE.finditer(sentence):
        ender = _END_ZH if _CJK.search(m.group()) else _END_EN
        e = ender.search(sentence, m.end())
        spans.append((m.end(), e.start() if e else len(sentence)))
    for m in _NEG_POST.finditer(sentence):
        start = 0
        for c in _CLAUSE_START.finditer(sentence, 0, m.start()):
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


def positive_text(sentence: str) -> str:
    """Sentence with negated spans blanked out (lower-cased)."""
    chars = list(sentence)
    for s, e in neg_spans(sentence):
        chars[s:e] = " " * (e - s)
    return "".join(chars).lower()


def term_positive_in(term: str, sentence: str) -> bool:
    """True if `term` occurs in `sentence` outside every negation span."""
    return term in positive_text(sentence)


# ------------------------------------------------------------ lexical support
_STOP = set("the and for with was were has had have are that this from not but his her their patient pt "
            "who which also been being there than then into onto about over under after before during "
            "per via will would should could may might can".split())
_STOP_ZH = {"患者", "病人", "目前", "考虑", "予以", "进行", "以及", "因为", "所以", "的是"}


def tokens(text: str) -> set[str]:
    text = (text or "").lower()
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
_CERTAIN = re.compile(r"(?i)\b(?:confirmed|definite(?:ly)?|definitive|diagnostic of|certainly)\b|确诊|明确诊断|诊断明确")
_MISSING = re.compile(r"(?i)\b(?:pending|not (?:yet )?(?:available|done|performed|obtained|documented|resulted|known|recorded)|"
                      r"unknown|unavailable|awaiting|unable to (?:obtain|recall)|not on file|to be (?:obtained|confirmed))\b"
                      r"|未查|未做|未提供|不详|未测|待查|结果未回|未回报|待回报|未记录|无法提供|待完善")
_UNCERTAIN = re.compile(r"(?i)\b(?:possibl[ey]|probabl[ey]|suspected|suspicious|likely|cannot (?:be )?exclude[d]?|"
                        r"rule out|r/o|query|questionable|appears?|may (?:be|represent)|\?)\b|\?|？|可能|考虑|疑似|待排|不除外|可疑")

has_normal_cue = lambda t: bool(_NORMAL.search(t or ""))
has_done_cue = lambda t: bool(_DONE.search(t or ""))
has_certain_cue = lambda t: bool(_CERTAIN.search(t or ""))
has_missing_cue = lambda t: bool(_MISSING.search(t or ""))
has_uncertain_cue = lambda t: bool(_UNCERTAIN.search(t or ""))
