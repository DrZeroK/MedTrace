"""CMB-Clin -> MedTrace standardized input schema + reference annotations + QC report.

    python -m data_pipeline.cmb_clin            # needs data/raw/cmb_clin (python -m data_pipeline.acquire cmb_clin)

Outputs in data/standardized/cmb_clin/:
  cases.json        list of {case_id, record_cutoff, sources[{source_id, content}]} - runnable with main.py
  references.json   per case: origin, classification, quality tier, split, expert reference answers, rule-derived facts
  manifest.json     counts, hashes, parameters
  qc_report.md      human-readable quality-control report

Principles
- Source text is preserved after line trimming, de-identification, and the case-specific punctuation errata below.
- The case title (which names the diagnosis) never enters the sources.
- Sections describing the course after admission (treatment, surgery, outcome) are withheld from the sources.
- Reference answers are the dataset's own expert solutions, copied unedited. Nothing is generated.
  Rule-derived items (measurements, negatives, differential names) are labelled `rule_derived_unreviewed`.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path

from medtrace.inputs import parse_case
from medtrace.ledger import build_ledger
from . import quality as Q

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "cmb_clin" / "CMB-Clin-qa.json"
OUT = ROOT / "data" / "standardized" / "cmb_clin"

# Confirmed by the project user on 2026-11-18. Keys restrict each change to its source.
PUNCTUATION_ERRATA = {
    "cmbclin-019-hpi": ("否认高血压，糖尿病史，否认手术病史。", "否认高血压、糖尿病史，否认手术病史。"),
    "cmbclin-026-hpi": ("大便色浅，不伴寒战高热，恶心呕吐", "大便色浅，不伴寒战高热、恶心呕吐"),
}


def correct_punctuation(source_id: str, content: str) -> str:
    if source_id not in PUNCTUATION_ERRATA:
        return content
    before, after = PUNCTUATION_ERRATA[source_id]
    if content.count(before) == 1 and after not in content:
        return content.replace(before, after, 1)
    if before not in content and content.count(after) == 1:
        return content
    raise ValueError(f"Expected one punctuation erratum anchor in {source_id}")

# top-level headings -> (slug, admission-time?)
HEADINGS = {
    "现病史": ("hpi", True), "病史摘要": ("hpi", True), "病史及体检": ("hpi", True), "病例资料": ("hpi", True),
    "既往史": ("pmh", True), "既往史、个人史": ("pmh", True), "个人史": ("pmh", True), "家族史": ("pmh", True),
    "体格检查": ("exam", True), "查体": ("exam", True),
    "辅助检查": ("aux", True), "实验室检查": ("lab", True), "影像学检查": ("img", True),
    "治疗经过": ("course", False), "治疗过程": ("course", False), "治疗方式": ("course", False),
    "病情变化": ("course", False), "体外循环实施": ("course", False), "体外循环实施答案": ("course", False),
}
_HEAD_RX = re.compile(r"^[\s　]*(?:[一二三四五六七八九十]+[、.．]\s*)?(" + "|".join(sorted(map(re.escape, HEADINGS), key=len, reverse=True)) + r")\s*[:：]?\s*$")
# sentence-level cues for content that may post-date admission (flag for human review; not auto-deleted)
_POST = re.compile(r"术后病理|术中(?:见|探查|冰冻|出血|诊断)|入院后[^。]{0,30}(?:治疗|手术|好转|加重|予)|出院|随访|病情好转|痊愈|切缘")
_POST_HISTORY_OK = re.compile(r"年前|月前|既往|外院|当地医院|曾")   # prior-history context: not post-admission
# the record itself states a diagnosis (legitimate admission information, but makes diagnosis-hit metrics trivial)
_DX_STATED = re.compile(r"病理(?:报告|结果|诊断|检查)?[^。]{0,12}(?:为|示|[:：])|确诊|明确诊断|诊断为")

# Some textbook case titles name a topic or a procedure, not a diagnosis; they cannot be scored as one.
_TITLE_NOT_DX = re.compile(r"管理|路径|评估和准备|相关性疾病|再植|术后")
_TITLE_SUFFIX = re.compile(r"(?:的诊疗|一例)$")
_Q_KINDS = [("differential", re.compile(r"鉴别")), ("diagnosis", re.compile(r"诊断")),
            ("plan", re.compile(r"治疗|处理|手术|决策|预防|措施")), ("investigation", re.compile(r"检查"))]
_DDX_ITEM = re.compile(r"(?:[①-⑳]|(?:^|\n)\s*(?:[（(]?\d{1,2}[)）.、．])?)\s*([\u4e00-\u9fffA-Za-z、/（）()]{2,24}?)\s*[:：]")
_DDX_STOP = re.compile(r"诊断|依据|鉴别|检查|治疗|此外|原则|分析|体征|病史|表现|处理|手术|答案|注意")


def split_sections(description: str):
    """Returns (kept, withheld): lists of {slug, heading, text}. Everything after the first post-admission heading is withheld."""
    sections, cur = [], {"slug": "hpi", "heading": "", "lines": [], "admission": True}
    for raw in description.replace("\r", "").split("\n"):
        m = _HEAD_RX.match(raw)
        if m:
            if cur["lines"] or cur["heading"]:
                sections.append(cur)
            slug, adm = HEADINGS[m.group(1)]
            cur = {"slug": slug, "heading": m.group(1), "lines": [], "admission": adm}
        elif raw.strip():
            cur["lines"].append(raw.strip())
    sections.append(cur)
    kept, withheld, cut = [], [], False
    for s in sections:
        cut = cut or not s["admission"]
        text = "\n".join(([s["heading"]] if s["heading"] else []) + s["lines"])
        body = "".join(l for l in s["lines"] if len(l) > 12 or re.search(r"\d", l))
        if cut:
            withheld.append({"heading": s["heading"], "chars": len(text), "reason": "post-admission course (treatment/outcome)"})
        elif len(body) < 15:
            if s["lines"] or s["heading"]:
                withheld.append({"heading": s["heading"], "chars": len(text), "reason": "empty section or figure caption only"})
        else:
            kept.append({"slug": s["slug"], "heading": s["heading"], "text": text})
    return kept, withheld


def question_kinds(q: str) -> list[str]:
    stem = q.split("\n")[0]
    if re.search(r"\n\s*A[.．、]", q):
        return ["multiple_choice"]
    kinds = []
    if "鉴别" in stem:
        kinds.append("differential")
    if "诊断" in stem.replace("鉴别诊断", ""):
        kinds.append("diagnosis")
    kinds += [k for k, rx in _Q_KINDS[2:] if rx.search(stem)]
    return kinds or ["other"]


def build() -> dict:
    raw_items = json.loads(RAW.read_text("utf-8"))
    raw_sha = hashlib.sha256(RAW.read_bytes()).hexdigest()
    keep = Q.reviewed_case_ids("cmb_clin", raw_sha)
    cases, refs, stats = [], [], collections.Counter()
    desc_by_id, seen_hash = {}, {}
    for item in raw_items:
        cid = f"cmbclin-{int(item['id']):03d}"
        desc = item.get("description") or ""
        issues = Q.corruption_issues(desc)
        h = Q.text_hash(desc)
        if h in seen_hash:
            stats["dropped_exact_duplicate"] += 1
            continue
        seen_hash[h] = cid
        if "too_short" in issues:
            stats["dropped_corrupt"] += 1
            continue
        clean, pii = Q.scrub_pii(desc)
        kept, withheld = split_sections(clean)
        if not kept:
            stats["dropped_no_admission_content"] += 1
            continue
        if cid not in keep:
            stats["excluded_input_review"] += 1
            continue
        title = item.get("title", "")
        chapter, _, disease = title.rpartition("案例分析-")
        chapter, disease = chapter.strip() or "未标注", _TITLE_SUFFIX.sub("", disease.strip() or title.strip())
        title_is_dx = not _TITLE_NOT_DX.search(disease)
        counts: dict = {}
        sources = []
        for s in kept:
            counts[s["slug"]] = counts.get(s["slug"], 0) + 1
            n = counts[s["slug"]]
            source_id = f"{cid}-{s['slug']}{n if n > 1 else ''}"
            sources.append({"source_id": source_id, "content": correct_punctuation(source_id, s["text"])})
        case = {"case_id": cid, "record_cutoff": None, "sources": sources}
        text = "\n".join(s["content"] for s in sources)

        flags = [f"corruption:{i}" for i in issues]
        post = [m.group() for m in _POST.finditer(text)
                if not _POST_HISTORY_OK.search(text[max(0, m.start() - 40):m.start()])]
        if post:
            flags.append("possible_post_admission_content:" + "/".join(sorted(set(post))[:4]))
        dx_stated = bool(_DX_STATED.search(text)) or (len(disease) >= 2 and disease in text)
        if dx_stated:
            flags.append("diagnosis_stated_in_record")
        if not title_is_dx:
            flags.append("title_is_not_a_diagnosis")
        if withheld and any(w["reason"].startswith("post") for w in withheld):
            flags.append("post_admission_sections_withheld")
        tier = "review_required" if post else "B" if (dx_stated or any(f.startswith(("post_", "corruption")) for f in flags)) else "A"

        ledger = build_ledger(parse_case(case, 0))
        measurements = [{"source_id": f.sid, "raw": n["raw"], "value": n["value"], "unit": n["unit"]} for f in ledger.facts for n in f.numerics]
        negatives = [{"source_id": f.sid, "text": f.text} for f in ledger.facts if f.neg_terms]
        pending = [{"source_id": f.sid, "text": f.text} for f in ledger.by_polarity("missing")]

        ref = {"diagnostic_discussion": [], "plan": [], "other": []}
        ddx_names = []
        for qa in item.get("QA_pairs") or []:
            kinds = question_kinds(qa["question"])
            sol = qa.get("answer", qa.get("solution", ""))      # the file uses "answer"; the README documents "solution"
            entry = {"question": qa["question"], "solution": sol, "kinds": kinds}
            if "multiple_choice" in kinds or kinds == ["other"]:
                ref["other"].append(entry)
            else:
                if {"diagnosis", "differential"} & set(kinds):
                    ref["diagnostic_discussion"].append(entry)
                if {"plan", "investigation"} & set(kinds):
                    ref["plan"].append(entry)
            if "differential" in kinds:
                seg = sol.split("鉴别诊断", 1)[-1] if "diagnosis" in kinds and "鉴别诊断" in sol else sol
                ddx_names += [n for n in (m.group(1).strip("、/") for m in _DDX_ITEM.finditer(seg)) if not _DDX_STOP.search(n)]
        slugs = sorted(counts)
        refs.append({
            "case_id": cid,
            "origin": {"dataset": "CMB-Clin", "item_id": item["id"], "title": title, "license": "Apache-2.0",
                       "url": "https://github.com/FreedomIntelligence/CMB", "raw_sha256": raw_sha},
            "classification": {"specialty_chapter": chapter, "disease_label": disease, "disease_label_status": "textbook_case_title",
                               "document_type": "textbook teaching case (admission-style)", "sections_present": slugs,
                               "completeness": "complete" if {"hpi", "exam"} <= set(slugs) and {"aux", "lab", "img"} & set(slugs) else "partial",
                               "complexity": Q.complexity(len(text), len(measurements), len(sources)),
                               "n_chars": len(text), "n_measurements": len(measurements), "n_negative_statements": len(negatives)},
            "quality": {"tier": tier, "flags": flags, "withheld_sections": withheld, "pii": pii},
            "split": None,
            "reference": {"provenance": "textbook_expert", "status": "verified_by_source (CMB-Clin expert-consensus solutions, copied unedited)",
                          "note": "answers to case questions, not a written progress note; they may draw on information from withheld post-admission sections",
                          "case_features": None, "diagnostic_discussion": ref["diagnostic_discussion"], "plan": ref["plan"],
                          "evidence": None, "review_items": None, "other_qa": ref["other"]},
            "derived": {"label_status": "rule_derived_unreviewed", "dx_metric_eligible": not dx_stated and len(disease) >= 2 and title_is_dx,
                        "measurements": measurements, "negatives": negatives, "pending": pending,
                        "reference_differentials": list(dict.fromkeys(n for n in ddx_names if n and n != disease))},
        })
        cases.append(case)
        desc_by_id[cid] = text
        stats["kept"] += 1

    # near-duplicates and leakage-safe splits (same disease label or near-duplicate cluster => same split)
    groups = Q.near_duplicate_groups(desc_by_id)
    group_of = {r["case_id"]: "dx:" + r["classification"]["disease_label"] for r in refs}
    for g in groups:
        key = "nd:" + min(g)
        for cid in g:
            group_of[cid] = key
    splits = Q.assign_splits({r["case_id"]: group_of[r["case_id"]] for r in refs if r["quality"]["tier"] != "review_required"})
    for r in refs:
        r["split"] = splits.get(r["case_id"], "excluded_pending_review")
        r["quality"]["near_duplicate_of"] = next(([c for c in g if c != r["case_id"]] for g in groups if r["case_id"] in g), [])

    if {case["case_id"] for case in cases} != keep or len(cases) != len(keep):
        raise ValueError("Rebuilt case IDs do not match the reviewed input list")
    OUT.mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", "utf-8")
    dump("cases.json", cases)
    dump("references.json", refs)
    c = lambda key: dict(collections.Counter(key(r) for r in refs).most_common())
    manifest = {"dataset": "cmb_clin", "raw_sha256": raw_sha, "raw_items": len(raw_items),
                "punctuation_errata": sorted(PUNCTUATION_ERRATA), "counts": dict(stats),
                "tiers": c(lambda r: r["quality"]["tier"]), "splits": c(lambda r: r["split"]),
                "completeness": c(lambda r: r["classification"]["completeness"]), "complexity": c(lambda r: r["classification"]["complexity"]),
                "specialty_chapters": c(lambda r: r["classification"]["specialty_chapter"]),
                "near_duplicate_groups": groups, "split_salt": "medtrace-v1", "split_ratios": {"dev": 0.4, "validation": 0.2, "test": 0.4},
                "pii_hits": dict(sum((collections.Counter(r["quality"]["pii"]) for r in refs), collections.Counter())),
                "dx_metric_eligible": sum(r["derived"]["dx_metric_eligible"] for r in refs),
                "with_reference_discussion": sum(bool(r["reference"]["diagnostic_discussion"]) for r in refs),
                "with_reference_plan": sum(bool(r["reference"]["plan"]) for r in refs),
                "withheld_post_admission_sections": sum(any(w["reason"].startswith("post") for w in r["quality"]["withheld_sections"]) for r in refs)}
    dump("manifest.json", manifest)
    _report(manifest, refs)
    return manifest


def _report(m: dict, refs: list) -> None:
    t = lambda d: "\n".join(f"| {k} | {v} |" for k, v in d.items())
    review = [r for r in refs if r["quality"]["tier"] == "review_required"]
    L = ["# CMB-Clin quality-control report", "",
         "Generated by `python -m data_pipeline.cmb_clin`. Source: FreedomIntelligence/CMB (Apache-2.0), textbook teaching cases.", "",
         f"- Raw items: {m['raw_items']}; kept: {m['counts'].get('kept', 0)}; exact duplicates dropped: {m['counts'].get('dropped_exact_duplicate', 0)}; "
         f"corrupt/too short dropped: {m['counts'].get('dropped_corrupt', 0)}; no admission content: {m['counts'].get('dropped_no_admission_content', 0)}",
        f"- Excluded by the 2026-11-18 admission-input review: {m['counts']['excluded_input_review']}",
         f"- Near-duplicate groups (character 5-gram Jaccard >= 0.6): {len(m['near_duplicate_groups'])}",
         f"- Cases with post-admission sections withheld from the sources: {m['withheld_post_admission_sections']}",
         f"- PII scan: {m['pii_hits'] or 'no identifiers found'} (`already_masked_name` = names the publisher had already masked, left as is)",
         f"- Reference answers: diagnosis/differential for {m['with_reference_discussion']} cases, treatment/investigation for {m['with_reference_plan']}; "
         "reference Case Features text: none (not provided by the dataset, not generated)",
         f"- Cases where an automatic diagnosis-hit metric is meaningful (record does not state the diagnosis): {m['dx_metric_eligible']}", "",
         "## Quality tiers", "", "| tier | cases |", "|---|---|", t(m["tiers"]), "",
         "A = admission-time content only. B = usable, but the record states a diagnosis and/or post-admission sections were withheld. "
         "review_required = a sentence inside an admission section may describe events after admission; excluded from all splits until a clinician decides.", "",
         "## Splits (group-wise by disease label and near-duplicate cluster; deterministic hash, salt `medtrace-v1`)", "", "| split | cases |", "|---|---|", t(m["splits"]), "",
         "`dev` may be used for prompt development; `validation` for choosing between variants; `test` only for the final, pre-registered comparison.", "",
         "## Completeness", "", "| level | cases |", "|---|---|", t(m["completeness"]), "",
         "## Complexity", "", "| level | cases |", "|---|---|", t(m["complexity"]), "",
         "## Specialty (textbook chapter)", "", "| chapter | cases |", "|---|---|", t(m["specialty_chapters"]), "",
         "## Cases needing clinician review before use", ""]
    L += [f"- `{r['case_id']}` {r['origin']['title']}: {'; '.join(r['quality']['flags'])}" for r in review] or ["- none"]
    (OUT / "qc_report.md").write_text("\n".join(L) + "\n", "utf-8")


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=1))
