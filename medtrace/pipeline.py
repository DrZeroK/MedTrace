"""Modules C-E orchestration: generation variants A0/A1/A2/S2/A3 for a single case.

A0  direct structured prompt (baseline)                                  1 call
A1  + fact ledger, evidence constraints, statement-level attribution     1 call
A2  + deterministic verification, safe repair, targeted repair call      1-2 calls   (strategy S1, default)
S2  model problem extraction (quotes verified) -> A2                     2-3 calls
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
from functools import lru_cache
from pathlib import Path

from . import verify as V
from .config import prompt_version
from .inputs import Case
from .ledger import build_ledger, digest, Ledger
from .llm import BudgetExceeded, CallStats, LLMError
from .note import Note, ParseError, Statement, SECTIONS, note_from_model, parse_json_object, to_record


def prompt_dir() -> Path:
    return Path(__file__).parent / "prompts" / prompt_version()


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
        "cutoff": "{n} record statement(s) dated after the record cutoff were excluded from this note.",
        "verify": 'Verify: "{text}" - {msg}',
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
    },
}
_MSG_ZH = {
    "invalid_ref": "引用了不存在的来源编号", "post_cutoff": "涉及晚于资料截止时间的信息",
    "date_not_in_source": "日期未见于资料", "number_not_in_source": "数值未见于资料",
    "unit_mismatch": "数值单位与资料不一致", "negation_flip": "阴性/阳性表述与资料相反",
    "undocumented_negative": "资料中未提及，却被表述为无", "undocumented_normal": "资料支持不足的“正常”表述",
    "low_support": "该陈述在资料中支持不足", "unsupported_completed": "计划中将未记录的处置表述为已完成",
    "overconfident": "诊断表述过于肯定", "weak_attribution": "所引来源支持不足", "missing_ref": "缺少来源引用",
    "empty_section": "该部分为空", "value_label_mismatch": "数值与检查项目不对应",
    "omitted_critical": "资料中的过敏信息或待回报/未做项目未在记录中体现",
    "false_missing": "资料中已有记录，却被表述为未记录",
    "knowledge_record_value": "知识性陈述含病人记录中的特定数值",
}
_CORE_RX = {"allergy": r"(?i)allerg|过敏", "medication": r"(?i)medication|drug|用药|药物", "vitals": r"(?i)vital|生命体征"}


@lru_cache(maxsize=None)
def _load_prompt(version: str, name: str, lang: str) -> str:
    return (Path(__file__).parent / "prompts" / version / lang / f"{name}.txt").read_text("utf-8")


def load_prompt(name: str, lang: str) -> str:
    return _load_prompt(prompt_version(), name, lang)


def prompt_fingerprint() -> str:
    version = prompt_version()
    h = hashlib.sha256()
    for p in sorted(prompt_dir().rglob("*.txt")):
        h.update(p.read_bytes())
    return f"{version}:{h.hexdigest()[:12]}"


def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace(f"<<{k}>>", str(v))
    return template


def sources_block(case: Case) -> str:
    return "\n".join(f'<source id="{s.sid}">\n{s.content}\n</source>' for s in case.sources)


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

    # ------------------------------------------------------------------ public
    def run_case(self, case: Case, variant: str | None = None, deadline: float | None = None,
                 changes: str = "") -> CaseResult:
        variant = variant or self.cfg.pipeline
        t0 = time.monotonic()
        stats = CallStats()
        log = {"case_id": case.case_id, "index": case.index, "variant": variant, "warnings": list(case.warnings),
               "excluded_sources": case.excluded_sources, "redacted_statements": len(case.redacted)}
        lang = self.cfg.output_lang if self.cfg.output_lang in _I18N else case.lang
        tr = _I18N[lang]
        initial, final, status = [], [], "ok"
        try:
            if not case.usable:
                status = "input_error"
                reason = "; ".join(case.errors) or "no sources"
                note = Note()
                note.sections["case_features"] = [Statement(tr["no_input"].format(reason=reason))]
                note.review_items.append({"type": "missing", "description": tr["no_input"].format(reason=reason), "source_ids": []})
                L = None
            else:
                L = build_ledger(case)
                try:
                    note, initial, final = self._generate_and_verify(case, L, variant, lang, stats, deadline, changes, log)
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
            note.review_items.append({"type": "verify", "description": tr["fb_review"].format(reason="internal error"), "source_ids": []})
        for sec in SECTIONS:
            if not note.sections[sec]:
                note.sections[sec] = [Statement(tr["fb_disc"] if status != "ok" and sec == "diagnostic_discussion" else
                                                tr["fb_plan"] if status != "ok" and sec == "treatment_plan" else tr["empty"])]
        log.update(status=status, calls=stats.calls, http_attempts=stats.http_attempts, retries=stats.retries,
                   prompt_tokens=stats.prompt_tokens, completion_tokens=stats.completion_tokens, total_tokens=stats.total_tokens,
                   llm_latency=round(stats.latency, 3), latency=round(time.monotonic() - t0, 3),
                   llm_errors=stats.errors[-3:], findings_initial=V.counts(initial), findings_final=V.counts(final))
        meta = {"status": status, "pipeline": variant, "prompt": prompt_fingerprint(), "calls": stats.calls}
        return CaseResult(to_record(note, case, self.cfg, meta), note, status, initial, final, log)

    # ---------------------------------------------------------------- internals
    def _generate_and_verify(self, case, L, variant, lang, stats, deadline, changes, log):
        tr = _I18N[lang]
        low_time = lambda: deadline is not None and deadline - time.monotonic() < self.cfg.time_reserve
        skip = lambda step: log.setdefault("time_budget_skipped", []).append(step)
        common = dict(lang=tr["lang"], cutoff=case.cutoff_raw if case.cutoff_raw not in (None, "") else tr["no_cutoff"],
                      sources=sources_block(case))
        system = load_prompt("system", lang)
        if variant == "S2" and low_time():
            skip("extract")
            problems = ""
        else:
            problems = self._extract(case, system, common, lang, stats, deadline, log) if variant == "S2" else ""
        if variant == "A0":
            user = fill(load_prompt("a0", lang), **common)
        else:
            user = fill(load_prompt("a1", lang), ledger=digest(L), problems=problems, changes=changes, **common)
        note = None
        for attempt in (1, 2):
            raw = self.client.chat(system, user, stats, deadline)
            try:
                note = note_from_model(parse_json_object(raw))
                break
            except ParseError as e:
                log.setdefault("parse_errors", []).append(str(e))
                if attempt == 2:
                    raise
                if low_time():
                    skip("regenerate")
                    raise
        log["raw_parse_retries"] = len(log.get("parse_errors", []))
        initial = V.verify_note(note, case, L)
        if variant in ("A0", "A1"):
            return note, initial, initial
        log["refs_dropped"] = V.safe_repair(note, case)
        findings = V.verify_note(note, case, L)
        actionable = [f for f in findings if f.severity in (V.HIGH, V.MEDIUM) and f.section in SECTIONS and f.index >= 0]
        mode = ("review" if variant == "A3" else
                "repair" if self.cfg.repair_call and any(f.severity == V.HIGH for f in findings) else None)
        if mode and low_time():
            skip(mode)
            mode = None
        if mode:
            try:
                user = fill(load_prompt(mode, lang), draft=_draft_json(note),
                            findings=json.dumps([{"section": f.section, "index": f.index, "issue": f.message} for f in actionable],
                                                ensure_ascii=False, indent=1), **common)
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
            obj = parse_json_object(self.client.chat(system, fill(load_prompt("extract", lang), **common), stats, deadline))
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
                lines.append(f'{i}. [{p.get("urgency", "routine")}] {p["problem"]}')
                lines += ev
        log["extract_quotes"] = {"kept": kept, "rejected": rejected}
        if not lines:
            return ""
        head = "模型提取的问题清单（引文已逐字核对）" if lang == "zh" else "Model-extracted problem list (quotes verified verbatim against the records)"
        return "\n<problem_list>\n" + head + "\n" + "\n".join(lines) + "\n</problem_list>\n"

    def _finalise(self, note, case, L: Ledger, findings, tr, lang):
        """Surface what could not be resolved, plus ledger-derived review items. No clinical rewriting."""
        unresolved = [f for f in findings if f.severity in (V.HIGH, V.MEDIUM)]
        if self.cfg.on_unresolved == "drop":
            for sec in SECTIONS:
                drop = {f.index for f in unresolved if f.section == sec and f.severity == V.HIGH}
                # may leave the section empty: run_case then inserts the "clinician input required" placeholder
                note.sections[sec] = [s for i, s in enumerate(note.sections[sec]) if i not in drop]
        have = " ".join(r["description"] for r in note.review_items)
        add = lambda typ, desc, ids=(): note.review_items.append({"type": typ, "description": desc, "source_ids": list(ids)})
        # one review item per statement; every high-severity finding is always surfaced, medium ones are capped
        merged: dict = {}
        for f in sorted(unresolved, key=lambda f: f.severity != V.HIGH):
            if f.code == "empty_section":
                continue
            msg = _MSG_ZH.get(f.code, f.message) if lang == "zh" else f.message
            m = merged.setdefault((f.section, f.text), {"high": False, "msgs": []})
            m["high"] |= f.severity == V.HIGH
            if msg not in m["msgs"]:
                m["msgs"].append(msg)
        n_medium = 0
        for (_, text), m in merged.items():
            if not m["high"]:
                n_medium += 1
                if n_medium > 8:
                    continue
            add("verify", tr["verify"].format(text=text[:200], msg="; ".join(m["msgs"])))
        for u in L.undocumented:
            if not re.search(_CORE_RX[u["key"]], have):
                add("missing", tr["undoc"].format(item=u[lang]))
        for c in L.conflicts[:5]:
            if c["term"] not in have.lower():
                add("conflict", tr["conflict"].format(term=c["term"], detail=c["detail"][:300]), c["sources"])
        if case.redacted or case.excluded_sources:
            add("verify", tr["cutoff"].format(n=len(case.redacted) + len(case.excluded_sources)))

    def _fallback(self, case, L, tr, reason) -> Note:
        note = Note()
        note.sections["case_features"] = [Statement(f.text, [f.sid]) for f in L.facts[:60]]
        note.sections["diagnostic_discussion"] = [Statement(tr["fb_disc"])]
        note.sections["treatment_plan"] = [Statement(tr["fb_plan"])]
        note.review_items.append({"type": "verify", "description": tr["fb_review"].format(reason=reason), "source_ids": []})
        return note


def _draft_json(note: Note) -> str:
    return json.dumps({sec: [{"index": i, "text": s.text, "sources": s.sources} for i, s in enumerate(note.sections[sec])]
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
                new = Statement(text.strip(), srcs or old.sources, old.kind, old.basis)
                f_new, f_old = V.check_statement(sec, idx, new, case, L), V.check_statement(sec, idx, old, case, L)
                if high(f_new) or bad(f_new) > bad(f_old):
                    reject("replace: new text fails verification")
                else:
                    stmts[idx] = new
                    res["applied"] += 1
        elif action == "add" and mode == "review":
            new = Statement(text.strip(), srcs, str(p.get("kind") or ""))
            if not new.text or (sec == "case_features" and not srcs) or bad(V.check_statement(sec, len(stmts), new, case, L)):
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
