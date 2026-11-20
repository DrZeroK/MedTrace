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
_SECTION_TERMS = {"个人", "个人史", "既往", "既往史", "家族", "家族史", "体格检查", "检查检验", "辅助检查", "专科检查", "婚育史", "月经史", "月经婚育史",
                  "疾病", "病史", "其他", "其它", "不适", "特殊"}   # generic list words ("否认疾病、手术史") name no finding
# Leading document-structure labels ("实验室检查：钾3.7") are formatting, not clinical content: they add
# out-of-vocabulary bigrams that depressed lexical support and caused low_support false alarms. Strip only
# a colon-suffixed, known section label at the very start; measurement labels such as "血压：…" are kept.
_LABEL_PREFIX = re.compile(r"^\s*(?:实验室检查|检查检验|体格检查|辅助检查|专科检查|生命体征|既往史|现病史|个人史|家族史|"
                           r"实验室|检验|检查|查体|病史|主诉|辅助|影像|心电图|一般情况|"
                           r"history|physical exam|examination|vitals?|laboratory|labs?|investigations)\s*[：:]\s*", re.I)
_TEST_NAME = re.compile(r"(?i)^(?:毒)?(?:病毒)?(?:标志物|抗体|抗原|指标|检测|筛查|系列|全套|谱|dna|rna)")
# A negated term that names a test panel or score ("肝炎病毒标志物均阴性") reports a result set, not a condition; the
# records name it as a label ("肝炎病毒标志物：乙肝表面抗原阴性…"). It is checked only for being documented at all.
_TEST_TERM = re.compile(r"(?i)(?:标志物|抗体|抗原|指标|检测|筛查|系列|全套|评分|检查|dna|rna)$")
# A collective test name whose results follow it ("肝炎病毒标志物：乙肝表面抗原阴性，丙肝抗体阴性").
_PANEL_TERM = re.compile(r"(?i)(?:标志物|指标|系列|全套|筛查|检测|检查|[三四五六七八]项)$")
# Result words, negative alternatives first so "未见异常"/"未检出" win over the "异常"/"检出" inside them.
_RESULT = re.compile(r"(?P<neg>阴性|[（(][-－—][）)]|未见异常|无异常|未检出|正常)"
                     r"|(?P<pos>阳性|[（(][+＋]+[）)]|升高|增高|偏高|降低|减低|偏低|异常|检出)")


def _documented_results(variants: set, term_norm: str, L: Ledger) -> set:
    """{'neg', 'pos'}: the results the records give for this test. An individual test takes the result word right
    after its name; a panel takes every result in the rest of the sentence, so one positive member counts."""
    states = set()
    panel = bool(_PANEL_TERM.search(term_norm))
    for f in L.facts:
        s = T.squash(f.text)
        for v in variants:
            i = s.find(v)
            while i >= 0:
                after = s[i + len(v):]
                if after[:1] in ("+", "＋"):
                    states.add("pos")
                else:
                    near = _RESULT.search(after[:8])
                    if near:
                        states.add(near.lastgroup)
                    if panel or not near:
                        states.update(m.lastgroup for m in _RESULT.finditer(after))
                i = s.find(v, i + 1)
    return states
_GENERIC_LABEL = re.compile(r"(?i)约|大小|直径|范围|长|宽|厚|高|共|为|右眼|左眼|双眼|左侧|右侧|about|approx|size|measur")   # "大小约 2.5cm" / "右眼" name no analyte
_SAYS_ABSENT = re.compile(r"(?i)not (?:documented|recorded|available)|undocumented|未记录|未提及|未记载|未提供|不详")
_META_COMMENT = re.compile(r"(?i)not (?:be )?(?:assumed|considered|taken as|read as|interpreted)"
                           r"|(?:不能|不可|不应|不得)(?:视为|认为|当作|作为)|(?:须|需|应|必须|请)(?:予以)?(?:核实|确认|复查)")
