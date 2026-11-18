"""TypicalCase-DC (CBLUE) -> MedTrace standardized cases + gold diagnoses + QC report.

    # place the Tianchi download at data/raw/cblue/TypicalCase-DC/ (account + terms required)
    python -m data_pipeline.typicalcase_dc

The corpus is 2,591 labelled published case reports already written in admission-record sections
(个人信息 / 主诉 / 现病史 / 既往史 / 个人史 / 家族史 / 体格检查 / 检查检验) with gold diagnoses and distractor options.

It is distributed under Tianchi terms and the texts are journal case reports, so `cases.json` and
`references.json` are kept only in the private repository and must not be published or redistributed
outside it.

Leakage control: the article title (names the diagnosis) is never used; multi-patient texts are dropped; a case
whose text contains post-admission cues (operation findings, treatment response, discharge, follow-up) or
treatment/diagnosis sub-headings is tiered `review_required` and kept out of every split; a case whose record
states a gold diagnosis or a pathology diagnosis is tier B (usable, but excluded from the diagnosis-hit metric).
Nothing is edited out of a sentence automatically.
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
RAW = ROOT / "data" / "raw" / "cblue" / "TypicalCase-DC" / "TypicalCase-DC_train.jsonl"
OUT = ROOT / "data" / "standardized" / "typicalcase_dc"

SECTIONS = {"个人信息": "hx", "主诉": "hx", "现病史": "hx", "既往史": "past", "个人史": "past", "家族史": "past", "个人家族史": "past",
            "婚育史": "past", "月经史": "past", "月经婚育史": "past", "体格检查": "exam", "专科检查": "exam", "检查检验": "tests", "辅助检查": "tests"}
_HEAD = re.compile(r"^[\s*#\-]*(?:[一二三四五六七八九十]+[、.．])?\s*(" + "|".join(sorted(SECTIONS, key=len, reverse=True)) + r")\s*\**\s*[:：]?\s*\**\s*(.*)$")
_MULTI = re.compile(r"病例\s*[1-9一二三]\s*[:：]|例\s*[12]\s*[:：]|患者\s*[12]\s*[:：]")
_POST = re.compile(r"术后病理|术中(?:见|探查|冰冻|出血|诊断|所见)|入院后[^。\n]{0,40}(?:治疗|手术|好转|加重|予|行)|出院|随访|病情好转|痊愈|治疗后|化疗后|术后第|切缘|转归")
_HIST_OK = re.compile(r"年前|月前|周前|天前|既往|外院|当地医院|曾|[12]\d{3}\s*年")
_SUBHEAD_LEAK = re.compile(r"(?m)^[\s*#\-]*(?:治疗|治疗经过|治疗过程|诊断|最终诊断|出院诊断|手术|转归|随访)\s*\**\s*[:：]")
_DX_STATED = re.compile(r"病理(?:报告|结果|诊断|检查|会诊)?[^。\n]{0,16}(?:为|示|[:：]|符合)|确诊|明确诊断|诊断为|符合[^。\n]{2,20}(?:瘤|癌|病|炎)")
_norm = lambda s: re.sub(r"[\s（）()“”\"'、，,。/]", "", s or "").lower()


def split_sections(text: str) -> dict:
    out: dict = collections.OrderedDict()
    cur = None
    for raw in text.replace("\r", "").split("\n"):
        m = _HEAD.match(raw)
        if m:
            cur = SECTIONS[m.group(1)]
            line = f"{m.group(1)}：{m.group(2).strip()}" if m.group(2).strip() else m.group(1)
            out.setdefault(cur, []).append(line)
        elif raw.strip() and cur:
            out[cur].append(raw.rstrip())
        elif raw.strip():
            out.setdefault("hx", []).append(raw.rstrip())
    return out


def build() -> dict:
    items = [json.loads(l) for l in RAW.read_text("utf-8").splitlines() if l.strip()]
    raw_sha = hashlib.sha256(RAW.read_bytes()).hexdigest()
    stats, seen = collections.Counter(), set()
    cases, refs = [], []
    for it in items:
        text = it.get("text") or ""
        if Q.corruption_issues(text, 120) or not it.get("answer"):
            stats["dropped_corrupt_or_unlabelled"] += 1
            continue
        h = Q.text_hash(text)
        if h in seen:
            stats["dropped_exact_duplicate"] += 1
            continue
        seen.add(h)
        if _MULTI.search(text):
            stats["dropped_multi_patient"] += 1
            continue
        clean, pii = Q.scrub_pii(text)
        secs = split_sections(clean)
        if "hx" not in secs or len(secs) < 2:
            stats["dropped_unstructured"] += 1
            continue
        cid = f"tcdc-{it['id']}"
        sources = [{"source_id": f"{cid}-{slug}", "content": "\n".join(lines)} for slug, lines in secs.items()]
        case = {"case_id": cid, "record_cutoff": None, "sources": sources}
        body = "\n".join(s["content"] for s in sources)
        gold = [a.strip() for a in it["answer"] if a.strip()]
        flags = []
        post = sorted({m.group()[:6] for m in _POST.finditer(body) if not _HIST_OK.search(body[max(0, m.start() - 40):m.start()])})
        if post:
            flags.append("possible_post_admission_content:" + "/".join(post[:4]))
        if _SUBHEAD_LEAK.search(body):
            flags.append("treatment_or_diagnosis_subheading")
        nb = _norm(body)
        dx_stated = any(_norm(g) in nb for g in gold) or bool(_DX_STATED.search(body))
        if dx_stated:
            flags.append("diagnosis_stated_in_record")
        tier = "review_required" if (post or "treatment_or_diagnosis_subheading" in flags) else "B" if dx_stated else "A"
        L = build_ledger(parse_case(case, 0))
        n_meas = sum(len(f.numerics) for f in L.facts)
        refs.append({
            "case_id": cid,
            "origin": {"dataset": "TypicalCase-DC (CBLUE)", "item_id": it["id"], "source_url": it.get("url"), "raw_sha256": raw_sha,
                       "terms": "Tianchi terms; private repository only; do not redistribute"},
            "classification": {"document_type": "published case report in admission-record sections", "question_type": it.get("question_type"),
                               "n_gold_diagnoses": len(gold), "sections_present": list(secs),
                               "completeness": "complete" if {"hx", "exam", "tests"} <= set(secs) and not re.search(r"体格检查[:：]\s*无。?\s*$", body, re.M) else "partial",
                               "complexity": Q.complexity(len(body), n_meas, len(sources) + (len(gold) > 1) * 2),
                               "n_chars": len(body), "n_measurements": n_meas, "n_dates": len(L.dates)},
            "quality": {"tier": tier, "flags": flags, "pii": pii},
            "split": None,
            "reference": {"provenance": "published_case_report", "status": "verified_by_source (gold diagnoses of the CBLUE task, copied unedited)",
                          "diagnoses": gold, "distractor_options": [v.strip() for v in it["options"].values() if v.strip() not in gold],
                          "case_features": None, "diagnostic_discussion": None, "plan": None, "evidence": None, "review_items": None},
            "derived": {"label_status": "rule_derived_unreviewed", "dx_metric_eligible": tier == "A",
                        "measurements": [{"source_id": f.sid, "raw": n["raw"], "value": n["value"], "unit": n["unit"]} for f in L.facts for n in f.numerics]},
        })
        cases.append(case)
        stats["kept"] += 1
    # same gold-diagnosis set => same split, so a disease picture seen during prompt development is never tested on
    group = {r["case_id"]: "dx:" + "|".join(sorted(_norm(g) for g in r["reference"]["diagnoses"])) for r in refs}
    splits = Q.assign_splits({c: g for c, g in group.items() if next(r for r in refs if r["case_id"] == c)["quality"]["tier"] != "review_required"},
                             ratios=(("dev", 0.3), ("validation", 0.2), ("test", 0.5)))
    for r in refs:
        r["split"] = splits.get(r["case_id"], "excluded_pending_review")
    OUT.mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", "utf-8")
    dump("cases.json", cases)
    dump("references.json", refs)
    c = lambda key, rows=refs: dict(collections.Counter(key(r) for r in rows).most_common())
    usable = [r for r in refs if r["split"] != "excluded_pending_review"]
    m = {"dataset": "typicalcase_dc", "raw_sha256": raw_sha, "raw_items": len(items), "counts": dict(stats), "tiers": c(lambda r: r["quality"]["tier"]),
         "splits": c(lambda r: r["split"]), "tier_A_by_split": c(lambda r: r["split"], [r for r in usable if r["quality"]["tier"] == "A"]),
         "completeness": c(lambda r: r["classification"]["completeness"]), "complexity": c(lambda r: r["classification"]["complexity"]),
         "gold_diagnoses_per_case": c(lambda r: min(r["classification"]["n_gold_diagnoses"], 5)),
         "cases_with_dates": sum(r["classification"]["n_dates"] > 0 for r in refs),
         "pii_hits": dict(sum((collections.Counter(r["quality"]["pii"]) for r in refs), collections.Counter())),
         "split_salt": "medtrace-v1", "split_ratios": {"dev": 0.3, "validation": 0.2, "test": 0.5}}
    dump("manifest.json", m)
    t = lambda d: "\n".join(f"| {k} | {v} |" for k, v in d.items())
    (OUT / "qc_report.md").write_text("\n".join([
        "# TypicalCase-DC quality-control report", "",
        "The case texts are journal case reports obtained under Tianchi terms; `cases.json` / `references.json` are "
        "kept only in the private repository and must not be published or redistributed.", "",
        f"- Labelled items: {m['raw_items']}; kept: {stats['kept']}; multi-patient texts dropped: {stats['dropped_multi_patient']}; "
        f"exact duplicates: {stats['dropped_exact_duplicate']}; corrupt or unlabelled: {stats['dropped_corrupt_or_unlabelled']}; unstructured: {stats['dropped_unstructured']}",
        f"- Cases containing explicit dates (usable for chronology and cutoff tests): {m['cases_with_dates']}",
        f"- Identifier patterns redacted: {m['pii_hits'] or 'none'}", "",
        "## Quality tiers", "", "| tier | cases |", "|---|---|", t(m["tiers"]), "",
        "A = no post-admission cue and the record does not state the diagnosis: eligible for the diagnosis-hit metric. "
        "B = record states a diagnosis (for example a biopsy result): usable for fidelity metrics only. "
        "review_required = post-admission content suspected (operation findings, treatment response, discharge, follow-up, or a "
        "treatment/diagnosis sub-heading): excluded from every split until a clinician cuts the record at admission.", "",
        "## Splits (cases with the same gold-diagnosis set share a split)", "", "| split | cases |", "|---|---|", t(m["splits"]), "",
        "Tier A per split:", "", "| split | tier A cases |", "|---|---|", t(m["tier_A_by_split"]), "",
        "## Completeness", "", "| level | cases |", "|---|---|", t(m["completeness"]), "",
        "## Complexity", "", "| level | cases |", "|---|---|", t(m["complexity"]), "",
        "## Gold diagnoses per case (5 = five or more)", "", "| n | cases |", "|---|---|", t(m["gold_diagnoses_per_case"]), ""]), "utf-8")
    return m


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=1))
