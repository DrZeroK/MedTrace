"""Module E1 - deterministic verification.

Checks generated statements against the fact ledger. Findings are *flags*: the only
automatic edits are provably safe ones (dropping source ids that do not exist).
Clinical wording is never rewritten by rule; unresolved findings are either sent back
to the model as a targeted repair request or surfaced to the clinician as review items.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from . import textutil as T
from .knowledge import approved_quote
from .inputs import Case
from .ledger import Ledger, numerics
from .note import Note, Statement, SECTIONS

import re

HIGH, MEDIUM, LOW = "high", "medium", "low"
# Only allergy: on real output, "anticoagulant use not recorded" (true) was flagged because *some* medication was
# documented, and "admission vitals not recorded" (true) because a home temperature was. Sub-item claims cannot be
# judged by keyword; allergy status is the one core item where a false "not documented" is both checkable and dangerous.
_CORE_DOC = {"allergy": re.compile(r"(?i)allerg|过敏")}
_SITE_DEPENDENT = set("扩张 肿大 压痛 增厚 异常 强化 积液 结节 占位 肿物 包块 肿块 水肿 出血 狭窄 梗阻 充血 渗出 增大 缩小 畸形 触痛 叩痛 "
                      "叩击痛 红肿 溃疡 糜烂 杂音 啰音 疼痛 肿胀 破溃 改变 病变 转移 复发 钙化 坏死 swelling tenderness mass lesion".split())
# Record section headers, not clinical findings: a header on its own line ("个人史\n无特殊") is split from its
# negation, so "个人史无特殊" must not be read as negating a positive finding. Section summaries are reviewer judgement.
_SECTION_TERMS = {"个人", "个人史", "既往", "既往史", "家族", "家族史", "体格检查", "检查检验", "辅助检查", "专科检查", "婚育史", "月经史", "月经婚育史"}
# Leading document-structure labels ("实验室检查：钾3.7") are formatting, not clinical content: they add
# out-of-vocabulary bigrams that depressed lexical support and caused low_support false alarms. Strip only
# a colon-suffixed, known section label at the very start; measurement labels such as "血压：…" are kept.
_LABEL_PREFIX = re.compile(r"^\s*(?:实验室检查|检查检验|体格检查|辅助检查|专科检查|生命体征|既往史|现病史|个人史|家族史|"
                           r"实验室|检验|检查|查体|病史|主诉|辅助|影像|心电图|一般情况|"
                           r"history|physical exam|examination|vitals?|laboratory|labs?|investigations)\s*[：:]\s*", re.I)
_TEST_NAME = re.compile(r"(?i)^(?:毒)?(?:病毒)?(?:标志物|抗体|抗原|指标|检测|筛查|系列|全套|谱|dna|rna)")
_GENERIC_LABEL = re.compile(r"(?i)约|大小|直径|范围|长|宽|厚|高|共|为|右眼|左眼|双眼|左侧|右侧|about|approx|size|measur")   # "大小约 2.5cm" / "右眼" name no analyte
_SAYS_ABSENT = re.compile(r"(?i)not (?:documented|recorded|available)|undocumented|未记录|未提及|未记载|未提供|不详")
_META_COMMENT = re.compile(r"(?i)not (?:be )?(?:assumed|considered|taken as|read as|interpreted)"
                           r"|(?:不能|不可|不应|不得)(?:视为|认为|当作|作为)|(?:须|需|应|必须|请)(?:予以)?(?:核实|确认|复查)")
_SHORT = {"case_features": "features", "diagnostic_discussion": "discussion", "treatment_plan": "plan"}


def _assertive_text(text: str) -> tuple[str, str]:
    """(checked content, positive view) for a statement. Clauses reporting information as missing/pending, and
    clauses telling the reader how to treat such information, are statements about the record, not findings:
    they are dropped before the negation and grounding checks. Sentences with nothing to drop are used verbatim,
    so negation scope across commas ("Denies chest pain, hemoptysis.") is unchanged."""
    asserted, positive = [], []
    for sent in T.split_sentences(text):
        clauses = re.split(r"[，,]", sent)
        kept = [c.strip() for c in clauses if c.strip() and not T.has_missing_cue(c) and not _META_COMMENT.search(c)]
        kept = sent if len(kept) == len([c for c in clauses if c.strip()]) else "，".join(kept)
        if kept.strip():
            asserted.append(kept)
            positive.append(T.clearly_positive_text(kept))
    return "\n".join(asserted), "\n".join(positive)


@dataclass
class Finding:
    code: str
    severity: str
    section: str
    index: int
    message: str
    text: str = ""

    def as_dict(self):
        return asdict(self)


def check_statement(section: str, index: int, st: Statement, case: Case, L: Ledger) -> list[Finding]:
    out: list[Finding] = []
    sec = _SHORT[section]
    text = st.text
    low = text.lower()
    add = lambda code, sev, msg: out.append(Finding(code, sev, section, index, msg, text))
    year = case.cutoff.year if case.cutoff else None

    # ---- evidence references
    bad = [s for s in st.sources if s not in case.valid_ids]
    if bad:
        add("invalid_ref", HIGH, f"cites source id(s) that do not exist: {bad}")
    if sec == "features" and not st.sources:
        add("missing_ref", LOW, "case-feature statement has no source reference")

    # ---- chronology
    for dt, has_time, _, _ in T.find_dates(text, year):
        if sec != "plan" and T.is_after(dt, has_time, case.cutoff):
            add("post_cutoff", HIGH, f"refers to {dt:%Y-%m-%d %H:%M}, later than the record cutoff")
        elif sec == "features" and dt.date() not in L.dates:
            add("date_not_in_source", MEDIUM, f"date {dt:%Y-%m-%d} does not appear in the records")

    quoted_knowledge = sec != "features" and approved_quote(st, L.knowledge_cards)
    if L.knowledge_enabled:
        if any(k not in L.knowledge_cards for k in st.knowledge_ids):
            add("invalid_knowledge_ref", MEDIUM, "knowledge reference was not supplied for this case")
        if sec == "features" and st.knowledge_ids:
            add("knowledge_in_features", HIGH, "knowledge cannot establish patient facts")
        if st.basis == "knowledge" and not st.knowledge_ids:
            add("missing_knowledge_ref", MEDIUM, "knowledge statement has no knowledge citation")
        if st.basis == "knowledge" and T.extract_numbers(text) and not quoted_knowledge:
            add("unverified_knowledge_number", MEDIUM, "numeric knowledge must quote an approved supplied card exactly")

    # ---- numbers and units
    if sec in ("features", "discussion") and not quoted_knowledge:
        for val, unit, raw in T.extract_numbers(T.mask_dates(text, year or 2000)):
            if sec == "discussion" and unit is None:
                continue      # reasoning text legitimately carries knowledge numbers (ages, scores, "24小时尿", "11β-…");
                              # only unit-bearing values are checked there
            if val not in L.numbers:
                add("number_not_in_source", HIGH if sec == "features" else MEDIUM,
                    f"value {raw!r} does not appear in the records")
            elif unit and L.units.get(val) and unit not in L.units[val]:
                add("unit_mismatch", HIGH if sec == "features" else MEDIUM,
                    f"{raw!r}: records give this value with unit(s) {sorted(L.units[val])}")

    # ---- a knowledge statement must not carry patient-specific values from the records
    if st.basis == "knowledge" and sec in ("discussion", "plan") and not quoted_knowledge:
        for val, unit, raw in T.extract_numbers(T.mask_dates(text, year or 2000)):
            if val in L.numbers:
                add("knowledge_record_value", MEDIUM,
                    f"knowledge statement carries {raw!r}, a value found in the patient's records")
                break

    # ---- value attached to the wrong measurement (e.g. sodium's value reported as potassium)
    if sec == "features":
        for num in numerics(text, year):
            known = L.label_values.get(num["label"])
            # Only flag an unambiguous swap: this label has a single recorded value, and the stated value is
            # positively recorded under a DIFFERENT single-valued analyte. Serial results (one label, many values
            # over time) and analyte aliases cannot be disambiguated by rule, so they are left to the reviewer.
            if (known and len(known) == 1 and not _GENERIC_LABEL.search(num["label"])
                    and num["value"] not in known and num["value"] in L.numbers):
                other = any(len(v) == 1 and num["value"] in v for lab, v in L.label_values.items()
                            if lab != num["label"] and not _GENERIC_LABEL.search(lab))
                if other:
                    add("value_label_mismatch", HIGH,
                        f"{num['raw']!r}: the records give {num['label']!r} as {sorted(known)}; this value belongs to another item")

    # ---- negation
    # A clause that reports something as not documented / pending is a statement ABOUT the record, not a
    # negative finding: it is exempt from the negation and grounding checks. The rest of the statement is still
    # checked, so a pending item cannot shield a clinical assertion in the same statement. (Seen on the first
    # real-model run: "资料中未记录生命体征、药物过敏史" was flagged as an undocumented negative.)
    meta_missing = sec == "features" and T.has_missing_cue(text)
    if sec == "features":
        checked, pos = _assertive_text(text)
    else:
        checked = text
        pos = "\n".join(T.clearly_positive_text(s) for s in T.split_sentences(text))
    enhanced = L.context_mode == "zh_context_v1" and T.detect_lang(checked) == "zh"
    if enhanced:
        from . import context as C
        pos = C.positive_text(checked)
    if sec in ("features", "discussion") and checked.strip():
        for term in sorted(L.neg_only):      # sorted: set order varies per process (PYTHONHASHSEED)
            if term in _SITE_DEPENDENT or term in _SECTION_TERMS or len(term) < 2:
                continue
            i = pos.find(term)
            # "否认肝炎病史" is not contradicted by "肝炎病毒标志物": skip the term inside a test name
            if i >= 0 and not _TEST_NAME.match(pos[i + len(term):]):
                add("negation_flip", HIGH if sec == "features" else LOW,
                    f"records document {term!r} only as absent/denied, but it is stated here without negation")
    # What a missing-information statement must not do is claim a core item is undocumented when the records
    # do document it.
    if meta_missing and T.support(text, L.tokens_all) < 0.9:      # >= 0.9: the records' own sentence, quoted (e.g. "具体用药不详")
        clauses = re.split(r"[，,；;。.！？\n]", text)
        for key, rx in _CORE_DOC.items():
            if key not in {u["key"] for u in L.undocumented} and any(rx.search(c) and _SAYS_ABSENT.search(c) for c in clauses):
                add("false_missing", HIGH, f"states that {key} information is not documented, but the records contain it")
    if sec == "features" and checked.strip():
        for term in (C.negated_terms(checked) if enhanced else T.negated_terms(checked)):
            if term in L.neg_terms:
                continue
            if term in _SITE_DEPENDENT or term in _SECTION_TERMS:
                continue        # "无扩张" at one site does not contradict "扩张" at another; section headers are not findings
            if term in L.clear_pos_text:
                add("negation_flip", HIGH, f"{term!r} is negated here but the records document it as present")
            elif term in L.pos_text:
                continue        # the records mention it after a negation cue: ambiguous, not flagged
            elif term not in L.all_text:
                add("undocumented_negative", MEDIUM, f"{term!r} is stated as absent but is not mentioned in the records")
    if enhanced and sec == "features":
        for code, term in C.context_conflicts(checked, L.facts):
            add(code, MEDIUM, f"{term!r}: assertion/person/time differs from the source context; review required")

    # ---- lexical grounding of case features
    if sec == "features" and checked.strip():
        cited = set().union(*[L.tokens_by_source.get(s, set()) for s in st.sources]) if st.sources else set()
        grounded = _LABEL_PREFIX.sub("", checked)   # ignore document-structure labels when scoring support
        s_all = T.support(grounded, L.tokens_all)
        thr = 0.35 if T.detect_lang(checked) == "zh" else 0.5
        if T.has_normal_cue(checked) and s_all < thr + 0.15:
            add("undocumented_normal", MEDIUM, "states a normal finding that is weakly supported by the records")
        elif s_all < thr:
            add("low_support", MEDIUM, f"statement content is weakly supported by the records (overlap {s_all:.2f})")
        elif cited and T.support(grounded, cited) < s_all - 0.3:
            add("weak_attribution", LOW, "the cited source supports this statement less well than other sources")

    # ---- proposed vs completed
    if sec == "plan":
        for clause in re.split(r"[；;。！？\n]", text):
            if T.has_done_cue(clause) and T.support(clause, L.tokens_all) < 0.5:
                add("unsupported_completed", HIGH, "plan describes an intervention as already done, without support in the records")
                break

    # ---- diagnostic certainty
    if sec == "discussion" and T.has_certain_cue(text) and not T.has_certain_cue(L.all_text):
        add("overconfident", LOW, "uses definitive diagnostic wording not present in the records")
    return out


def verify_note(note: Note, case: Case, L: Ledger) -> list[Finding]:
    out: list[Finding] = []
    for sec in SECTIONS:
        stmts = note.sections[sec]
        if not stmts:
            out.append(Finding("empty_section", HIGH, sec, -1, f"section {sec} is empty"))
        for i, st in enumerate(stmts):
            out.extend(check_statement(sec, i, st, case, L))
    for j, e in enumerate(note.extra_evidence):
        bad = [s for s in e["source_ids"] if s not in case.valid_ids]
        if bad:
            out.append(Finding("invalid_ref", HIGH, "evidence", j, f"evidence item cites unknown source id(s): {bad}", e["statement"]))
    for j, r in enumerate(note.review_items):
        bad = [s for s in r.get("source_ids", []) if s not in case.valid_ids]
        if bad:
            out.append(Finding("invalid_ref", MEDIUM, "review_items", j, f"review item cites unknown source id(s): {bad}", r["description"]))
    return out


def omission_findings(note: Note, L: Ledger) -> list[Finding]:
    """Safety-critical record content that the note does not reflect anywhere: documented allergies and
    results recorded as pending / not done. (General completeness is a reviewer judgement, not a rule.)"""
    note_tokens = T.tokens(note.text() + "\n" + "\n".join(r["description"] for r in note.review_items))
    out = []
    for f in L.facts:
        if f.category != "allergy" and f.polarity != "missing":
            continue
        thr = 0.35 if T.detect_lang(f.text) == "zh" else 0.5
        if T.support(f.text, note_tokens) < thr:
            what = "allergy information" if f.category == "allergy" else "a pending / not-done item"
            out.append(Finding("omitted_critical", MEDIUM, "case_features", -1, f"the records state {what} that the note does not mention", f.text))
    return out[:6]


def measurement_coverage(note: Note, L: Ledger) -> tuple[int, int]:
    """(unit-bearing record measurements whose value appears in the note, total). A proxy metric, not a finding."""
    vals = {n["value"] for f in L.facts for n in f.numerics}
    present = T.all_number_values(note.text())
    return len(vals & present), len(vals)


def safe_repair(note: Note, case: Case) -> int:
    """Provably safe edits only: remove references to source ids that do not exist. Returns #removed."""
    removed = 0
    valid = case.valid_ids
    for sec in SECTIONS:
        for st in note.sections[sec]:
            keep = [s for s in st.sources if s in valid]
            removed += len(st.sources) - len(keep)
            st.sources = keep
    for e in note.extra_evidence:
        keep = [s for s in e["source_ids"] if s in valid]
        removed += len(e["source_ids"]) - len(keep)
        e["source_ids"] = keep
    note.extra_evidence = [e for e in note.extra_evidence if e["source_ids"]]
    for r in note.review_items:
        keep = [s for s in r.get("source_ids", []) if s in valid]
        removed += len(r.get("source_ids", [])) - len(keep)
        r["source_ids"] = keep
    return removed


def counts(findings: list[Finding]) -> dict:
    c = {HIGH: 0, MEDIUM: 0, LOW: 0}
    for f in findings:
        c[f.severity] += 1
    return c
