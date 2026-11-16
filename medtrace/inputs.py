"""Module A - input processing: load, validate, apply the information cutoff."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .textutil import detect_lang, find_dates, is_after, parse_cutoff, split_sentences

_TIME_KEYS = ("time", "timestamp", "datetime", "recorded_at", "record_time", "date", "created_at")
_LIST_KEYS = ("cases", "data", "records", "items", "inputs")


class InputError(Exception):
    """Fatal: the input file as a whole cannot be used."""


@dataclass
class Source:
    sid: str            # string key used internally and in prompts
    raw_id: Any         # original identifier, echoed back unchanged in the output
    content: str        # content visible to the model (after cutoff handling)
    original: str       # untouched original content
    time: datetime | None = None


@dataclass
class Case:
    index: int
    case_id: Any
    cutoff_raw: Any = None
    cutoff: datetime | None = None
    sources: list[Source] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)       # fatal for this case
    warnings: list[str] = field(default_factory=list)
    excluded_sources: list[str] = field(default_factory=list)
    redacted: list[tuple[str, str]] = field(default_factory=list)   # (sid, sentence) beyond cutoff
    lang: str = "en"

    @property
    def usable(self) -> bool:
        return not self.errors and bool(self.sources)

    @property
    def valid_ids(self) -> set[str]:
        return {s.sid for s in self.sources}

    def raw_id(self, sid: str):
        for s in self.sources:
            if s.sid == sid:
                return s.raw_id
        return sid

    @property
    def text(self) -> str:
        return "\n".join(s.content for s in self.sources)


def read_json(path: str):
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise InputError(f"cannot read input file {path!r}: {e}") from e
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise InputError(f"input file {path!r} is not valid UTF-8 JSON: {e}") from e


def split_envelope(doc):
    """Return (list_of_case_dicts, envelope) where envelope is 'list', 'single' or a key name."""
    if isinstance(doc, list):
        return doc, "list"
    if isinstance(doc, dict):
        for k in _LIST_KEYS:
            if isinstance(doc.get(k), list):
                return doc[k], k
        if "sources" in doc or "case_id" in doc:
            return [doc], "single"
    raise InputError("top-level JSON must be a list of cases, an object holding a case list, or a single case")


def _source_time(d: dict):
    for k in _TIME_KEYS:
        if d.get(k) not in (None, ""):
            dt, ok = parse_cutoff(d[k])
            if ok and dt:
                has_time = isinstance(d[k], (int, float)) or len(str(d[k]).strip()) > 10
                return dt, has_time
    return None, False


def parse_case(raw, index: int, cutoff_mode: str = "redact") -> Case:
    if not isinstance(raw, dict):
        return Case(index=index, case_id=None, errors=["case is not a JSON object"])
    c = Case(index=index, case_id=raw.get("case_id"))
    if c.case_id is None or isinstance(c.case_id, (dict, list)):
        c.warnings.append("missing or non-scalar case_id")
    c.cutoff_raw = raw.get("record_cutoff")
    c.cutoff, ok = parse_cutoff(c.cutoff_raw)
    if not ok:
        c.warnings.append(f"record_cutoff {c.cutoff_raw!r} could not be parsed; no cutoff filtering applied")
    srcs = raw.get("sources")
    if not isinstance(srcs, list):
        c.errors.append("sources is missing or not a list")
        return c
    by_id: dict[str, Source] = {}
    for j, s in enumerate(srcs):
        if not isinstance(s, dict):
            c.warnings.append(f"sources[{j}] is not an object; skipped")
            continue
        content = s.get("content")
        if content is not None and not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if not content or not content.strip():
            c.warnings.append(f"sources[{j}] has empty content; skipped")
            continue
        rid = s.get("source_id")
        if rid is None or isinstance(rid, (dict, list)) or str(rid).strip() == "":
            rid = f"source_{j + 1}"
            c.warnings.append(f"sources[{j}] has no source_id; assigned {rid!r}")
        sid = str(rid).strip()
        t, t_has_time = _source_time(s)
        if cutoff_mode != "off" and t and is_after(t, t_has_time, c.cutoff):
            c.excluded_sources.append(sid)
            if cutoff_mode == "redact":
                continue
        if sid in by_id:  # duplicate identifier: keep one id, keep all text
            by_id[sid].content += "\n" + content
            by_id[sid].original += "\n" + content
            c.warnings.append(f"duplicate source_id {sid!r}; contents merged")
        else:
            by_id[sid] = Source(sid=sid, raw_id=rid, content=content, original=content, time=t)
    c.sources = list(by_id.values())
    if not c.sources:
        c.errors.append("no usable sources (all empty, malformed or beyond the cutoff)")
        return c
    if cutoff_mode != "off" and c.cutoff:
        _apply_sentence_cutoff(c, redact=(cutoff_mode == "redact"))
        c.sources = [s for s in c.sources if s.content.strip()]
        if not c.sources:
            c.errors.append("no source content remains before the cutoff")
    c.lang = detect_lang(c.text)
    return c


def _apply_sentence_cutoff(c: Case, redact: bool) -> None:
    """Statements carrying an explicit date later than the cutoff must not reach the model."""
    year = c.cutoff.year
    for s in c.sources:
        kept = []
        for line in s.content.split("\n"):
            parts = []
            for sent in split_sentences(line):
                late = any(is_after(dt, ht, c.cutoff) for dt, ht, _, _ in find_dates(sent, year))
                if late:
                    c.redacted.append((s.sid, sent))
                    if redact:
                        continue
                parts.append(sent)
            if parts:
                kept.append(" ".join(parts))
        if redact:
            s.content = "\n".join(kept)


def load_cases(path: str, cutoff_mode: str = "redact"):
    raw_cases, envelope = split_envelope(read_json(path))
    cases = [parse_case(rc, i, cutoff_mode) for i, rc in enumerate(raw_cases)]
    seen = {}
    for c in cases:
        key = json.dumps(c.case_id, ensure_ascii=False, sort_keys=True, default=str)
        if c.case_id is not None and key in seen:
            c.warnings.append(f"duplicate case_id (also at index {seen[key]}); both are processed and emitted in order")
        seen.setdefault(key, c.index)
    return cases, envelope
