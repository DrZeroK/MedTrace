"""Calibrate the rubric judge's adjudication step against clinician labels.

    python -m eval.adjudication_calibration export --input input.json --judge-dirs DIR [DIR ...] --out DIR
    python -m eval.adjudication_calibration score --dir DIR

export reads major_errors.json written by eval.rubric_judge in each judge dir and writes, in a fixed shuffled order:
    labels.csv   one row per major error, to fill in (UTF-8 with BOM so Excel/Numbers open it); the adjudication
                 verdict is NOT shown, so the label is independent of it
    packet.md    per item: the error as the first-pass judge stated it, then the case records and the full note
    key.json     item -> run, case and adjudication verdict (keep closed until labelling is done)
score compares the filled-in labels with the first-pass judge (which asserted every error) and the adjudication.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

LABELS = ("成立", "不成立", "不确定")
MEANING = {"harmful": "可能造成严重伤害的建议（整例记0分）", "serious_omission": "严重遗漏（整例记0分）",
           "fabricated_key_fact": "编造关键事实（整例封顶50%）", "key_number_or_chronology": "关键数值或时序错误（整例封顶50%）"}
COLS = ["item_id", "case_id", "错误类型", "记录原文", "资料原文", "原评审理由", "你的判断（成立/不成立/不确定）", "备注"]


def export(a) -> int:
    cases = {c["case_id"]: c for c in json.loads(Path(a.input).read_text("utf-8"))}
    items = []
    for d in a.judge_dirs:
        items += json.loads((Path(d) / "major_errors.json").read_text("utf-8"))
    random.Random(a.seed).shuffle(items)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    notes: dict = {}
    key, packet = {}, ["# 重大错误复核标注包", "",
                       "请对每条判断：按竞赛评分规则，这条“重大错误”是否成立。成立=确属该类重大错误，应扣至0分或封顶50%；"
                       "不成立=属于常规或可接受处理、上下文已处理、或只是一般性不足。判断填入 labels.csv。", ""]
    with open(out / "labels.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for n, e in enumerate(items, 1):
            iid = f"E{n:02d}"
            if e["output"] not in notes:
                notes[e["output"]] = {r["case_id"]: r for r in json.loads(Path(e["output"]).read_text("utf-8"))}
            m = notes[e["output"]][e["case_id"]]["medical_record"]
            adj = e.get("adjudication") or {}
            key[iid] = {"run": e["run"], "case_id": e["case_id"], "type": e["type"],
                        "adjudicated": "confirmed" if adj.get("confirmed") is True else
                                       "overturned" if adj.get("confirmed") is False else "not_reviewed",
                        "adjudication_reason": adj.get("reason", "")}
            w.writerow([iid, e["case_id"], e["type"], e["note_quote"], e["source_quote"], e["reason"], "", ""])
            src = "\n".join(f"- [{s['source_id']}] {s['content']}" for s in cases[e["case_id"]]["sources"])
            packet += [f"## {iid}　{e['case_id']}　{MEANING.get(e['type'], e['type'])}", "",
                       f"**记录原文**：{e['note_quote']}", "", f"**资料原文**：{e['source_quote']}", "",
                       f"**原评审理由**：{e['reason']}", "", "<details><summary>入院资料与完整首程</summary>", "",
                       "**入院资料**", "", src, "", "**病例特点**", "", m["case_features"], "",
                       "**拟诊讨论**", "", m["diagnostic_discussion"], "", "**诊疗计划**", "", m["plan"], "",
                       "**待核事项**", "", "\n".join(f"- {x}" for x in m["review_items"]) or "[]", "", "</details>", ""]
    (out / "packet.md").write_text("\n".join(packet), "utf-8")
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(items)} items -> {out}/labels.csv, packet.md, key.json")
    return 0


def score(a) -> int:
    d = Path(a.dir)
    key = json.loads((d / "key.json").read_text("utf-8"))
    with open(d / "labels.csv", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get(COLS[6]) or "").strip() in LABELS]
    if not rows:
        print("no labelled rows yet", file=sys.stderr)
        return 1
    pairs = [((r[COLS[6]].strip()), key[r["item_id"]]["adjudicated"], key[r["item_id"]]["type"]) for r in rows]
    decided = [p for p in pairs if p[0] != "不确定" and p[1] != "not_reviewed"]
    c = Counter((h, adj) for h, adj, _ in decided)
    real = c[("成立", "confirmed")] + c[("成立", "overturned")]
    lines = [f"# 复核机制校准（{len(rows)} 条已标注，{len(decided)} 条可比较）", "",
             f"- 初评“重大错误”经标注成立的比例（初评精确率）：{real}/{len(decided)}",
             f"- 复核与标注一致：{c[('成立', 'confirmed')] + c[('不成立', 'overturned')]}/{len(decided)}",
             f"- 复核错误推翻（标注成立、复核推翻，即过松）：{c[('成立', 'overturned')]}",
             f"- 复核错误维持（标注不成立、复核维持，即过严）：{c[('不成立', 'confirmed')]}", "",
             "| 错误类型 | 标注成立 | 复核维持 | 一致 | 过松 | 过严 |", "|---|---|---|---|---|---|"]
    for t in sorted({p[2] for p in decided}):
        sub = Counter((h, adj) for h, adj, tt in decided if tt == t)
        lines.append(f"| {t} | {sub[('成立', 'confirmed')] + sub[('成立', 'overturned')]} | "
                     f"{sub[('成立', 'confirmed')] + sub[('不成立', 'confirmed')]} | "
                     f"{sub[('成立', 'confirmed')] + sub[('不成立', 'overturned')]} | {sub[('成立', 'overturned')]} | "
                     f"{sub[('不成立', 'confirmed')]} |")
    (d / "calibration.md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--input", required=True)
    e.add_argument("--judge-dirs", nargs="+", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("score")
    s.add_argument("--dir", required=True)
    a = ap.parse_args(argv)
    return export(a) if a.cmd == "export" else score(a)


if __name__ == "__main__":
    sys.exit(main())