_SHORT = {"case_features": "features", "diagnostic_discussion": "discussion", "treatment_plan": "plan"}
# "A→B" / "由A降至B" with a direction word in the same clause; ranges ("4.8-5.3") use "-" and are not matched
_TREND = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[^\d，,；;。]{0,8}?(?:→|->|—>|降至|升至|增至|减至|至|到)\s*(\d+(?:\.\d+)?)")
_UP = re.compile(r"升高|上升|增高|增加|加重|升至|增至|进行性增|(?i:\b(?:rising|rose|increas\w*|worsen\w*)\b)")
_DOWN = re.compile(r"下降|降低|减低|减少|好转|回落|降至|减至|(?i:\b(?:fell|falling|decreas\w*|declin\w*|improv\w*)\b)")


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
    term: str = ""          # the clinical term concerned, when there is one (clinician-facing wording, dedupe)

    def as_dict(self):
        return asdict(self)


def check_statement(section: str, index: int, st: Statement, case: Case, L: Ledger) -> list[Finding]:
    out: list[Finding] = []
    sec = _SHORT[section]
    text = st.text
    low = text.lower()
    add = lambda code, sev, msg, term="": out.append(Finding(code, sev, section, index, msg, text, term))
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
    if any(k not in L.knowledge_cards for k in st.knowledge_ids):
        add("invalid_knowledge_ref", MEDIUM, "knowledge reference was not supplied for this case")
    if sec == "features" and st.knowledge_ids:
        add("knowledge_in_features", HIGH, "knowledge cannot establish patient facts")
    if L.knowledge_cards:
        if st.basis == "knowledge" and not st.knowledge_ids:
            add("missing_knowledge_ref", MEDIUM, "knowledge statement has no knowledge citation")
        if st.basis == "knowledge" and T.extract_numbers(text) and not quoted_knowledge:
            add("unverified_knowledge_number", MEDIUM, "numeric knowledge must quote an approved supplied card exactly")

    if L.context_mode == "zh_context_v1" and sec in ("features", "discussion") and st.basis != "knowledge":
        from .evidence_status import unsupported_claims
        for code, reason in unsupported_claims(text, L.facts):
            add(code, MEDIUM, reason)

    # ---- numbers and units
    if sec in ("features", "discussion") and not quoted_knowledge:
        for val, unit, raw in T.extract_numbers(T.mask_dates(text, year or 2000)):
            if sec == "discussion" and unit is None:
                continue      # reasoning text legitimately carries knowledge numbers (ages, scores, "24小时尿", "11β-…");
                              # only unit-bearing values are checked there
            if val not in L.numbers:
                add("number_not_in_source", HIGH if sec == "features" else MEDIUM,
                    f"value {raw!r} does not appear in the records", raw)
            elif unit and L.units.get(val) and unit not in L.units[val]:
                add("unit_mismatch", HIGH if sec == "features" else MEDIUM,
                    f"{raw!r}: records give this value with unit(s) {sorted(L.units[val])}", raw)

    # ---- a trend word that contradicts the quoted values ("TBA 持续升高（14.2→11.8μmol/L）")
    if sec in ("features", "discussion"):
        for clause in re.split(r"[，,；;。！？\n]", T.mask_dates(text, year or 2000)):
            m = _TREND.search(clause)
            if not m:
                continue
            a, b = float(m.group(1)), float(m.group(2))
            up, down = bool(_UP.search(clause)), bool(_DOWN.search(clause))
            if a != b and up != down and (up and b < a or down and b > a):
                add("trend_direction", HIGH, f"{m.group(0)!r}: the stated direction contradicts the values", m.group(0).strip())

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
            # "否认肝炎病史" is not contradicted by "肝炎病毒标志物" (a test name) or "非手术患者" (a risk group)
            if i >= 0 and not _TEST_NAME.match(pos[i + len(term):]) and not pos[:i].endswith("非"):
                add("negation_flip", HIGH if sec == "features" else LOW,
                    f"records document {term!r} only as absent/denied, but it is stated here without negation", term)
    # What a missing-information statement must not do is claim a core item is undocumented when the records
    # do document it.
    if meta_missing and T.support(text, L.tokens_all) < 0.9:      # >= 0.9: the records' own sentence, quoted (e.g. "具体用药不详")
        clauses = re.split(r"[，,；;。.！？\n]", text)
        for key, rx in _CORE_DOC.items():
            if key not in {u["key"] for u in L.undocumented} and any(rx.search(c) and _SAYS_ABSENT.search(c) for c in clauses):
                add("false_missing", HIGH, f"states that {key} information is not documented, but the records contain it")
    if sec == "features" and checked.strip():
        for term in (C.negated_terms(checked) if enhanced else T.negated_terms(checked)):
            term_norm = T.squash(term)
            variants = T.term_variants(term_norm)
            if variants & L.neg_terms_norm or any(T.concat_of(v, L.neg_terms_norm) for v in variants):
                continue        # documented negative, possibly abbreviated or coordinated ("吸烟饮酒" = 吸烟 + 饮酒)
            if _TEST_TERM.search(term_norm) and _documented_results(variants, term_norm, L) == {"neg"}:
                continue        # the records give only negative results for this test or panel
            if term in _SITE_DEPENDENT or term in _SECTION_TERMS:
                continue        # "无扩张" at one site does not contradict "扩张" at another; section headers are not findings
            if enhanced:
                source_states = [s for f in L.facts for s in C.term_attributes(f.text, term)]
                if source_states and all(s["assertion"] == "unknown" for s in source_states):
                    add("context_scope_ambiguous", MEDIUM, f"{term!r}: the source assertion scope is ambiguous; review required")
                    continue
            if any(v in L.clear_pos_text_norm for v in variants):
                add("negation_flip", HIGH, f"{term!r} is negated here but the records document it as present", term)
            elif any(v in L.pos_text_norm for v in variants):
                continue        # the records mention it after a negation cue: ambiguous, not flagged
            elif not any(v in L.all_text_norm for v in variants):
                add("undocumented_negative", MEDIUM, f"{term!r} is stated as absent but is not mentioned in the records", term)
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
        # scored on the comma-clause carrying the "已…" cue: reasoning after it ("…，需重新评估…") is not the action
        for clause in re.split(r"[，,；;。！？\n]", text):
            if T.has_done_cue(clause) and T.support(clause, L.tokens_all) < 0.5:
                add("unsupported_completed", HIGH, "plan describes an intervention as already done, without support in the records")
                break

    # ---- diagnostic certainty: only a definitive claim (not "不能确诊…", "需…确诊") about a diagnosis that the
    # records do not themselves list without qualification
    if sec == "discussion" and not T.has_certain_cue(L.all_text):
        heading = _subject(text)
        unsupported = [c for c in T.definitive_claims(text) if not _record_diagnosis(_claim_subject(c) or heading, L)]
        if unsupported:
            add("overconfident", MEDIUM, "uses definitive diagnostic wording not present in the records")
    if sec == "discussion" and index == 0 and is_copied_diagnosis_list(text, L):
        add("copied_diagnosis_list", MEDIUM, "discussion opens with a verbatim copy of the records' diagnosis list")
    return out


