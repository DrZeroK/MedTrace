"""Modules C-E orchestration: generation variants A0/A1/A2/S2/A3 for a single case.

A0  direct structured prompt (baseline)                                  1 call
A1  + fact ledger, evidence constraints, statement-level attribution     1 call
A2  + deterministic verification, safe repair, targeted repair call      1-2 calls   (strategy S1, default)
S2  reasoning call: problems, quotes (verified), differentials -> A2    2-3 calls
A3  A2 with a semantic review call producing guarded, targeted patches   2 calls     (strategy S3)

A case can never raise out of run_case: on any failure a conservative, extract-only
note is emitted and flagged for the clinician.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import verify as V
from . import textutil as T
from .knowledge import KnowledgeBase, knowledge_block
from .config import ConfigError, prompt_version
from .inputs import Case
from .ledger import build_ledger, digest, Ledger
from .llm import BudgetExceeded, CallStats, LLMError
from .note import (Note, ParseError, Statement, SECTIONS, note_from_model, parse_json_object,
                   to_record, to_official_record, official_schema_errors, _stmt)


def prompt_dir(version: str | None = None) -> Path:
    return Path(__file__).parent / "prompts" / (version or prompt_version())


_I18N = {
    "en": {
        "lang": "English",
        "no_cutoff": "not specified",
        "empty": "Not generated automatically; clinician input required.",
        "fb_disc": "An automated diagnostic assessment could not be generated for this case. The case features above are verbatim extracts from the admission records; the assessment must be written by a clinician.",
        "fb_plan": "No automated plan was generated. Investigations, treatment and monitoring must be determined by the treating clinician.",
        "fb_review": "Automatic generation failed ({reason}); this note contains verbatim record extracts only and requires full clinician review.",
        "no_input": "No usable admission records were supplied for this case ({reason}); no note could be generated.",
        "undoc": "{item}: not documented in the supplied records; confirm before acting on the plan.",
        "conflict": "Possible conflict or change over time regarding '{term}': {detail}. Verify which applies.",
        "conflict_polarity": "The records both deny and document '{term}' ({sources}); verify which applies.",
        "conflict_internal": "{sources} records '{term}' as absent and later describes it as present; verify with the patient.",
        "conflict_numeric": "'{term}' has different values ({values}) in {sources} with no distinguishing time; verify.",
        "cutoff": "{n} record statement(s) dated after the record cutoff were excluded from this note.",
        "verify": 'Verify: "{text}" - {msg}',
        "overconfident": "The note states the working diagnosis more definitively than the records support; review the working diagnosis.",
        "c_negation_flip": "'{term}' is stated with the opposite polarity to the source records; check the original record.",
        "c_number_not_in_source": "The value {term} in the case features does not appear in the source records; check it.",
        "allergy_fabricated": "The draft stated an allergy to {term} that the records do not document; it was removed. Confirm the allergy history.",
        "aortic_removed": "The records document {term}; plan items giving {drug} were removed. Any antithrombotic therapy must be decided by the treating clinician.",
        "c_allergy_not_in_source": "The note states an allergy to {term} that the records do not document; check it.",
        "c_aortic_antithrombotic": "The records document {term}, and the plan includes antithrombotic therapy; check it.",
        "allergy_removed": "A plan item giving {drug} was removed because the records document an allergy to {allergen}; choose an alternative.",
        "c_allergy_conflict": "The plan gives {term} although the records document an allergy to this drug class; check it.",
        "c_bleeding_risk": "The records document {term}, and the plan includes anticoagulant, antiplatelet or thrombolytic therapy; assess the bleeding risk before acting.",
        "retensed": "The plan described an intervention the records do not document as already done; it is now worded as planned. Confirm whether it was performed.",
        "number_removed": "{n} value(s) in the draft case features could not be matched to the source records and were removed; check the original records for them.",
        "c_unit_mismatch": "The unit of {term} differs from the source records; check it.",
        "c_value_label_mismatch": "A value in the case features is attached to a different test than in the source records; check it.",
        "c_qualifier_not_in_source": "The qualifier '{term}' on a value in the case features is not in the source records; check it.",
        "c_post_cutoff": "The note uses information dated after the record cutoff; check it.",
        "c_trend_direction": "The direction of change stated for {term} contradicts the values; check it.",
        "c_unsupported_completed": "The plan describes an intervention as already done that the records do not document; confirm whether it was performed.",
        "c_false_missing": "The note says allergy information is not documented, but the records contain it; check it.",
    },
    "zh": {
        "lang": "简体中文",
        "no_cutoff": "未指定",
        "empty": "未能自动生成，需医生补充。",
        "fb_disc": "本例未能自动生成拟诊讨论。以上病例特点均为入院资料的原文摘录，诊断分析须由医生书写。",
        "fb_plan": "未自动生成诊疗计划，检查、治疗及监测方案须由经治医生制定。",
        "fb_review": "自动生成失败（{reason}）；本记录仅包含资料原文摘录，需医生全面审核。",
        "no_input": "本例未提供可用的入院资料（{reason}），无法生成记录。",
        "undoc": "{item}：所提供资料中未记录，执行诊疗计划前请核实。",
        "conflict": "关于“{term}”的信息可能存在矛盾或随时间变化：{detail}。请核实。",
        "cutoff": "有{n}条晚于资料截止时间的记录内容未纳入本记录。",
        "verify": "请核实：“{text}”——{msg}",
        "overconfident": "记录中初步诊断的确定程度可能高于资料支持，请复核初步诊断表述。",
        "conflict_polarity": "资料中对“{term}”既有否认记载又有阳性记载（{sources}），请核实。",
        "conflict_internal": "{sources}对“{term}”的记载前后不一致（先记为无，后有阳性描述），请向患者核实。",
        "conflict_numeric": "“{term}”在{sources}中的数值不一致（{values}），且未注明不同测量时间，请核实。",
        "c_negation_flip": "“{term}”的有无表述与原始资料相反，请核对原始资料。",
        "c_number_not_in_source": "病例特点中的数值{term}未见于原始资料，请核对。",
        "allergy_fabricated": "草稿写有资料未记载的{term}过敏，已删除，请核实患者过敏史。",
        "aortic_removed": "资料记录有{term}，诊疗计划中含{drug}的抗栓条目已删除，是否抗栓须由经治医生决定。",
        "c_allergy_not_in_source": "记录中写有资料未记载的{term}过敏，请核对。",
        "c_aortic_antithrombotic": "资料记录有{term}，诊疗计划含抗栓治疗，请核对。",
        "allergy_removed": "资料记录有{allergen}过敏，诊疗计划中含{drug}的条目已删除，请另选方案。",
        "c_allergy_conflict": "诊疗计划中的{term}与资料记录的药物过敏史属同类药物，请核对。",
        "c_bleeding_risk": "资料记录有{term}，诊疗计划包含抗凝、抗血小板或溶栓治疗，请评估出血风险后再执行。",
        "retensed": "诊疗计划中有资料未记录的处置被写为已完成，已改为拟行，请核实是否已执行。",
        "number_removed": "草稿病例特点中有{n}处数值未能与原始资料对应，已删除，请查阅原始资料补充。",
        "c_unit_mismatch": "{term}的单位与原始资料不一致，请核对。",
        "c_value_label_mismatch": "病例特点中有数值与原始资料中的检查项目不对应，请核对。",
        "c_qualifier_not_in_source": "病例特点中数值的限定词“{term}”未见于原始资料，请核对。",
        "c_post_cutoff": "记录引用了晚于资料截止时间的信息，请核对。",
        "c_trend_direction": "记录对{term}的变化方向（升高/下降）与数值不符，请核对。",
        "c_unsupported_completed": "诊疗计划将资料未记录的处置写为已完成，请核实是否已执行。",
        "c_false_missing": "记录称过敏信息未记录，但原始资料中已有记载，请核对。",
    },
}
# Verifier findings that are clinician-facing in the official medical_record: high-severity record contradictions and
# value errors, plus overconfident wording. They use the clean `c_<code>` phrase above instead of quoting the draft;
# every other finding stays in the run log (findings_final_detail).
# omitted_critical stays in the run log: on the practice run it fired mostly on "接种史不详" / "未查" lines.
OFFICIAL_VERIFIER_CODES = {"overconfident", "bleeding_risk"}
CLINICIAN_HIGH_CODES = {"negation_flip", "trend_direction", "number_not_in_source", "unit_mismatch", "value_label_mismatch", "post_cutoff",
                        "unsupported_completed", "false_missing", "qualifier_not_in_source", "allergy_conflict",
                        "allergy_not_in_source", "aortic_antithrombotic"}
MAX_REVIEW_ITEMS = 6
# Lower ranks survive the cap: pipeline notices (fallback, cutoff), then record contradictions and high findings,
# undocumented core items, the model's own items, and last numeric discrepancies and certainty wording.
def _review_rank(r: dict) -> int:
    origin = r.get("origin", "model")
    if origin == "pipeline":
        return 0
    if (origin == "verifier" and r.get("severity") == "high") or r.get("conflict_kind") in ("internal", "polarity"):
        return 1
    if origin == "ledger" and r.get("type") == "missing":
        return 2
    if origin in ("model", "knowledge"):
        return 3
    return 4
_MSG_ZH = {
    "invalid_ref": "引用了不存在的来源编号", "post_cutoff": "涉及晚于资料截止时间的信息",
    "date_not_in_source": "日期未见于资料", "number_not_in_source": "数值未见于资料",
    "unit_mismatch": "数值单位与资料不一致", "negation_flip": "阴性/阳性表述与资料相反",
    "undocumented_negative": "资料中未提及，却被表述为无", "undocumented_normal": "资料支持不足的“正常”表述",
    "low_support": "该陈述在资料中支持不足", "unsupported_completed": "计划中将未记录的处置表述为已完成",
    "overconfident": "诊断表述过于肯定", "trend_direction": "变化方向描述与数值不符", "weak_attribution": "所引来源支持不足", "missing_ref": "缺少来源引用",
    "empty_section": "该部分为空", "value_label_mismatch": "数值与检查项目不对应",
    "qualifier_not_in_source": "数值的限定词（如空腹、持续）未见于资料",
    "allergy_conflict": "计划药物与记录的过敏史冲突", "allergy_not_in_source": "过敏史未见于资料",
    "aortic_antithrombotic": "主动脉夹层/壁内血肿而计划含抗栓治疗", "bleeding_risk": "资料记录出血风险而计划含抗栓治疗",
    "omitted_critical": "资料中的过敏信息或待回报/未做项目未在记录中体现",
    "false_missing": "资料中已有记录，却被表述为未记录",
    "knowledge_record_value": "知识性陈述含病人记录中的特定数值",
    "context_assertion": "来源中的不确定或缺失信息被写成确定事实",
    "context_experiencer": "来源中的家属信息被写成患者信息",
    "context_temporality": "来源中的既往信息被写成当前信息",
    "context_scope_ambiguous": "来源中的否定范围不明确，需核实原文意图",
}
_CORE_RX = {"allergy": r"(?i)allerg|过敏", "medication": r"(?i)medication|drug|用药|药物", "vitals": r"(?i)vital|生命体征"}


@lru_cache(maxsize=None)
def _load_prompt(version: str, name: str, lang: str) -> str:
    return (Path(__file__).parent / "prompts" / version / lang / f"{name}.txt").read_text("utf-8")


def load_prompt(name: str, lang: str, version: str | None = None) -> str:
    return _load_prompt(version or prompt_version(), name, lang)


def prompt_fingerprint(version: str | None = None) -> str:
    version = version or prompt_version()
    h = hashlib.sha256()
    for p in sorted(prompt_dir(version).rglob("*.txt")):
        h.update(p.read_bytes())
    return f"{version}:{h.hexdigest()[:12]}"


def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace(f"<<{k}>>", str(v))
    return template


def sources_block(case: Case) -> str:
    return "\n".join(f'<source id="{s.sid}">\n{s.content}\n</source>' for s in case.sources)


def _normalise_basis(note: Note, L) -> int:
    """Reclassify a statement the model labelled 'knowledge' but which actually reasons over a patient
    value from the records. Such text is patient-grounded inference, not book knowledge; leaving it as
    'knowledge' both fires the knowledge_record_value verifier false alarm and mislabels the official
    evidence kind. Count is logged for audit. Approved quoted knowledge (with knowledge_ids) is kept.
    """
    year = None
    changed = 0
    for sec in SECTIONS:
        for st in note.sections[sec]:
            if st.basis != "knowledge" or st.knowledge_ids or sec == "case_features":
                continue
            nums = T.extract_numbers(T.mask_dates(st.text, year or 2000))
            if any(val in L.numbers for val, _, _ in nums):
                st.basis = "inference"
                changed += 1
    return changed


@dataclass
class CaseResult:
    record: dict
    note: Note
    status: str                                   # ok | fallback | input_error
    initial_findings: list = field(default_factory=list)   # on the raw model draft
    final_findings: list = field(default_factory=list)
    log: dict = field(default_factory=dict)


class Pipeline:
    def __init__(self, cfg, client):
        self.cfg = cfg
        self.client = client
        if not cfg.development and (cfg.context_mode != "legacy" or cfg.prompt_candidate_path):
            raise ConfigError("context and prompt candidates require explicit development mode")
        self.candidate = None
        if cfg.prompt_candidate_path:
            path = Path(cfg.prompt_candidate_path)
            if not path.is_absolute():
                raise ConfigError("PROMPT_CANDIDATE_PATH must be absolute")
            try:
                candidate = json.loads(path.read_text("utf-8"))
                instruction = candidate["instruction"]
                valid = (candidate["schema_version"] == 1 and isinstance(instruction, str) and 0 < len(instruction.strip()) <= 1600
                         and "<<" not in instruction and ">>" not in instruction
                         and candidate["base_prompt"] == prompt_fingerprint(cfg.prompt_version)
                         and candidate["instruction_sha256"] == hashlib.sha256(instruction.encode()).hexdigest())
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise ConfigError("cannot load prompt candidate") from e
            if not valid:
                raise ConfigError("prompt candidate failed schema/hash/base-prompt validation")
            self.candidate = candidate
        self.kb = KnowledgeBase(cfg.kb_path) if cfg.kb_path else None

    # ------------------------------------------------------------------ public
    def run_case(self, case: Case, variant: str | None = None, deadline: float | None = None,
                 changes: str = "") -> CaseResult:
        variant = variant or self.cfg.pipeline
        t0 = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        stats = CallStats()
        log = {"case_id": case.case_id, "index": case.index, "variant": variant, "warnings": list(case.warnings),
               "excluded_sources": case.excluded_sources, "redacted_statements": len(case.redacted)}
        if self.cfg.development:
            log.update(context_mode=self.cfg.context_mode, candidate_sha256=self.candidate["instruction_sha256"] if self.candidate else None)
        lang = self.cfg.output_lang if self.cfg.output_lang in _I18N else case.lang
        tr = _I18N[lang]
        initial, final, status = [], [], "ok"
        try:
            if not case.usable or (self.cfg.official and case.protocol_errors):
                status = "input_error"
                reason = "; ".join(case.errors + case.protocol_errors) or "no sources"
                log["error"] = reason
                note = Note()
                note.sections["case_features"] = [Statement(tr["no_input"].format(reason=reason))]
                note.review_items.append({"type": "missing", "description": tr["no_input"].format(reason=reason),
                                          "source_ids": [], "origin": "pipeline"})
                L = None
            else:
                L = build_ledger(case, context_mode=self.cfg.context_mode)
                if self.cfg.context_mode != "legacy":
                    log["contexts"] = [{"fact_id": f.fid, "source_id": f.sid, "text": f.text, "scopes": f.contexts}
                                       for f in L.facts if f.contexts]
                if self.kb and variant != "A0":
                    audit = {"case_id": case.case_id, "index": case.index, "status": "ok", "retrieved": [], "rules": []}
                    log["knowledge"] = audit
                    try:
                        cards = self.kb.retrieve(case.text)
                        normalized = [{"fact_id": f.fid, "source_id": f.sid, "polarity": f.polarity,
                                      "matches": self.kb.normalize(f.text)} for f in L.facts]
                        rules = self.kb.check_rules(L)
                        L.knowledge_cards = {e["id"]: e for e in cards}
                        audit.update(status="ok" if cards else "no_hits", retrieved=cards, normalized=normalized, rules=rules)
                    except Exception as e:
                        L.knowledge_cards = {}
                        audit.update(status="degraded", error=str(e))
                try:
                    note, initial, final = self._generate_and_verify(case, L, variant, lang, stats, deadline, changes, log)
                    if self.cfg.official and any(not note.sections[sec] for sec in SECTIONS):
                        raise ParseError("generation left an empty required section")
                except (LLMError, ParseError) as e:
                    status = "fallback"
                    log["error"] = f"{type(e).__name__}: {e}"
                    if isinstance(e, BudgetExceeded):
                        log["budget_exhausted"] = True
                    note = self._fallback(case, L, tr, type(e).__name__)
        except Exception as e:  # defensive: a bug must not take the batch down
            status = "fallback"
            log["error"] = f"internal {type(e).__name__}: {e}"
            note = Note()
            note.review_items.append({"type": "verify", "description": tr["fb_review"].format(reason="internal error"),
                                      "source_ids": [], "origin": "pipeline"})
        audit = log.get("knowledge")
        if audit is not None:
            if audit["status"] == "degraded":
                note.review_items.append({"type": "verify", "description": "知识检索失败，本例已退回原生成流程，需复核。",
                                          "source_ids": [], "origin": "pipeline"})
            for rule in audit["rules"]:
                if rule["state"] != "not_triggered":
                    note.review_items.append({"type": "verify", "description": rule["message"],
                                              "source_ids": rule["source_ids"], "origin": "knowledge"})
            audit["citations"] = [{"section": sec, "index": i, "statement": st.text, "knowledge_ids": st.knowledge_ids,
                "valid_ids": all(k in (L.knowledge_cards if L else {}) for k in st.knowledge_ids),
                "clinical_support": "requires_clinician_review"}
                for sec in SECTIONS for i, st in enumerate(note.sections[sec]) if st.knowledge_ids]
            audit["citation_findings"] = [f.as_dict() for f in final if "knowledge" in f.code]
            if variant == "A1":
                for finding in audit["citation_findings"]:
                    note.review_items.append({"type": "verify", "description": finding["message"],
                                              "source_ids": [], "origin": "verifier", "code": finding.get("code")})
        for sec in SECTIONS:
            if not note.sections[sec]:
                note.sections[sec] = [Statement(tr["fb_disc"] if status != "ok" and sec == "diagnostic_discussion" else
                                                tr["fb_plan"] if status != "ok" and sec == "treatment_plan" else tr["empty"])]
        log.update(status=status, calls=stats.calls, http_attempts=stats.http_attempts, retries=stats.retries,
                   llm_compat=stats.compat,
                   prompt_tokens=stats.prompt_tokens, completion_tokens=stats.completion_tokens,
                   total_tokens=stats.total_tokens, reasoning_tokens=stats.reasoning_tokens,
                   cached_tokens=stats.cached_tokens, usage_missing=stats.usage_missing,
                   llm_latency=round(stats.latency, 3), latency=round(time.monotonic() - t0, 3),
                   llm_errors=stats.errors[-3:], findings_initial=V.counts(initial), findings_final=V.counts(final),
                   findings_final_detail=[f.as_dict() for f in final])
        log.update(started_at=started_at, finished_at=datetime.now(timezone.utc).isoformat(), attempts=stats.attempts)
        visible = lambda r: (not self.cfg.official or r.get("origin", "model") not in ("verifier", "internal")
                             or r.get("official_visible"))
        ranked = sorted((r for r in note.review_items if visible(r) and r.get("description")), key=_review_rank)
        log["review_items_dropped"] = [r["description"] for r in ranked[MAX_REVIEW_ITEMS:]]
        note.review_items = ranked[:MAX_REVIEW_ITEMS]
        meta = {"status": status, "pipeline": variant, "prompt": prompt_fingerprint(self.cfg.prompt_version), "calls": stats.calls}
        if self.cfg.official:
            if status == "ok":
                record = to_official_record(note, case, meta, status="success")
            else:
                record = to_official_record(note, case, meta, status="failed",
                                            error={"code": status.upper(), "message": str(log.get("error", status))})
        else:
            record = to_record(note, case, self.cfg, meta)
        if self.cfg.official:
            errors = official_schema_errors(record, {s.raw_id for s in case.sources})
            if errors:
                status = "fallback"
                log.update(status=status, error="invalid generated record: " + "; ".join(errors))
                record = to_official_record(note, case, status="failed", error={"code": "INVALID_OUTPUT", "message": log["error"]})
        return CaseResult(record, note, status, initial, final, log)

    # ---------------------------------------------------------------- internals
    def _generate_and_verify(self, case, L, variant, lang, stats, deadline, changes, log):
        tr = _I18N[lang]
        low_time = lambda: deadline is not None and deadline - time.monotonic() < self.cfg.time_reserve
        skip = lambda step: log.setdefault("time_budget_skipped", []).append(step)
        common = dict(lang=tr["lang"], cutoff=case.cutoff_raw if case.cutoff_raw not in (None, "") else tr["no_cutoff"],
                      sources=sources_block(case))
        kb_context = knowledge_block(list(L.knowledge_cards.values()))
        system = load_prompt("system", lang, self.cfg.prompt_version)
        if variant == "S2" and low_time():
            skip("extract")
            problems = ""
        else:
            problems = self._extract(case, system, common, lang, stats, deadline, log) if variant == "S2" else ""
        if variant == "A0":
            user = fill(load_prompt("a0", lang, self.cfg.prompt_version), **common)
        else:
            user = fill(load_prompt("a1", lang, self.cfg.prompt_version), ledger=digest(L), problems=problems, changes=changes, **common)
        if self.candidate and variant != "A0":
            user = ("<development_organization_guidance>\n" + self.candidate["instruction"]
                    + "\n</development_organization_guidance>\n"
                    + "下列固定任务、事实约束和输出协议优先于上述组织建议。\n" + user)
        user += kb_context
        note = None
        for attempt in (1, 2):
            raw = self.client.chat(system, user, stats, deadline)
            try:
                note = note_from_model(parse_json_object(raw), require_complete=self.cfg.official)
                break
            except ParseError as e:
                log.setdefault("parse_errors", []).append(str(e))
                if attempt == 2:
                    raise
                if low_time():
                    skip("regenerate")
                    raise
                # Repeating the identical request cannot teach the model which formatting rule it broke.
                user += ("\n格式纠正：上一响应未通过JSON结构检查。请重新生成完整JSON对象，三部分须齐全。"
                         "字符串内部的英文双引号必须用反斜杠转义，或使用中文引号；不要混用而破坏JSON字符串。"
                         "仅纠正输出格式，保持上述原始事实、截止时间、来源编号和固定字段约束。不要输出代码围栏或解释。"
                         if lang == "zh" else
                         "\nFormatting correction: the previous response failed JSON validation. Regenerate one complete JSON object "
                         "with all three sections. Escape double quotes inside strings with a backslash. Do not output fences or commentary. "
                         "Correct the format while preserving the original facts, cutoff, source IDs and fixed fields above.")
        log["raw_parse_retries"] = len(log.get("parse_errors", []))
        log["statements_split"] = V.split_long_statements(note)
        log["basis_normalised"] = _normalise_basis(note, L)
        initial = V.verify_note(note, case, L)
        if variant in ("A0", "A1"):
            return note, initial, initial
        log["refs_dropped"] = V.safe_repair(note, case)
        log["copied_diagnosis_dropped"] = V.drop_copied_diagnosis(note, L)
        log["numbers_rejoined"], removed = V.repair_numbers(note, case, L)
        log["number_clauses_removed"] = removed
        log["qualifiers_removed"] = V.strip_unsupported_qualifiers(note, case)
        log["allergies_unsupported_removed"] = V.strip_unsupported_allergies(note, case)
        for term in dict.fromkeys(log["allergies_unsupported_removed"]):
            note.review_items.append({"type": "verify", "description": tr["allergy_fabricated"].format(term=term),
                                      "source_ids": [], "origin": "verifier", "official_visible": True})
        log["aortic_antithrombotics_removed"] = V.remove_aortic_antithrombotics(note, case)
        if log["aortic_antithrombotics_removed"]:
            drugs = ("、" if lang == "zh" else ", ").join(dict.fromkeys(d for d, _ in log["aortic_antithrombotics_removed"]))
            note.review_items.append({"type": "verify", "description": tr["aortic_removed"].format(
                drug=drugs, term=log["aortic_antithrombotics_removed"][0][1]), "source_ids": [], "origin": "verifier",
                "official_visible": True})
        log["allergy_conflicts_removed"] = V.remove_allergy_conflicts(note, case)
        for drug, allergen in log["allergy_conflicts_removed"]:
            note.review_items.append({"type": "verify", "description": tr["allergy_removed"].format(drug=drug, allergen=allergen),
                                      "source_ids": [], "origin": "verifier", "official_visible": True})
        log["completed_retensed"] = V.retense_completed(note, L)
        if log["completed_retensed"]:
            note.review_items.append({"type": "verify", "description": tr["retensed"], "source_ids": [],
                                      "origin": "verifier", "official_visible": True})
        if removed:
            note.review_items.append({"type": "verify", "description": tr["number_removed"].format(n=len(removed)),
                                      "source_ids": [], "origin": "verifier", "official_visible": True})
        findings = V.verify_note(note, case, L)
        actionable = [f for f in findings if f.severity in (V.HIGH, V.MEDIUM) and f.section in SECTIONS and f.index >= 0]
        mode = ("review" if variant == "A3" else
                "repair" if self.cfg.repair_call and any(f.severity == V.HIGH for f in findings) else None)
        if mode and low_time():
            skip(mode)
            mode = None
        if mode:
            try:
                user = fill(load_prompt(mode, lang, self.cfg.prompt_version), draft=_draft_json(note),
                            findings=json.dumps([{"section": f.section, "index": f.index, "issue": f.message} for f in actionable],
                                                ensure_ascii=False, indent=1), **common)
                user += kb_context
                obj = parse_json_object(self.client.chat(system, user, stats, deadline))
                log["patches"] = apply_patches(note, obj.get("patches") or [], case, L, mode,
                                               {(f.section, f.index) for f in actionable})
                if mode == "review":
                    extra = note_from_model({"case_features": [], "review_items": obj.get("review_items") or []}).review_items
                    for r in extra:
                        r["source_ids"] = [s for s in r["source_ids"] if s in case.valid_ids]
                    note.review_items.extend(extra)
            except (LLMError, ParseError) as e:   # verification call is optional: keep the draft
                log["revise_error"] = f"{type(e).__name__}: {e}"
            findings = V.verify_note(note, case, L)
        self._finalise(note, case, L, findings + V.omission_findings(note, L), tr, lang)
        return note, initial, V.verify_note(note, case, L)

    def _extract(self, case, system, common, lang, stats, deadline, log) -> str:
        """S2: model-extracted problem list; every quote must be found verbatim in its cited source."""
        try:
            obj = parse_json_object(self.client.chat(system, fill(load_prompt("extract", lang, self.cfg.prompt_version), **common), stats, deadline,
                                                     self.cfg.reason_thinking))
        except (LLMError, ParseError) as e:
            log["extract_error"] = f"{type(e).__name__}: {e}"
            return ""
        norm = lambda s: re.sub(r"\s+", " ", str(s)).strip().lower()
        src = {s.sid: norm(s.content) for s in case.sources}
        lines, kept, rejected = [], 0, 0
        for i, p in enumerate((obj.get("problems") or [])[:10], 1):
            if not isinstance(p, dict) or not p.get("problem"):
                continue
            ev = []
            for e in p.get("evidence") or []:
                if isinstance(e, dict) and str(e.get("source")) in src and norm(e.get("quote", "")) and norm(e["quote"]) in src[str(e["source"])]:
                    ev.append(f'   - ({e["source"]}, {e.get("polarity", "positive")}) "{e["quote"]}"')
                    kept += 1
                else:
                    rejected += 1
            if ev:
                certainty = f' ({p["certainty"]})' if isinstance(p.get("certainty"), str) and p["certainty"].strip() else ""
                lines.append(f'{i}. [{p.get("urgency", "routine")}] {p["problem"]}{certainty}')
                lines += ev
                for d in (p.get("differentials") or [])[:3]:
                    if isinstance(d, dict) and str(d.get("name") or "").strip():
                        lines.append("   * " + " | ".join(f"{k}: {str(d[k]).strip()[:120]}" for k in ("name", "for", "against", "test")
                                                         if str(d.get(k) or "").strip()))
                miss = [str(m).strip()[:80] for m in (p.get("missing") or [])[:3] if str(m).strip()]
                if miss:
                    lines.append("   ? " + "; ".join(miss))
        log["extract_quotes"] = {"kept": kept, "rejected": rejected}
        if not lines:
            return ""
        # quotes are checked against the records; differentials (*) and missing items (?) are the model's reasoning,
        # so the writing step must still ground every statement in the records
        head = ("模型的问题清单与鉴别思路：引文已逐字核对；“*”鉴别方向与“?”缺失信息为推理，写入记录时仍须以资料为据"
                if lang == "zh" else
                "Model problem list and differential reasoning: quotes verified verbatim; '*' differentials and '?' missing "
                "items are reasoning, so every statement written from them must still rest on the records")
        return "\n<problem_list>\n" + head + "\n" + "\n".join(lines) + "\n</problem_list>\n"

    def _finalise(self, note, case, L: Ledger, findings, tr, lang):
        """Surface what could not be resolved, plus ledger-derived review items. No clinical rewriting."""
        unresolved = [f for f in findings if f.severity in (V.HIGH, V.MEDIUM)]
        sources_of = {(f.section, f.text): note.sections[f.section][f.index].sources
                      for f in unresolved if f.section in SECTIONS and 0 <= f.index < len(note.sections[f.section])}
        fact_sid = {x.text: x.sid for x in L.facts}
        sources_of.update({(f.section, f.text): [fact_sid[f.text]] for f in unresolved if f.index < 0 and f.text in fact_sid})
        if self.cfg.on_unresolved == "drop":
            for sec in SECTIONS:
                drop = {f.index for f in unresolved if f.section == sec and f.severity == V.HIGH}
                # may leave the section empty: run_case then inserts the "clinician input required" placeholder
                note.sections[sec] = [s for i, s in enumerate(note.sections[sec]) if i not in drop]
        have = " ".join(r["description"] for r in note.review_items)
        def add(typ, desc, ids=(), origin="ledger", **extra):
            note.review_items.append({"type": typ, "description": desc, "source_ids": list(ids),
                                      "origin": origin, **extra})
        conflicts = [c for c in L.conflicts if c["term"] not in have.lower()][:5]   # model already explained the rest
        conflict_terms = {c["term"] for c in conflicts}
        # one review item per statement. Development output quotes the draft for debugging; the clinician-facing text
        # (`clinician`, used by the official record) never does, and only clinician-relevant findings get one.
        merged: dict = {}
        for f in sorted(unresolved, key=lambda f: f.severity != V.HIGH):
            if f.code == "empty_section":
                continue
            msg = _MSG_ZH.get(f.code, f.message) if lang == "zh" else f.message
            m = merged.setdefault((f.section, f.text), {"high": False, "msgs": [], "codes": [], "findings": []})
            m["high"] |= f.severity == V.HIGH
            m["findings"].append(f)
            if msg not in m["msgs"]:
                m["msgs"].append(msg)
            if f.code not in m["codes"]:
                m["codes"].append(f.code)
        said = set()
        for key, m in merged.items():
            clean = None
            for f in m["findings"]:
                relevant = (f.severity == V.HIGH and f.code in CLINICIAN_HIGH_CODES) or f.code in OFFICIAL_VERIFIER_CODES
                if relevant and (f.code, f.term) not in said and f.term not in conflict_terms:
                    said.add((f.code, f.term))
                    clean = tr["overconfident"] if f.code == "overconfident" else tr["c_" + f.code].format(term=f.term[:60])
                    break
            if self.cfg.official and clean is None:
                continue                      # internal QA finding: run log only
            desc = (clean if self.cfg.official or (clean and "overconfident" in m["codes"]) else
                    tr["verify"].format(text=key[1][:200], msg="; ".join(m["msgs"])))
            add("verify", desc, sources_of.get(key, ()), origin="verifier", codes=m["codes"],
                severity="high" if m["high"] else "medium", official_visible=clean is not None, clinician=clean)
        for u in L.undocumented:
            if not re.search(_CORE_RX[u["key"]], have):
                add("missing", tr["undoc"].format(item=u[lang]), origin="ledger")
        rid = case.raw_id
        for c in conflicts:
            fmt = dict(term=c["term"], sources="、".join(rid(s) for s in c["sources"]) if lang == "zh" else
                       ", ".join(rid(s) for s in c["sources"]))
            if c["kind"] == "numeric":
                fmt["values"] = "、".join(f"{v:g}" for v in c["values"]) + f" {c['unit']}"
            add("conflict", tr.get("conflict_" + c["kind"], tr["conflict"]).format(detail=c["detail"][:300], **fmt),
                c["sources"], origin="ledger", conflict_kind=c["kind"])
        if case.redacted or case.excluded_sources:
            add("verify", tr["cutoff"].format(n=len(case.redacted) + len(case.excluded_sources)),
                origin="pipeline")

    def _fallback(self, case, L, tr, reason) -> Note:
        note = Note()
        note.sections["case_features"] = [Statement(f.text, [f.sid]) for f in L.facts[:60]]
        note.sections["diagnostic_discussion"] = [Statement(tr["fb_disc"])]
        note.sections["treatment_plan"] = [Statement(tr["fb_plan"])]
        note.review_items.append({"type": "verify", "description": tr["fb_review"].format(reason=reason),
                                  "source_ids": [], "origin": "pipeline"})
        return note


def _draft_json(note: Note) -> str:
    return json.dumps({sec: [{"index": i, "text": s.text, "sources": s.sources, "basis": s.basis, "knowledge_ids": s.knowledge_ids} for i, s in enumerate(note.sections[sec])]
                       for sec in SECTIONS}, ensure_ascii=False, indent=1)


def apply_patches(note: Note, patches: list, case: Case, L: Ledger, mode: str, flagged: set) -> dict:
    """Apply model-proposed patches under deterministic guards.

    A patch is rejected when it would introduce a new high-severity finding, make a statement
    worse than the one it replaces, delete an unflagged case feature, or empty a section.
    This is what keeps a second model pass from adding hallucinations of its own.
    """
    res = {"applied": 0, "rejected": 0, "reasons": []}
    bad = lambda fs: sum(f.severity in (V.HIGH, V.MEDIUM) for f in fs)
    high = lambda fs: any(f.severity == V.HIGH for f in fs)

    def reject(why):
        res["rejected"] += 1
        res["reasons"].append(why)

    deletes = []
    for p in patches[:40]:
        if not isinstance(p, dict) or p.get("section") not in SECTIONS:
            reject("malformed patch")
            continue
        sec, action = p["section"], str(p.get("action", "")).lower()
        stmts = note.sections[sec]
        idx = p.get("index")
        text = p.get("text") if isinstance(p.get("text"), str) else ""
        srcs = [str(s) for s in (p.get("sources") or []) if str(s) in case.valid_ids]
        in_range = isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(stmts)
        if action == "replace":
            if not in_range or not text.strip():
                reject("replace: bad index or empty text")
            elif mode == "repair" and (sec, idx) not in flagged:
                reject("replace: statement was not flagged")
            else:
                old = stmts[idx]
                new = _stmt({"text": text.strip(), "sources": srcs or old.sources, "kind": old.kind,
                             "basis": p.get("basis", old.basis), "knowledge_ids": p.get("knowledge_ids", [])})
                f_new, f_old = V.check_statement(sec, idx, new, case, L), V.check_statement(sec, idx, old, case, L)
                if high(f_new) or bad(f_new) > bad(f_old):
                    reject("replace: new text fails verification")
                else:
                    stmts[idx] = new
                    res["applied"] += 1
        elif action == "add" and mode == "review":
            new = _stmt({"text": text.strip(), "sources": srcs, "kind": p.get("kind"),
                         "basis": p.get("basis"), "knowledge_ids": p.get("knowledge_ids")})
            if new is None or (sec == "case_features" and not srcs) or bad(V.check_statement(sec, len(stmts), new, case, L)):
                reject("add: unsupported or unattributed statement")
            else:
                stmts.append(new)
                res["applied"] += 1
        elif action == "delete":
            if not in_range:
                reject("delete: bad index")
            elif sec == "case_features" and (sec, idx) not in flagged:
                reject("delete: case feature was not flagged by the verifier")
            else:
                deletes.append((sec, idx))
        else:
            reject(f"unsupported action {action!r}")
    for sec, idx in sorted(set(deletes), key=lambda x: -x[1]):
        if len(note.sections[sec]) > 1 and idx < len(note.sections[sec]):
            del note.sections[sec][idx]
            res["applied"] += 1
        else:
            reject("delete: would empty the section")
    res["reasons"] = res["reasons"][:10]
    return res
