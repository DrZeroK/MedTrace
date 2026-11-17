"""Internal note representation, tolerant parsing of model output, and output serialisation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .textutil import split_sentences, strip_enum

SECTIONS = ("case_features", "diagnostic_discussion", "treatment_plan")
_ALIASES = {
    "case_features": ("case_features", "features", "case_characteristics", "病例特点"),
    "diagnostic_discussion": ("diagnostic_discussion", "discussion", "diagnosis_discussion", "拟诊讨论", "诊断讨论"),
    "treatment_plan": ("treatment_plan", "diagnostic_and_treatment_plan", "plan", "诊疗计划"),
}
_MARK = re.compile(r"\s*\[\[([^\[\]]+)\]\]")
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)
REVIEW_TYPES = ("missing", "conflict", "verify")


class ParseError(Exception):
    pass


@dataclass
class Statement:
    text: str
    sources: list = field(default_factory=list)
    kind: str = ""
    basis: str = ""             # record | knowledge | inference (optional; discussion/plan)


@dataclass
class Note:
    sections: dict = field(default_factory=lambda: {s: [] for s in SECTIONS})
    review_items: list = field(default_factory=list)     # [{type, description, source_ids}]
    extra_evidence: list = field(default_factory=list)   # model-supplied evidence list (baseline format)
    structured: bool = True                              # False when the model returned free prose

    def copy(self) -> "Note":
        return Note({k: [Statement(s.text, list(s.sources), s.kind, s.basis) for s in v] for k, v in self.sections.items()},
                    [dict(r) for r in self.review_items], [dict(e) for e in self.extra_evidence], self.structured)

    def text(self, section=None) -> str:
        secs = [section] if section else SECTIONS
        return "\n".join(s.text for sec in secs for s in self.sections[sec])


def parse_json_object(text: str) -> dict:
    """Extract one JSON object from model text (handles reasoning tags, code fences, trailing commas)."""
    if not isinstance(text, str) or not text.strip():
        raise ParseError("empty model response")
    t = _FENCE.sub("", _THINK.sub("", text).strip())
    candidates = [t]
    i, j = t.find("{"), t.rfind("}")
    if 0 <= i < j:
        candidates.append(t[i:j + 1])
        candidates.append(re.sub(r",\s*([}\]])", r"\1", t[i:j + 1]))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    raise ParseError("model response is not a JSON object")


def _ids(v) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, (list, tuple)):
        v = re.split(r"[,;，；]", str(v))
    out = []
    for x in v:
        x = str(x).strip().strip("[]")
        if x and x not in out:
            out.append(x)
    return out


def _stmt(item) -> Statement | None:
    if isinstance(item, str):
        text, src, kind, basis = item, [], "", ""
    elif isinstance(item, dict):
        text = item.get("text") or item.get("statement") or item.get("content") or item.get("description") or ""
        src = _ids(item.get("sources", item.get("source_ids", item.get("source"))))
        kind = str(item.get("kind") or item.get("type") or "")
        basis = str(item.get("basis") or "").strip().lower()
        if basis not in ("record", "knowledge", "inference"):   # auxiliary field: drop off-enum values rather than fail schema
            basis = ""
    else:
        return None
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    for m in _MARK.finditer(text):       # inline [[id]] markers are folded into the source list
        for i in _ids(m.group(1)):
            if i not in src:
                src.append(i)
    text = strip_enum(_MARK.sub("", text))
    return Statement(text, src, kind, basis) if text else None


def note_from_model(obj: dict) -> Note:
    note = Note()
    found = False
    for sec, names in _ALIASES.items():
        val = next((obj[n] for n in names if n in obj), None)
        if val is None:
            continue
        found = True
        if isinstance(val, str):
            note.structured = False
            items = [l for l in val.split("\n") if l.strip()]
            if len(items) == 1:
                items = split_sentences(val)
        elif isinstance(val, list):
            items = val
        elif isinstance(val, dict):
            items = [x for v in val.values() for x in (v if isinstance(v, list) else [v])]
        else:
            items = [str(val)]
        note.sections[sec] = [s for s in (_stmt(i) for i in items) if s]
    if not found:
        raise ParseError("model JSON has none of the required sections")
    for r in obj.get("review_items") or []:
        if isinstance(r, str):
            r = {"type": "verify", "text": r}
        if not isinstance(r, dict):
            continue
        desc = r.get("text") or r.get("description") or r.get("item") or ""
        typ = str(r.get("type") or "verify").lower()
        if desc:
            note.review_items.append({"type": typ if typ in REVIEW_TYPES else "verify", "description": str(desc),
                                      "source_ids": _ids(r.get("sources", r.get("source_ids")))})
    for e in obj.get("evidence") or []:
        if isinstance(e, dict) and (e.get("statement") or e.get("claim") or e.get("text")):
            note.extra_evidence.append({"section": str(e.get("section") or ""),
                                        "statement": str(e.get("statement") or e.get("claim") or e.get("text")),
                                        "source_ids": _ids(e.get("source_ids", e.get("sources")))})
    return note


def render_section(stmts: list[Statement], numbered: bool, inline: bool) -> str:
    lines = []
    for i, s in enumerate(stmts, 1):
        t = s.text + (f" [{', '.join(s.sources)}]" if inline and s.sources else "")
        lines.append(f"{i}. {t}" if numbered and len(stmts) > 1 else t)
    return "\n".join(lines)


def to_record(note: Note, case, cfg, meta: dict | None = None) -> dict:
    """Serialise to the output contract. Field names/selection are configurable (official schema TBC)."""
    rid = case.raw_id
    numbered = cfg.numbered and note.structured
    rec = {"case_id": case.case_id}
    for sec in SECTIONS:
        rec[sec] = render_section(note.sections[sec], numbered, cfg.inline_citations)
    evidence = []
    for sec in SECTIONS:
        for s in note.sections[sec]:
            if not s.sources:
                continue
            e = {"section": sec, "statement": s.text, "source_ids": [rid(i) for i in s.sources]}
            if s.basis:
                e["basis"] = s.basis
            evidence.append(e)
    evidence += [{"section": e["section"], "statement": e["statement"], "source_ids": [rid(i) for i in e["source_ids"]]}
                 for e in note.extra_evidence if e["source_ids"]]
    rec["evidence"] = evidence
    rec["review_items"] = [{"type": r["type"], "description": r["description"],
                            "source_ids": [rid(i) for i in r.get("source_ids", [])]} for r in note.review_items]
    if cfg.include_meta and meta:
        rec["meta"] = meta
    if cfg.output_fields:
        rec = {k: v for k, v in rec.items() if k == "case_id" or k in cfg.output_fields}
    if cfg.output_field_map:
        rec = {cfg.output_field_map.get(k, k): v for k, v in rec.items()}
    return rec


OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["case_id", "case_features", "diagnostic_discussion", "treatment_plan", "evidence", "review_items"],
    "properties": {
        "case_features": {"type": "string", "minLength": 1},
        "diagnostic_discussion": {"type": "string", "minLength": 1},
        "treatment_plan": {"type": "string", "minLength": 1},
        "evidence": {"type": "array", "items": {
            "type": "object", "required": ["section", "statement", "source_ids"],
            "properties": {"section": {"type": "string"}, "statement": {"type": "string"},
                           "source_ids": {"type": "array", "minItems": 1},
                           "basis": {"enum": ["record", "knowledge", "inference"]}}}},
        "review_items": {"type": "array", "items": {
            "type": "object", "required": ["type", "description", "source_ids"],
            "properties": {"type": {"enum": list(REVIEW_TYPES)}, "description": {"type": "string", "minLength": 1},
                           "source_ids": {"type": "array"}}}},
    },
}


def schema_errors(rec: dict) -> list[str]:
    """Validate a default-profile record. Uses jsonschema when installed, else an equivalent manual check."""
    try:
        import jsonschema
        return [e.message for e in jsonschema.Draft7Validator(OUTPUT_SCHEMA).iter_errors(rec)]
    except ImportError:
        errs = [f"missing {k}" for k in OUTPUT_SCHEMA["required"] if k not in rec]
        errs += [f"{k} must be a non-empty string" for k in SECTIONS if not (isinstance(rec.get(k), str) and rec.get(k))]
        errs += [f"{k} must be a list" for k in ("evidence", "review_items") if not isinstance(rec.get(k), list)]
        errs += [f"evidence basis must be record/knowledge/inference" for e in rec.get("evidence", [])
                 if isinstance(e, dict) and "basis" in e and e["basis"] not in ("record", "knowledge", "inference")]
        return errs