def _subject(text: str) -> str:
    """The diagnosis a discussion statement is about: its heading before the first colon, else its first clause."""
    return re.split(r"[：:，,。；;]", text, 1)[0]


# Words around a certainty cue that do not name a diagnosis ("支持诊断明确", "故诊断成立").
_CLAIM_FILLER = re.compile(r"支持|诊断|依据|结合|考虑|目前|本例|该病|此|已|可|基本|临床|即|为|成立|明确|确诊|确定|充分|可以|较|的|是|故|因此|综上")


def _claim_subject(claim: str) -> str:
    """The diagnosis a definitive clause names ("肺炎诊断明确" -> "肺炎"); "" when it names none ("支持诊断明确"),
    in which case the claim is about the statement's heading."""
    rest = _CLAIM_FILLER.sub("", T._CERTAIN.sub("", claim))
    rest = re.sub(r"[\s、，,；;。！？!?：:（）()\-]", "", rest)
    return rest if len(rest) >= 2 else ""


def _record_diagnosis(subject: str, L: Ledger) -> bool:
    """True if `subject` is one of the records' own diagnoses stated without uncertainty."""
    subj = T.tokens(subject)
    certain = set().union(*[T.tokens(dx) for dx in L.diagnoses if not T.has_uncertain_cue(dx)], set())
    # union over items: a heading may combine a listed diagnosis and its sub-item ("急性胃肠炎" + "轻-中度脱水")
    return bool(subj) and len(subj & certain) / len(subj) >= 0.6


