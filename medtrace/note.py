"""Internal note representation, tolerant parsing of model output, and output serialisation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .textutil import detect_lang, split_sentences, strip_enum

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
# Verifier findings and internal pipeline warnings stay in run logs; the scored review_items
# must read as clinician-facing missing/conflict/confirmation items, not QA messages that quote
# our own draft back at the reader.
OFFICIAL_REVIEW_EXCLUDE = {"verifier", "internal"}


class ParseError(Exception):
    pass


@dataclass
class Statement:
    text: str
    sources: list = field(default_factory=list)
    kind: str = ""
    basis: str = ""             # record | knowledge | inference (optional; discussion/plan)
    knowledge_ids: list = field(default_factory=list)
    cont: bool = False          # continuation chunk of the previous statement (split_long_statements); rendered on its line


@dataclass
class Note:
    sections: dict = field(default_factory=lambda: {s: [] for s in SECTIONS})
    review_items: list = field(default_factory=list)     # [{type, description, source_ids}]
    extra_evidence: list = field(default_factory=list)   # model-supplied evidence list (baseline format)

    def copy(self) -> "Note":
        return Note({k: [Statement(s.text, list(s.sources), s.kind, s.basis, list(s.knowledge_ids), s.cont) for s in v] for k, v in self.sections.items()},
                    [dict(r) for r in self.review_items], [dict(e) for e in self.extra_evidence])

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
    last_error = None
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except ValueError as error:
            if isinstance(error, json.JSONDecodeError):
                last_error = error
            continue
    location = (f" ({last_error.msg}; line {last_error.lineno}, column {last_error.colno})" if last_error else "")
    raise ParseError("model response is not a JSON object" + location)


def _ids(v) -> list[str]:
    if v is None:
        return []
    literal_ids = isinstance(v, (list, tuple))
    if not literal_ids:
        v = re.split(r"[,;，；]", str(v))
    out = []
    for x in v:
        x = str(x) if literal_ids else str(x).strip().strip("[]")
        if x.strip() and x not in out:
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
    return Statement(text, src, kind, basis, _ids(item.get("knowledge_ids")) if isinstance(item, dict) else []) if text else None


def note_from_model(obj: dict, require_complete: bool = False) -> Note:
    note = Note()
    found = False
    for sec, names in _ALIASES.items():
        val = next((obj[n] for n in names if n in obj), None)
        if require_complete:
            items_to_check = val if isinstance(val, list) else [val]
            if not items_to_check or any(not isinstance(i, (str, dict)) for i in items_to_check):
                raise ParseError(f"missing or malformed required section: {sec}")
            for item in items_to_check:
                text = item if isinstance(item, str) else next((item[k] for k in ("text", "statement", "content", "description") if k in item), None)
                if not isinstance(text, str) or not text.strip():
                    raise ParseError(f"empty or malformed required section: {sec}")
        if val is None:
            continue
        found = True
        if isinstance(val, str):
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
        if require_complete and not note.sections[sec]:
            raise ParseError(f"empty required section: {sec}")
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
                                      "source_ids": _ids(r.get("sources", r.get("source_ids"))), "origin": "model"})
    for e in obj.get("evidence") or []:
        if isinstance(e, dict) and (e.get("statement") or e.get("claim") or e.get("text")):
            note.extra_evidence.append({"section": str(e.get("section") or ""),
                                        "statement": str(e.get("statement") or e.get("claim") or e.get("text")),
                                        "source_ids": _ids(e.get("source_ids", e.get("sources")))})
    return note


_TERMINAL = re.compile(r"[。！？；.!?;][\"'”’）)]*$")


def render_prose(stmts: list[Statement], inline: bool = False) -> str:
    """One paragraph per section; development and official outputs share this renderer.
    Evidence remains in the separate evidence array; inline citations stay attached to their statement."""
    texts = []
    for s in stmts:
        text = s.text.strip()
        if not text:
            continue
        if inline and s.sources:
            text += f" [{', '.join(s.sources)}]"
        texts.append(text)
    if not texts:
        return ""
    zh = detect_lang(" ".join(texts)) == "zh"
    out = texts[0]
    for t in texts[1:]:
        if _TERMINAL.search(out):
            out += t if zh else " " + t
        else:
            out += ("；" if zh else "; ") + t
    return out


# Official rendering: statements are grouped by their `kind` in first-progress-note order and numbered one per line.
# Unknown kinds (e.g. v2 output) inherit the previous statement's group, so older prompts render in their own order.
_GROUPS = {
    "case_features": (("summary", None, None), ("symptoms", None, None), ("history", None, None),
                      ("exam", None, None), ("tests", None, None), ("missing", None, None)),
    "diagnostic_discussion": (("assessment", "初步诊断及依据", "Working diagnoses"), ("differential", "鉴别诊断", "Differential diagnosis"),
                              ("uncertainty", "待明确问题", "Open questions")),
    "treatment_plan": (("investigation", "检查", "Investigations"), ("treatment", "处理", "Management"),
                       ("monitoring", "观察", "Monitoring")),
}
_CITE_KINDS = {"assessment"}     # rubric: each working diagnosis points at its record, e.g. "贫血待查（Hb 82 g/L，见S03）"


def render_official(stmts: list[Statement], section: str, rid=lambda i: i) -> str:
    groups = _GROUPS[section]
    order = [g[0] for g in groups]
    items: list = []                            # [group kind, line text, sources]
    current = None
    for s in stmts:
        text = s.text.strip()
        if not text:
            continue
        k = (s.kind or "").strip().lower()
        k = k if k in order else (current or None)
        if s.cont and items:
            items[-1][1] += text
            continue
        items.append([k, text, s.sources])
        current = k
    if not items:
        return ""
    for it in items:
        if it[0] in _CITE_KINDS and it[2]:
            ids = "、".join(dict.fromkeys(rid(i) for i in it[2]))
            body = re.sub(r"[。.]$", "", it[1])
            it[1] = body + (f"（见{ids}）。" if detect_lang(body) == "zh" else f" (see {ids}).")
    items = [(k, text) for k, text, _ in items]
    zh = detect_lang(" ".join(t for _, t in items)) == "zh"
    rank = {k: n for n, k in enumerate(order)}
    items.sort(key=lambda it: rank.get(it[0], -1))   # stable; ungrouped leading items stay first
    lines, last = [], object()
    n = 0
    for k, text in items:
        if k != last:
            head = next((g[1] if zh else g[2] for g in groups if g[0] == k), None)
            if head:
                lines.append(head + ("：" if zh else ":"))
                n = 0
            last = k
        n += 1
        lines.append(f"{n}. {text}")
    return "\n".join(lines)


_REVIEW_PREFIX = {"zh": {"missing": "【缺失】", "conflict": "【冲突】", "verify": "【待确认】"},
                  "en": {"missing": "[Missing] ", "conflict": "[Conflict] ", "verify": "[Confirm] "}}


def _review_text(r: dict) -> str:
    text = (r.get("clinician") or r["description"]).strip()
    if text.startswith(("【", "[")):
        return text
    lang = "zh" if detect_lang(text) == "zh" else "en"
    return _REVIEW_PREFIX[lang].get(r.get("type", "verify"), _REVIEW_PREFIX[lang]["verify"]) + text


def to_record(note: Note, case, cfg, meta: dict | None = None) -> dict:
    """Serialise to the output contract. Field names/selection are configurable (official schema TBC)."""
    rid = case.raw_id
    rec = {"case_id": case.case_id}
    for sec in SECTIONS:
        rec[sec] = render_prose(note.sections[sec], cfg.inline_citations)
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


def to_official_record(note: Note, case, meta: dict | None = None, status: str = "success",
                       error: dict | None = None) -> dict:
    """Serialise to the provider's official output protocol.

    Top level: {case_id, status, medical_record, error}. On failure medical_record is null and
    error is {code, message}. On success medical_record holds case_features / diagnostic_discussion /
    plan / evidence[{statement, source_ids, kind}] / review_items[str]. Evidence is capped at 3-5
    entries (the spec's recommended range); review_items are plain strings.
    """
    rid = case.raw_id
    if status != "success":
        return {
            "case_id": case.case_id,
            "status": "failed",
            "medical_record": None,
            "error": {"code": str((error or {}).get("code", "GENERATION_ERROR")),
                      "message": str((error or {}).get("message", "generation failed"))},
        }
    sections = {sec: render_official(note.sections[sec], sec, rid) for sec in SECTIONS}

    def _kind(sec: str, basis: str) -> str:
        """Official 'fact' = content stated in the records; 'inference' = reasoning over them.
        Case features are record facts; every discussion/plan entry is clinical reasoning (judgement,
        differential, uncertainty, plan) regardless of the model's often-unreliable 'basis' tag. The
        rubric's own example marks the diagnostic-boundary statement in discussion as inference."""
        return "fact" if sec == "case_features" else "inference"

    # evidence: derive from statements carrying source ids, map section + basis -> kind, cap to 3-5.
    candidates = []
    for sec in SECTIONS:
        for s in note.sections[sec]:
            if not s.sources or s.cont:       # a split continuation is a sentence fragment, not a checkable claim
                continue
            candidates.append({"statement": s.text, "source_ids": [rid(i) for i in s.sources],
                               "kind": _kind(sec, s.basis), "_k": (s.kind or "").lower()})
    candidates += [{"statement": e["statement"], "source_ids": [rid(i) for i in e["source_ids"]],
                    "kind": _kind(e.get("section", ""), e.get("basis", "")), "_k": ""}
                   for e in note.extra_evidence if e["source_ids"]]
    evidence = [{k: v for k, v in e.items() if k != "_k"} for e in _select_evidence(candidates)]
    review = [_review_text(r) for r in note.review_items
              if r.get("description")
              and (r.get("origin", "model") not in OFFICIAL_REVIEW_EXCLUDE or r.get("official_visible"))][:6]
    return {
        "case_id": case.case_id,
        "status": "success",
        "medical_record": {
            "case_features": sections["case_features"],
            "diagnostic_discussion": sections["diagnostic_discussion"],
            "plan": sections["treatment_plan"],
            "evidence": evidence,
            "review_items": review,
        },
        "error": None,
    }


def _select_evidence(candidates: list[dict], low: int = 3, high: int = 5) -> list[dict]:
    """Keep 3-5 evidence entries. Cover distinct sources and reserve at least one `inference` when
    the note contains one, so the official 'fact vs inference' distinction is actually represented."""
    if not candidates:
        return []
    facts = [e for e in candidates if e["kind"] == "fact"]
    infers = [e for e in candidates if e["kind"] == "inference"]

    def distinct(items):
        out, seen = [], set()
        for e in items:
            key = tuple(e["source_ids"])
            if key not in seen:
                seen.add(key)
                out.append(e)
        return out

    # facts: key findings first (values before prose, few sources before many), summary and "not documented" lines last
    facts = sorted(facts, key=lambda e: (e.get("_k") in ("summary", "missing"), len(e["source_ids"]) > 3,
                                         not re.search(r"\d", e["statement"])))
    facts_d, infers_d = distinct(facts), distinct(infers)
    by_kind = lambda k: [e for e in infers_d if e.get("_k") == k]
    main = (by_kind("assessment") or infers_d)[:1]                       # the working diagnosis and its basis
    boundary = [e for e in (by_kind("uncertainty") + by_kind("differential"))[:1] if e not in main]   # inference boundary
    picked: list[dict] = list(main)
    for e in facts_d:                                    # then facts across distinct sources
        if len(picked) >= high - len(boundary):
            break
        if e not in picked:
            picked.append(e)
    picked += boundary
    for e in facts + infers:                             # fill from all remaining to reach `low`
        if len(picked) >= min(low, len(candidates)):
            break
        if e not in picked:
            picked.append(e)
    for e in infers_d + facts_d:                         # top up toward `high` with distinct entries
        if len(picked) >= high:
            break
        if e not in picked:
            picked.append(e)
    return picked[:high]


OFFICIAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["case_id", "status", "medical_record", "error"],
    "properties": {
        "case_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "status": {"enum": ["success", "failed"]},
        "medical_record": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["case_features", "diagnostic_discussion", "plan", "evidence", "review_items"],
            "properties": {
                "case_features": {"type": "string", "minLength": 1, "pattern": r"\S"},
                "diagnostic_discussion": {"type": "string", "minLength": 1, "pattern": r"\S"},
                "plan": {"type": "string", "minLength": 1, "pattern": r"\S"},
                "evidence": {"type": "array", "maxItems": 5, "items": {   # 3-5 recommended; fewer (even 0) listed as-is per spec
                    "type": "object", "additionalProperties": False, "required": ["statement", "source_ids", "kind"],
                    "properties": {"statement": {"type": "string", "minLength": 1, "pattern": r"\S"},
                                   "source_ids": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1, "pattern": r"\S"}},
                                   "kind": {"enum": ["fact", "inference"]}}}},
                "review_items": {"type": "array", "items": {"type": "string", "minLength": 1, "pattern": r"\S"}},
            },
        },
        "error": {"type": ["object", "null"], "additionalProperties": False, "required": ["code", "message"],
                  "properties": {k: {"type": "string", "minLength": 1, "pattern": r"\S"} for k in ("code", "message")}},
    },
    "allOf": [{"if": {"properties": {"status": {"const": "success"}}},
               "then": {"properties": {"medical_record": {"type": "object"}, "error": {"type": "null"}}},
               "else": {"properties": {"medical_record": {"type": "null"}, "error": {"type": "object"}}}}],
}


