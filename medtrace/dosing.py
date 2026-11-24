"""Table-driven dose check for antithrombotics in plan text (spec §8), independent of the aortic rule.

Findings are flags only: a dose is never rewritten. Two checks:
  loading_dose_as_maintenance  a loading-size single dose given repeatedly every day, or a dose the records show was
                               given once (e.g. an outside loading dose) repeated daily above usual maintenance
  dose_above_daily_max         a daily total above the labelled adult maximum
Thresholds are adult label values used as engineering screening limits, not prescribing advice; weight- or
INR-titrated drugs (warfarin, enoxaparin and other LMWH, heparin) have no fixed limit here. Clinical review: PENDING.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import aortic as A
from . import textutil as T

# canonical: (usual adult maintenance mg/day upper bound, loading single dose mg, labelled max mg/day or None)
DOSE_RULES = {
    "aspirin": (100, 300, None),           # antiplatelet 75-100 mg/d; analgesic doses are indication-dependent
    "clopidogrel": (75, 300, 150),
    "ticagrelor": (180, 180, 180),         # 90 mg bid; loading 180 mg once
    "prasugrel": (10, 60, 10),
    "indobufen": (400, None, 400),         # 100-200 mg bid
    "cilostazol": (200, None, 200),        # 100 mg bid
    "rivaroxaban": (20, None, 30),         # 15 mg bid in the first 21 days of VTE treatment
    "apixaban": (10, None, 20),            # 10 mg bid in the first 7 days of VTE treatment
    "edoxaban": (60, None, 60),
    "dabigatran": (300, None, 300),        # 150 mg bid
    "fondaparinux": (10, None, 10),
}
_DOSE = re.compile(r"^[^\d，,；;。]{0,10}?(\d+(?:\.\d+)?)\s*(mg|g)(?![a-z])")
_FREQ = [
    (re.compile(r"bid|b\.i\.d|q12h|(?:每日|每天|一日)\s*(?:两|二|2)\s*次|2\s*次\s*/\s*(?:日|天|d\b)|twice daily"), 2),
    (re.compile(r"tid|t\.i\.d|q8h|(?:每日|每天|一日)\s*(?:三|3)\s*次|3\s*次\s*/\s*(?:日|天|d\b)|three times daily"), 3),
    (re.compile(r"(?<![a-z])(?:qd|qn|qam|qpm)(?![a-z])|(?:每日|每天|一日)\s*(?:一|1)\s*次|1\s*次\s*/\s*(?:日|天|d\b)|每晚|once daily"), 1),
    (re.compile(r"^\s*/\s*(?:日|天|d\b|day)|^\s*(?:每日|每天)(?!\s*[一二两三1-3]\s*次)|daily|per day"), 1),   # a daily total
]
_LOADING_CUE = re.compile(r"负荷|首剂|顿服|一次性|嚼服|loading|single dose|\bstat\b")
_ONCE_SOURCE = re.compile(r"予|给予|口服|嚼服|顿服|负荷|服用")


@dataclass
class DoseFinding:
    code: str
    drug: str
    per_dose_mg: float
    times_per_day: int
    daily_mg: float
    limit_mg: float
    reason: str


def _doses(text: str):
    """[(canonical, per-dose mg, times per day or None, clause)] for rule drugs in `text`."""
    out = []
    for clause in re.split(r"[，,；;。\n]", T.fw(text).lower()):
        for canon, _, _, rx in A._DRUGS:
            if canon not in DOSE_RULES:
                continue
            for m in rx.finditer(clause):
                d = _DOSE.search(clause[m.end():])
                if not d:
                    continue
                mg = float(d.group(1)) * (1000 if d.group(2) == "g" else 1)
                tail = clause[m.end() + d.end():m.end() + d.end() + 14]
                times = next((n for rx_f, n in _FREQ if rx_f.search(tail)), None)
                out.append((canon, mg, times, clause))
    return out


def _source_once(source_text: str) -> dict:
    """{canonical: {mg}} for doses the records show as given once (no frequency), e.g. "予阿司匹林300mg、氯吡格雷300mg口服"."""
    once = {}
    for sent in T.split_sentences(source_text or ""):
        if not _ONCE_SOURCE.search(sent):
            continue
        for canon, mg, times, _ in _doses(sent):
            if times is None:
                once.setdefault(canon, set()).add(mg)
    return once


def dose_findings(text: str, source_text: str = "") -> list[DoseFinding]:
    """Dose findings for plan `text`; `source_text` (the input records) lets a once-given dose be recognised."""
    out, once = [], _source_once(source_text)
    for canon, mg, times, clause in _doses(text):
        if times is None:
            continue                               # no frequency: not a daily regimen
        maint, loading, max_day = DOSE_RULES[canon]
        daily = mg * times
        loading_cue = bool(_LOADING_CUE.search(clause))
        if not loading_cue and loading and mg >= loading:
            out.append(DoseFinding("loading_dose_as_maintenance", canon, mg, times, daily, loading, "LOADING_SIZE_DOSE_DAILY"))
        elif not loading_cue and mg in once.get(canon, ()) and daily > maint:
            out.append(DoseFinding("loading_dose_as_maintenance", canon, mg, times, daily, maint, "SOURCE_ONE_TIME_DOSE_REPEATED_DAILY"))
        elif max_day is not None and daily > max_day and not loading_cue:
            out.append(DoseFinding("dose_above_daily_max", canon, mg, times, daily, max_day, "ABOVE_LABELLED_DAILY_MAX"))
    return out


def loading_as_maintenance(text: str) -> list[tuple[str, float]]:
    """Earlier interface: (drug, daily mg) for loading-size doses given daily."""
    return [(f.drug, f.daily_mg) for f in dose_findings(text) if f.code == "loading_dose_as_maintenance"]
