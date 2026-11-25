"""Module E1 - deterministic verification.

Checks generated statements against the fact ledger. Findings are *flags*: the only
automatic edits are provably safe ones (dropping source ids that do not exist).
Clinical wording is never rewritten by rule; unresolved findings are either sent back
to the model as a targeted repair request or surfaced to the clinician as review items.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, asdict

from . import aortic as A
from . import dosing as D
from . import textutil as T
from .knowledge import approved_quote
from .inputs import Case
from .ledger import Ledger, numerics
from .note import Note, Statement, SECTIONS, statement_groups

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
# Words that state a CHANGE in the number only. Clinical words (好转/加重/improved/worsened) are excluded: recovery
# can be a rise ("贫血好转（血红蛋白80→100g/L）") and worsening a fall. Bare 升高/增高/降低/减低/增加/减少 are excluded
# too: they usually state a level ("总胆汁酸升高（14.2→11.8）" = elevated on both dates; "血钾降低" = hypokalaemia).
_UP = re.compile(r"上升|升至|增至|(?:较前|进行性|逐渐)(?:上升|升高|增高|增加)|(?i:\b(?:ris(?:e|es|ing)|rose|increas\w*)\b)")
_DOWN = re.compile(r"下降|回落|降至|减至|(?:较前|进行性|逐渐)(?:下降|降低|减低|减少)|(?i:\b(?:fall(?:s|ing)?|fell|decreas\w*|declin\w*)\b)")
# a negated direction word ("未升高", "无明显下降", "did not rise") asserts no direction
_DIR_NEG = re.compile(r"(?:未|无|不|没有|并未|并无|否认)(?:明显|显著|进一步)?$|(?i:\b(?:not|no|without|never)\s+(?:\w+\s+)?)$")


def _direction(rx: re.Pattern, clause: str) -> bool:
    """True if `clause` asserts the direction `rx` names (some occurrence not under a negation)."""
    return any(not _DIR_NEG.search(clause[:m.start()]) for m in rx.finditer(clause))


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


def _negated_list_covers(term_norm: str, L: Ledger) -> bool:
    """"肾等重要脏器疾病" shortens the records' negated list "否认…肺、肾、内分泌系统等重要脏器疾病史": the head and the
    "等…" tail both sit, in order, inside one negated span of a record sentence. (Cloud practice run, P01.)"""
    head, sep, tail = term_norm.partition("等")
    if not (sep and head and tail):
        return False
    for f in L.facts:
        for s, e in T.neg_spans(f.text):
            span = T.squash(f.text[s:e])
            i = span.find(head)
            if i >= 0 and span.find("等" + tail, i + len(head)) >= 0:
                return True
    return False


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
            up, down = _direction(_UP, clause), _direction(_DOWN, clause)
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

    # ---- an allergy stated in the note that the records do not give
    recorded = None
    for frag in re.split(r"[，,；;。（）()]", text):
        if _ALLERGY_CUE.search(frag):
            recorded = recorded_allergies(case) if recorded is None else recorded
            term = unsupported_allergy(frag, recorded)
            if term:
                add("allergy_not_in_source", HIGH, f"states an allergy to {term!r} that the records do not document", term)

    # ---- qualifier attached to a value that the records give without it ("GLU 10.8" written as "空腹血糖10.8")
    if sec in ("features", "discussion") and st.basis != "knowledge":
        for _, _, qual, raw in unsupported_qualifiers(text, case):
            add("qualifier_not_in_source", HIGH if sec == "features" else MEDIUM,
                f"'{qual}' is not recorded with the value {raw!r} in the records", qual)

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
            elif not any(v in L.all_text_norm or T.covered_by(v, L.neg_terms_norm) or _negated_list_covers(v, L)
                         for v in variants):
                # covered_by: a reworded record negation; checked after the flip test so it cannot hide one
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
            if _unsupported_done(clause, L):
                add("unsupported_completed", HIGH, "plan describes an intervention as already done, without support in the records")
                break
        # ---- harm screen: a drug of a recorded allergy class; antithrombotic therapy despite recorded bleeding
        for drug, allergen in allergy_conflicts(text, recorded_allergies(case)):
            add("allergy_conflict", HIGH, f"plan gives {drug!r} although the records document an allergy to {allergen!r}", drug)
        # acute aortic syndrome screen (medtrace/aortic.py): a finding whenever the screen would rewrite generated text;
        # a real order copied from the records is kept and gets its review item from the pipeline instead
        if A.has_antithrombotic(text):
            ctx = _aortic_context(case)
            lang = "zh" if re.search(r"[一-鿿]", text) else "en"
            changed = [e for e in A.screen_text(text, case, lang, ctx)[1] if e.replacement != e.original_candidate]
            if changed:
                name = A.ENTITY_NAME["en"].get(changed[0].entity, "an acute aortic syndrome")
                add("aortic_antithrombotic", HIGH, f"antithrombotic suggestion conflicts with {name} ({ctx.state})",
                    A.ENTITY_NAME["zh"].get(changed[0].entity, "急性主动脉综合征"))
            elif not _SAFETY_CAUTION.search(text):
                # F5, deduplicated: an AAS the aortic screen already governs is not reported again as bleeding
                aas_live = ctx.state not in A.QUIET_STATES
                bleeding = [b for b in recorded_bleeding(case) if not (aas_live and b in _AAS_BLEEDING_TERMS)]
                if bleeding:
                    add("bleeding_risk", MEDIUM, f"antithrombotic therapy planned although the records document {bleeding[0]!r}",
                        bleeding[0])
        for d in D.dose_findings(text, "\n".join(s.content for s in case.sources)):
            add(d.code, HIGH, f"{d.drug} {d.per_dose_mg:g} mg x{d.times_per_day}/day ({d.daily_mg:g} mg/day; limit "
                f"{d.limit_mg:g}): {d.reason}", d.drug)

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


_QUALIFIER = re.compile(r"空腹|餐后|随机|持续|最高|最低|平均|峰值")


def unsupported_qualifiers(text: str, case: Case) -> list[tuple[int, int, str, str]]:
    """(start, end, qualifier, value) for each qualifier whose next value (same clause, within 10 characters) is
    recorded, but never with that qualifier in the 15 characters before it in the same clause. Values absent from
    the records are left to the number check."""
    t, src = T.fw(text), T.fw("\n".join(s.content for s in case.sources))
    out = []
    for m in _QUALIFIER.finditer(t):
        n = re.search(r"\d+(?:\.\d+)?", re.split(r"[，,。；;\n]", t[m.end():])[0])
        if not n or n.start() >= 10:   # whole value, starting within 10 characters ("0.61", not a truncated "0")
            continue
        hits = list(re.finditer(rf"(?<![\d.]){re.escape(n.group(0))}(?!\.?\d)", src))
        if hits and not any(m.group(0) in re.split(r"[。；;\n]", src[max(0, h.start() - 15):h.start()])[-1] for h in hits):
            out.append((m.start(), m.end(), m.group(0), n.group(0)))
    return out


def strip_unsupported_qualifiers(note: Note, case: Case) -> list[str]:
    """Delete a qualifier the records do not give with its value: "空腹血糖10.8" -> "血糖10.8". Removing it only
    weakens the claim back to what the records say. Returns the removed qualifiers."""
    removed = []
    for sec in ("case_features", "diagnostic_discussion"):
        for st in note.sections[sec]:
            if st.basis == "knowledge":
                continue
            for start, end, qual, _ in reversed(unsupported_qualifiers(st.text, case)):
                st.text = st.text[:start] + st.text[end:]
                removed.append(qual)
    return removed


# Drug classes for the allergy screen: (record terms that name the allergen, plan terms that would give it).
# Class level on purpose: an allergy to one penicillin rules out the others. Only drugs; foods and pollens are ignored.
_ALLERGY_CLASSES = {
    "penicillin": ("青霉素|阿莫西林|氨苄西林|哌拉西林|苯唑西林|(?i:penicillin|amoxicillin|ampicillin|piperacillin)",) * 2,
    "cephalosporin": ("头孢|(?i:cephalosporin|ceftriaxone|cefazolin|cefuroxime|ceftazidime|cefepime)",) * 2,
    "quinolone": ("沙星|喹诺酮|(?i:quinolone|levofloxacin|moxifloxacin|ciprofloxacin)",) * 2,
    "sulfonamide": ("磺胺|复方新诺明|(?i:sulfa|sulfamethoxazole|co-trimoxazole|TMP-SMX)",) * 2,
    "aminoglycoside": ("庆大霉素|阿米卡星|链霉素|妥布霉素|(?i:gentamicin|amikacin|streptomycin|tobramycin)",) * 2,
    "macrolide": ("红霉素|阿奇霉素|克拉霉素|(?i:erythromycin|azithromycin|clarithromycin)",) * 2,
    "nsaid": ("阿司匹林|布洛芬|双氯芬酸|吲哚美辛|洛索洛芬|塞来昔布|非甾体|(?i:aspirin|ibuprofen|diclofenac|nsaid)",) * 2,
    "contrast": ("造影剂|对比剂|(?i:contrast)", "造影剂|对比剂|增强CT|增强扫描|增强MRI|CTA|造影|(?i:contrast|angiogra)"),
}
_ALLERGY_CLASSES = {k: (re.compile(a), re.compile(b)) for k, (a, b) in _ALLERGY_CLASSES.items()}
_ALLERGY_CUE = re.compile(r"(?i)过敏|allerg")
_RELATIVE = re.compile(r"(?i)母亲|父亲|其母|其父|母系|父系|家属|家族|兄|姐|弟|妹|儿子|女儿|子女|配偶|\b(?:mother|father|sister|brother|family)\b")
# wording that already handles the allergy or the bleeding risk ("避免使用青霉素类", "评估出血风险后")
_SAFETY_CAUTION = re.compile(r"(?i)过敏|避免|禁用|慎用|替代|改用|皮试|脱敏|预处理|出血风险|评估出血|权衡|禁忌|暂缓|暂不|不予|"
                             r"停用|停止|暂停|不宜|不建议|无需|allerg|avoid|alternative|bleeding risk|contraindicat|withhold|hold")
_BLEEDING = ("出血", "呕血", "黑便", "便血", "咯血", "壁内血肿", "主动脉夹层", "血小板减少",
             "bleeding", "haemorrhage", "hemorrhage", "melena", "hematemesis", "aortic dissection", "intramural hematoma")


def recorded_allergies(case: Case) -> dict:
    """{class: allergen as written} for drug allergies the records state as present ("青霉素过敏史"; not "否认青霉素过敏")."""
    out = {}
    for s in case.sources:
        for sent in T.split_sentences(s.content):
            for clause in re.split(r"[，,；;。]", sent):
                if not _ALLERGY_CUE.search(clause) or _RELATIVE.search(clause):   # "母亲对阿莫西林过敏" is not the patient's
                    continue
                for cls, (rec, _) in _ALLERGY_CLASSES.items():
                    m = rec.search(clause)
                    if m and T.term_positive_in(m.group(0).lower(), clause) and not re.search(r"否认|未发现|不详|未知|(?<![a-z])no\b", clause):
                        out.setdefault(cls, m.group(0))
    return out


def allergy_conflicts(text: str, allergies: dict) -> list[tuple[str, str]]:
    """(plan drug, recorded allergen) for each recorded allergy class the plan text would give, unless it says how
    the allergy is handled."""
    if not allergies or _SAFETY_CAUTION.search(text):
        return []
    return [(m.group(0), allergies[c]) for c, (_, plan) in _ALLERGY_CLASSES.items() if c in allergies
            for m in [plan.search(text)] if m]


def recorded_bleeding(case: Case) -> list[str]:
    """Bleeding-risk terms the records state as present (not "否认呕血、黑便")."""
    found = []
    for s in case.sources:
        for sent in T.split_sentences(s.content):
            low = sent.lower()
            found += [t for t in _BLEEDING if t in low and T.term_positive_in(t, low) and t not in found]
    return found


def _remove_clauses(stmts: list, hits_for) -> tuple[list, list]:
    """Drop each clause for which hits_for(clause, statement_text) returns hits. Returns (kept statements, hits);
    when every statement would go, returns ([], []) with nothing edited, so the caller keeps the section."""
    removed, kept = [], []
    for st in stmts:
        parts = re.split(r"([，,；;。])", st.text)
        keep = []
        for j in range(0, len(parts), 2):
            clause, delim = parts[j], parts[j + 1] if j + 1 < len(parts) else ""
            hits = hits_for(clause, st.text)
            if hits:
                removed += hits
            else:
                keep.append(clause + delim)
        text = "".join(keep).strip().strip("，,；;")
        if text:
            st.text = text if text[-1] in "。.!?！？" else text + ("。" if re.search(r"[\u4e00-\u9fff]", text) else ".")
            kept.append(st)
    return (kept, removed) if kept else ([], [])


def _apply_removal(note: Note, sec: str, hits_for) -> list:
    kept, removed = _remove_clauses(note.sections[sec], hits_for)
    if kept:
        note.sections[sec] = kept
    return removed


def remove_allergy_conflicts(note: Note, case: Case) -> list[tuple[str, str]]:
    """Remove the plan clause that would give a drug of a recorded allergy class. Never empties the plan (the finding
    then stays visible). Returns (drug, allergen) pairs removed."""
    allergies = recorded_allergies(case)
    if not allergies:
        return []
    return _apply_removal(note, "treatment_plan",
                          lambda clause, full: [] if _SAFETY_CAUTION.search(full) else allergy_conflicts(clause, allergies))


# Acute aortic syndromes: the graded antithrombotic screen lives in medtrace/aortic.py (spec and evidence in
# docs/AORTIC_ANTITHROMBOTIC_RULE.md; clinical review pending). The two functions below keep the earlier interface.
_AAS_BLEEDING_TERMS = {"壁内血肿", "主动脉夹层", "aortic dissection", "intramural hematoma"}
_AORTIC_CTX: dict = {}


def _aortic_context(case: Case) -> "A.Context":
    """Per-case cache: check_statement runs once per statement, the record-level state only once per case."""
    key = id(case)
    hit = _AORTIC_CTX.get(key)
    if hit is None or hit[0] is not case:
        if len(_AORTIC_CTX) > 256:
            _AORTIC_CTX.clear()
        hit = _AORTIC_CTX[key] = (case, A.context(case))
    return hit[1]


def recorded_aortic(case: Case) -> list[str]:
    """Entity names of a current, suspected, perioperative or unknown-status AAS (empty when the rule is quiet)."""
    state, finding = A.aortic_state(case)
    return [] if state in A.QUIET_STATES or finding is None else [A.ENTITY_NAME["zh"][finding.entity]]


def remove_aortic_antithrombotics(note: Note, case: Case, lang: str = "zh") -> list[tuple[str, str]]:
    """Earlier interface: screen the plan in place; (drug class, entity) for each rewritten unit."""
    return [(",".join(e.drug_classes), A.ENTITY_NAME["zh"].get(e.entity, e.entity))
            for e in A.screen_plan(note, case, lang) if e.replacement != e.original_candidate]


# An allergy stated in the note must be one the records give; an invented one (seen with qwen3:8b: "青霉素过敏" in a
# plan, no allergy in the record) is a fabricated key fact.
_HYPOTHETICAL = re.compile(r"(?i)如|若|假如|是否|询问|核实|确认|不详|未记录|未知|待|否认|无|未发现|\bif\b|whether|unknown|\bno\b|denies")
_PAREN = re.compile(r"[（(][^（）()]*[）)]")


# Co-occurrence is not an assertion: "予头孢曲松抗感染并监测过敏反应" orders a drug and watches for a reaction.
_MONITOR = re.compile(r"(?i)监测|观察|注意|警惕|预防|monitor|watch for|observe")
_ASSERT_AFTER = re.compile(r"(?i)^(?:类)?(?:药物|抗生素|类药物)?(?:过敏|皮试阳性)|^\s*(?:allergy|allergic)")
_ASSERT_BEFORE = re.compile(r"(?i)(?:对|过敏史\s*[：:]\s*|过敏\s*[：:]\s*)$|allerg(?:y|ic)\s*(?:to\s*)?[:：]?\s*$")


def unsupported_allergy(fragment: str, recorded: dict) -> str | None:
    """The allergen term when `fragment` asserts a patient drug allergy ("青霉素过敏", "对青霉素过敏", "allergy to
    penicillin") that the records do not document."""
    if (not _ALLERGY_CUE.search(fragment) or _HYPOTHETICAL.search(fragment) or _RELATIVE.search(fragment)
            or _MONITOR.search(fragment)):
        return None
    for cls, (rec, _) in _ALLERGY_CLASSES.items():
        if cls in recorded:
            continue
        for m in rec.finditer(fragment):
            if _ASSERT_AFTER.search(fragment[m.end():]) or _ASSERT_BEFORE.search(fragment[:m.start()]):
                return m.group(0)
    return None


def strip_unsupported_allergies(note: Note, case: Case) -> list[str]:
    """Remove a stated allergy the records lack: first a parenthetical holding it ("拟予头孢类（青霉素过敏，需替代）"
    -> "拟予头孢类"), then a clause. Never empties a section. Returns the allergen terms removed."""
    recorded, removed = recorded_allergies(case), []
    for sec in SECTIONS:
        for st in note.sections[sec]:
            def drop(m):
                term = unsupported_allergy(m.group(0)[1:-1], recorded)
                if term:
                    removed.append(term)
                return "" if term else m.group(0)
            st.text = _PAREN.sub(drop, st.text)
        removed += _apply_removal(note, sec, lambda clause, full: [t] if (t := unsupported_allergy(clause, recorded)) else [])
    return removed


_ZH_DONE_PREFIX = re.compile(r"已(?:经)?(?=" + T.ZH_DONE_VERBS + ")")


def _unsupported_done(clause: str, L: Ledger) -> bool:
    if not (T.has_done_cue(clause) and T.support(clause, L.tokens_all) < 0.5):
        return False
    # Documented history must not be retensed (cloud P05: "鉴于已使用抗血小板药物" became "拟使用…", which reads as a new
    # antiplatelet plan): (1) an antithrombotic class the records show was given; (2) any done-object ("已行冠脉造影")
    # that a record sentence reports with a done cue.
    named = A.drug_classes(clause)
    if named and named <= _given_classes(L):
        return False
    m = _DONE_OBJECT.search(T.fw(clause))
    return not (m and _done_in_records(T.squash(m.group(1)), L))


_DONE_OBJECT = re.compile(r"已(?:经)?(?:" + T.ZH_DONE_VERBS + r")([^，,；;。、\s]{2,8})")


def _given_classes(L: Ledger) -> set:
    got = getattr(L, "_aortic_given", None)
    if got is None:
        got = set()
        for f in L.facts:
            if T.has_done_cue(f.text) or re.search(r"予|给予|服用|口服|使用", f.text):
                got |= A.drug_classes(f.text)
        L._aortic_given = got
    return got


def _done_in_records(obj: str, L: Ledger) -> bool:
    """A record sentence names `obj` and reports it as done ("已行", "予", "行…后", "术后")."""
    if len(obj) < 2:
        return False
    for f in L.facts:
        t = T.squash(f.text)
        i = t.find(obj)
        if i >= 0 and (T.has_done_cue(f.text) or re.search(r"(?:予|行|给予|完成|接受|曾)$", t[max(0, i - 4):i])
                       or t[i + len(obj):i + len(obj) + 2].startswith(("后", "术后"))):
            return True
    return False


def retense_completed(note: Note, L: Ledger) -> int:
    """A plan item the records do not show as done but worded as done ("已行冠脉造影") becomes a plan ("拟行冠脉造影").
    Only the Chinese "已/已经 + verb" form is rewritten; other forms ("已于…", English) stay flagged. Returns #rewritten."""
    n = 0
    for st in note.sections["treatment_plan"]:
        parts = re.split(r"([，,；;。！？\n])", st.text)
        for j in range(0, len(parts), 2):
            if _unsupported_done(parts[j], L):
                new = _ZH_DONE_PREFIX.sub("拟", parts[j])
                n += new != parts[j]
                parts[j] = new
        st.text = "".join(parts)
    return n


# Not severity modifiers: ward names (转入重症监护室), disease names that contain the word (重症肌无力), and words that
# merely contain the two characters (严重症状, 加重症状).
_NOT_MODIFIER = r"(?!肌无力|监护|医学|病房|状)"
_SEVERE_WORD = r"(?<![严加])(?:重症|危重)" + _NOT_MODIFIER
_SEVERE = re.compile(_SEVERE_WORD)
_SEVERITY_CRITERIA = re.compile(r"(?i)CURB|PSI|q?SOFA|APACHE|主要标准|次要标准|诊断标准|分级标准|\d+\s*项")
_SEVERE_CLAIM = re.compile(r"(?:符合|提示|考虑|属于|达到|为)?" + _SEVERE_WORD
                           + r"(?:肺炎)?(?:的)?(?:临床特征|临床表现|特征|表现|标准)?")
_NEGATED = re.compile(r"(?:无|未|不|非|否认|没有|排除)[^，,。；;：:]{0,4}$")   # cue earlier in the same clause


def _asserted(m: re.Match) -> bool:
    """The severity mention is claimed, not negated ("无重症表现", "不符合重症肺炎", "未达重症标准")."""
    return not _NEGATED.search(re.split(r"[，,。；;：:]", m.string[:m.start()])[-1])


_PENDING_RESULT = re.compile(r"(?:缺少?|未提供|尚无|暂无|尚未提供|待)([一-鿿A-Za-z0-9-]{2,10}?)"
                             r"(?:检查|检测|化验|培养|穿刺)?(?:结果|报告)")


def drop_planned_result_items(note: Note, case: Case) -> list[str]:
    """Drop a model review item asking for the result of a test the plan itself has just ordered ("缺脑脊液检查结果"
    while the plan says "拟行腰椎穿刺送脑脊液…"): the plan already handles it, and the rubric wants review items for
    missing or conflicting record content. A test the records mention (sent, pending) stays a valid item."""
    plan = note.text("treatment_plan")
    records = "\n".join(s.content for s in case.sources)
    kept, dropped = [], []
    for r in note.review_items:
        m = _PENDING_RESULT.search(r.get("description", ""))
        # records name tests more briefly or differently ("未提供血气分析" vs "动脉血气分析", "甲状腺及肝功能"): the test
        # counts as named in the records if any two-character piece of its core name is there. Conservative on purpose:
        # a wrongly kept item is harmless, a wrongly dropped one loses a real missing-information item.
        core = re.sub(r"(?:分析|功能|常规|检查|测定|水平|全套)$", "", m.group(1)) if m else ""
        in_records = any(core[i:i + 2] in records for i in range(len(core) - 1))
        if r.get("origin", "model") == "model" and m and len(core) >= 2 and core in plan and not in_records:
            dropped.append(r["description"])
        else:
            kept.append(r)
    note.review_items = kept
    return dropped


# one clause, no condition between: "收入ICU或普通病房" is a hedge, "收入普通病房，若…或…转ICU" is an escalation rule
_GAP = r"[^。；，,\n若如转]"
_DISPOSITION_HEDGE = re.compile(rf"(?:ICU|重症监护){_GAP}{{0,8}}或{_GAP}{{0,8}}(?:普通病房|病房)|"
                                rf"(?:普通病房|病房){_GAP}{{0,8}}或{_GAP}{{0,8}}(?:ICU|重症监护)")


def hedged_disposition(note: Note) -> bool:
    """The plan leaves the admission setting open ("ICU监护或普通病房"); logged for evaluation, not rewritten."""
    return bool(_DISPOSITION_HEDGE.search(note.text("treatment_plan")))


def downgrade_unsupported_severity(note: Note) -> int:
    """A discussion statement that calls the case severe ("重症肺炎") without naming the criteria it was checked
    against is rewritten to "严重程度待评估": the label changes treatment intensity, and on the practice case the model
    applied it with only 2 of the 3 minor criteria met. Statements already hedged ("待评估"), citing criteria, or only
    negating severity are left alone. A statement split by split_long_statements is judged with its continuation
    chunks, so criteria in a later sentence still count. Returns #statements rewritten."""
    stmts = note.sections["diagnostic_discussion"]
    sub = lambda rx, repl, text: rx.sub(lambda m: repl if _asserted(m) else m.group(0), text)
    n = 0
    for group in statement_groups(stmts):
        whole = "".join(st.text for st in group)
        if (not any(_asserted(m) for m in _SEVERE.finditer(whole)) or "待评估" in whole
                or _SEVERITY_CRITERIA.search(whole)):
            continue
        first = group[0]
        head, sep, body = re.split(r"([：:])", first.text, 1) if re.search(r"[：:]", first.text) else (first.text, "", "")
        if sep:
            if any(_asserted(m) for m in _SEVERE.finditer(head)):
                head = sub(_SEVERE, "", head)
                head = (re.sub(r"（([^）]*)）", r"（\1，严重程度待评估）", head, 1) if "（" in head
                        else head + "（严重程度待评估）")
            first.text = head + sep + sub(_SEVERE_CLAIM, "需按标准评估是否为重症", body)
        elif any(_asserted(m) for m in _SEVERE.finditer(head)):
            first.text = re.sub(r"[。.]$", "", sub(_SEVERE, "", head)) + "（严重程度待评估）。"
        for st in group[1:]:
            st.text = sub(_SEVERE_CLAIM, "需按标准评估是否为重症", st.text)
        n += 1
    return n


_SPLIT_NUM = re.compile(r"(?<![\d.])(\d+)\s*([、，,])\s*(\d+)(?![\d.])")


def repair_numbers(note: Note, case: Case, L: Ledger) -> tuple[int, list[str]]:
    """Case features carry patient values, and one wrong value caps a case. Small models sometimes split a value with
    punctuation ("SpO₂ 93%" -> "SpO₂ 9、3%"). (1) Rejoin a split value when the joined form, with the characters
    around it, is in the records and the split form is not. (2) Remove any clause whose value is still not in the
    records. Returns (#rejoined, removed clause texts)."""
    src = re.sub(r"\s", "", "".join(s.content for s in case.sources))
    year = case.cutoff.year if case.cutoff else None

    def rejoin(m):
        a, p, b = m.groups()
        before = re.sub(r"\s", "", m.string[:m.start()])[-2:]
        after = m.string[m.end():m.end() + 1]
        ok = (float(a + b) in L.numbers and (before + a + b + after) in src and (a + p + b) not in src)
        return a + b if ok else m.group(0)

    joined, removed = 0, []
    for st in note.sections["case_features"]:
        new = _SPLIT_NUM.sub(rejoin, st.text)
        joined += new != st.text
        st.text = new
    kept, original = [], copy.deepcopy(note.sections["case_features"])
    for i, st in enumerate(note.sections["case_features"]):
        bad = {f.term for f in check_statement("case_features", i, st, case, L) if f.code == "number_not_in_source"}
        if not bad:
            kept.append(st)
            continue
        if any(T.neg_spans(s) for s in T.split_sentences(st.text)):
            removed.append(st.text)   # a fragment could lose the negation it was under ("否认胸痛X、咯血" -> "咯血")
            continue
        parts = re.split(r"([，,；;。、])", st.text)
        keep = []
        for j in range(0, len(parts), 2):
            clause, delim = parts[j], parts[j + 1] if j + 1 < len(parts) else ""
            if {raw for _, _, raw in T.extract_numbers(T.mask_dates(clause, year or 2000))} & bad:
                removed.append(clause.strip())
            else:
                keep.append(clause + delim)
        text = "".join(keep).strip().strip("，,；;")
        if text:
            st.text = text if text[-1] in "。.!?！？" else text + ("。" if re.search(r"[一-鿿]", text) else ".")
            kept.append(st)
    if not kept:   # an empty section scores 0, worse than a flagged value: keep the draft, findings stay visible
        note.sections["case_features"] = original
        return joined, []
    note.sections["case_features"] = kept
    return joined, removed


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
        for index, st in enumerate(note.sections[sec]):
            parts = [x for x in _SENT_END.split(st.text) if x.strip()] if len(st.text) > limit else [st.text]
            chunks: list[str] = []
            for x in parts:
                if chunks and len(chunks[-1]) + len(x) <= limit:
                    chunks[-1] += x
                else:
                    chunks.append(x)
            group = index if len(chunks) > 1 else st.split_group
            out += [Statement(c.strip(), list(st.sources), st.kind, st.basis, list(st.knowledge_ids), group) for c in chunks]
            added += len(chunks) - 1
        note.sections[sec] = out
    return added


def counts(findings: list[Finding]) -> dict:
    c = {HIGH: 0, MEDIUM: 0, LOW: 0}
    for f in findings:
        c[f.severity] += 1
    return c