def official_schema_errors(rec: dict, valid_ids: set[str] | None = None) -> list[str]:
    """Validate structure, success/failure consistency and case-local references without optional dependencies."""
    nonempty = lambda v: isinstance(v, str) and bool(v.strip())
    if not isinstance(rec, dict):
        return ["record must be an object"]
    errs = []
    if set(rec) != set(OFFICIAL_SCHEMA["required"]):
        errs.append("record must contain exactly case_id, status, medical_record, error")
    if not nonempty(rec.get("case_id")):
        errs.append("case_id must be a non-empty string")
    status, mr, error = rec.get("status"), rec.get("medical_record"), rec.get("error")
    if status == "failed":
        if mr is not None:
            errs.append("medical_record must be null on failure")
        if not isinstance(error, dict) or set(error) != {"code", "message"} or not all(nonempty(error[k]) for k in error):
            errs.append("failure requires error.code and error.message strings")
        return errs
    if status != "success":
        return errs + ["bad status"]
    if error is not None:
        errs.append("error must be null on success")
    if not isinstance(mr, dict):
        return errs + ["medical_record must be an object on success"]
    if set(mr) != {"case_features", "diagnostic_discussion", "plan", "evidence", "review_items"}:
        errs.append("medical_record must contain exactly the five official fields")
    for key in ("case_features", "diagnostic_discussion", "plan"):
        if not nonempty(mr.get(key)):
            errs.append(f"{key} must be a non-empty string")
    reviews = mr.get("review_items")
    if not isinstance(reviews, list) or any(not nonempty(r) for r in reviews):
        errs.append("review_items must be an array of non-empty strings")
    evidence = mr.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > 5:
        return errs + ["evidence must be an array of at most five entries"]
    if valid_ids and not evidence:
        errs.append("generated record has no traceable evidence")
    for e in evidence:
        if not isinstance(e, dict) or set(e) != {"statement", "source_ids", "kind"}:
            errs.append("bad evidence entry")
            continue
        if not nonempty(e["statement"]) or e["kind"] not in ("fact", "inference"):
            errs.append("bad evidence statement/kind")
        ids = e["source_ids"]
        if not isinstance(ids, list) or not ids or any(not nonempty(s) for s in ids):
            errs.append("evidence source_ids must be a non-empty array of strings")
        elif valid_ids is not None and any(s not in valid_ids for s in ids):
            errs.append("evidence cites a source outside the current case")
    return errs


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