_DX_COPY = re.compile(r"^\s*(?:初步|入院|门诊)?诊断\s*[：:]|^\s*\(?\d{1,2}[.)、．]")


def is_copied_diagnosis_list(text: str, L: Ledger) -> bool:
    """A discussion statement that reproduces the records' diagnosis list (header and/or enumerated items) instead of
    discussing it. Judged by bigram overlap with the list, so reasoning text that merely names a diagnosis is kept."""
    if not L.diagnoses or not _DX_COPY.search(text):
        return False
    body = re.sub(r"^\s*(?:初步|入院|门诊)?诊断\s*[：:]", "", text)
    if len(re.findall(r"(?<!\d)\d{1,2}[.)、．](?!\d)", body)) < 2 and not re.match(r"^\s*(?:初步|入院|门诊)?诊断", text):
        return False
    body = re.sub(r"(?<!\d)\d{1,2}[.)、．](?!\d)", " ", body)      # list numbers are not content tokens
    return T.support(body, T.tokens("\n".join(L.diagnoses))) >= 0.85


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


def drop_copied_diagnosis(note: Note, L: Ledger) -> int:
    """Remove a leading verbatim copy of the records' diagnosis list from the discussion ("初步诊断：1. …；2. …"),
    when real discussion follows. The removed text restates record content, not reasoning, so nothing clinical
    is lost; the diagnoses remain the subject of the statements that follow. Returns #statements removed."""
    stmts = note.sections["diagnostic_discussion"]
    if not stmts or not is_copied_diagnosis_list(stmts[0].text, L):
        return 0
    dx = T.tokens("\n".join(L.diagnoses))
    n = 1
    # list items keep going while they are bare restatements (enumeration may already be stripped); a headed
    # statement ("胃早期癌：依据…") is discussion and ends the run
    while (n < len(stmts) and not re.search(r"[：:]", T.strip_enum(stmts[n].text))
           and T.support(T.strip_enum(stmts[n].text), dx) >= 0.85):
        n += 1
    if n >= len(stmts):
        return 0                   # nothing else to keep: left to the copied_diagnosis_list finding
    note.sections["diagnostic_discussion"] = stmts[n:]
    return n


_SENT_END = re.compile(r"(?<=[。；;！？!?])")


def split_long_statements(note: Note, limit: int = 100) -> int:
    """Split statements longer than `limit` characters at sentence boundaries into consecutive statements with the
    same sources and labels. Wording is unchanged and prose rendering is identical; only statement (and evidence)
    granularity changes. A single sentence over the limit stays whole. Returns #statements added."""
    added = 0
    for sec in SECTIONS:
        out = []
        for st in note.sections[sec]:
            parts = [x for x in _SENT_END.split(st.text) if x.strip()] if len(st.text) > limit else [st.text]
            chunks: list[str] = []
            for x in parts:
                if chunks and len(chunks[-1]) + len(x) <= limit:
                    chunks[-1] += x
                else:
                    chunks.append(x)
            out += [Statement(c.strip(), list(st.sources), st.kind, st.basis, list(st.knowledge_ids)) for c in chunks]
            added += len(chunks) - 1
        note.sections[sec] = out
    return added


def counts(findings: list[Finding]) -> dict:
    c = {HIGH: 0, MEDIUM: 0, LOW: 0}
    for f in findings:
        c[f.severity] += 1
    return c
