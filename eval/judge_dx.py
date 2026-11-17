"""Diagnosis scoring by a judge model, for runs produced by eval.run_external.

    python -m eval.judge_dx eval/results/<run> [--workers 6]

Why: verbatim matching of gold diagnosis names badly undercounts (first real run: 39% by string match, while a
manual read found most "misses" were correct diagnoses under another name, e.g. gold "手部急性化脓性细菌感染" vs
note "化脓性屈肌腱鞘炎"). The judge sees only the gold diagnosis list and the note's Diagnostic Discussion and labels
each gold diagnosis:
    primary       stated as the working / most likely diagnosis (synonym, or a more specific or equivalent term)
    differential  mentioned only as a differential or as "cannot be excluded"
    absent        not mentioned
The judge model is set with JUDGE_MODEL (default qwen-plus: cheaper than, and different from, the generator, to limit
self-preference). This is a development-time proxy; it never runs in the submission pipeline. Spot-check its labels
(`judge_dx.json` keeps every verdict with its reason) and confirm headline numbers by blinded clinician review.
"""
from __future__ import annotations

import copy
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from medtrace.config import load_config
from medtrace.llm import CallStats, LLMClient, LLMError
from medtrace.note import ParseError, parse_json_object
from .run_ablation import md_table

SYSTEM = "你是一名严谨的临床医学评审专家。只输出一个JSON对象，不要输出其他内容。"
PROMPT = """请判断一份首次病程记录的“拟诊讨论”是否给出了标准诊断。

标准诊断（逐条判断）：
{gold}

拟诊讨论：
<<<
{disc}
>>>

对每一条标准诊断给出一个标签：
- "primary"：讨论将其作为初步诊断/最可能诊断提出（允许同义词、规范名称不同、更具体的分型，或“可能性大”“考虑”等分级表述）。
- "differential"：仅作为鉴别诊断、“不能除外”或待排诊断出现。
- "absent"：未提及，或仅给出明显更笼统的描述（如只写“占位性病变，性质待查”而标准诊断是具体肿瘤）。
不要因为讨论内容丰富而放宽标准；只依据文字本身判断。

输出：{{"judgements": [{{"gold": "标准诊断原文", "label": "primary|differential|absent", "reason": "不超过30字"}}]}}"""


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    run = Path(argv[0])
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 4
    cfg = copy.copy(load_config())
    cfg.model = os.environ.get("JUDGE_MODEL", "qwen-plus")
    cfg.max_calls_per_case, cfg.extra_body = 1, {}
    client = LLMClient(cfg)
    gold = {}
    for item in json.loads((run / "cases_used.json").read_text("utf-8")):
        ref = item["annotation"].get("gold", {})
        if ref.get("eligible"):
            gold[item["case"]["case_id"]] = ref["diagnoses"]
    if not gold:
        sys.exit("this run has no gold diagnoses in cases_used.json (re-run eval.run_external with the current code)")
    cache_path = run / "judge_dx.json"
    cache = json.loads(cache_path.read_text("utf-8")) if cache_path.exists() else {}
    jobs = []
    for f in sorted(run.glob("outputs_*.json")):
        v = f.stem.split("_", 1)[1]
        for rec in json.loads(f.read_text("utf-8")):
            key = f"{v}|{rec['case_id']}"
            if rec["case_id"] in gold and key not in cache:
                jobs.append((key, gold[rec["case_id"]], rec["diagnostic_discussion"]))

    def judge(job):
        key, g, disc = job
        try:
            raw = client.chat(SYSTEM, PROMPT.format(gold="\n".join(f"{i + 1}. {x}" for i, x in enumerate(g)), disc=disc[:4000]), CallStats())
            js = parse_json_object(raw).get("judgements") or []
            labels = [str(j.get("label", "")).lower() for j in js][:len(g)]
            if len(labels) != len(g) or any(l not in ("primary", "differential", "absent") for l in labels):
                return key, {"error": "malformed judge output", "raw": raw[:300]}
            return key, {"labels": labels, "reasons": [str(j.get("reason", ""))[:60] for j in js][:len(g)], "gold": g}
        except (LLMError, ParseError) as e:
            return key, {"error": f"{type(e).__name__}: {e}"[:200]}

    with ThreadPoolExecutor(workers) as ex:
        for key, res in ex.map(judge, jobs):
            if "error" not in res:
                cache[key] = res
            else:
                print("judge failed:", key, res["error"], file=sys.stderr)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")
    fallback = {(r["variant"], r["case_id"]) for r in csv.DictReader(open(run / "per_case.csv", encoding="utf-8")) if r["status"] != "ok"}
    rows = []
    for v in sorted({k.split("|")[0] for k in cache}):
        items = [(k.split("|", 1)[1], c) for k, c in cache.items() if k.startswith(v + "|")]
        n_dx = sum(len(c["labels"]) for _, c in items)
        prim = sum(l == "primary" for _, c in items for l in c["labels"])
        diff = sum(l == "differential" for _, c in items for l in c["labels"])
        rows.append({"variant": v, "cases_judged": len(items), "of_which_fallback_notes": sum((v, cid) in fallback for cid, _ in items),
                     "cases_any_gold_primary_%": round(100 * sum("primary" in c["labels"] for _, c in items) / len(items), 1),
                     "cases_all_gold_primary_%": round(100 * sum(all(l == "primary" for l in c["labels"]) for _, c in items) / len(items), 1),
                     "gold_dx_primary_%": round(100 * prim / n_dx, 1), "gold_dx_primary_or_differential_%": round(100 * (prim + diff) / n_dx, 1),
                     "gold_dx_total": n_dx})
    table = md_table(rows)
    (run / "judge_dx_summary.md").write_text(f"# Judge-scored diagnosis accuracy (`{cfg.model}` as judge)\n\n{table}\n\n"
                                             "Proxy metric from a judge model; fallback notes contain no discussion and count as absent.\n", "utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
