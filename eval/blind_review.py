"""Blinded expert review tooling.

  export:  python -m eval.blind_review export eval/results/<run> [--reviewers R1,R2] [--seed 0]
           -> review/packet.md (randomised, variant hidden), review/scores_<reviewer>.csv (to fill in), review/key.json (keep sealed)
  score:   python -m eval.blind_review score eval/results/<run>
           -> review/review_summary.md: per-variant metrics, inter-rater agreement, disagreements for adjudication

Score sheet columns (one row per blinded note):
  critical_error      0/1   at least one severe clinical error (see docs/CLINICAL_RUBRIC.md)
  error_categories    semicolon-separated rubric codes, e.g. "F2;R1"
  facts_wrong         number of incorrect factual statements in Case Features
  facts_assessed      number of factual statements assessed
  refs_supported / refs_assessed     evidence references that semantically support their statement
  reasoning_score     1-5   plan_score 1-5
"""
from __future__ import annotations

import csv
import json
import random
import statistics as st
import sys
from pathlib import Path

COLS = ["blind_id", "critical_error", "error_categories", "facts_wrong", "facts_assessed", "refs_supported",
        "refs_assessed", "reasoning_score", "plan_score", "comments"]
HERE = Path(__file__).parent


def export(run: Path, reviewers: list[str], seed: int) -> None:
    src = run / "cases_used.json" if (run / "cases_used.json").exists() else HERE / "cases.json"   # external-dataset runs carry their own cases
    cases = {c["case"]["case_id"]: c for c in json.loads(src.read_text("utf-8"))}
    items = []
    for f in sorted(run.glob("outputs_*.json")):
        variant = f.stem.split("_", 1)[1]
        for rec in json.loads(f.read_text("utf-8")):
            items.append((variant, rec))
    rng = random.Random(seed)
    rng.shuffle(items)
    out = run / "review"
    out.mkdir(exist_ok=True)
    key, md = {}, ["# Blinded review packet", "", "Score every note independently using docs/CLINICAL_RUBRIC.md. Do not try to infer which system produced a note.", ""]
    for n, (variant, rec) in enumerate(items, 1):
        bid = f"N{n:03d}"
        key[bid] = {"variant": variant, "case_id": rec["case_id"]}
        case = cases[rec["case_id"]]["case"]
        md += [f"## {bid}  (case {rec['case_id']}, cutoff {case.get('record_cutoff')})", "", "### Records"]
        md += [f"**[{s['source_id']}]** {s['content']}\n" for s in case["sources"]]
        md += ["### Case Features", rec["case_features"], "", "### Diagnostic Discussion", rec["diagnostic_discussion"], "",
               "### Diagnostic and Treatment Plan", rec["treatment_plan"], "", "### Evidence references"]
        md += [f"- {e['statement'][:140]} -> {e['source_ids']}" for e in rec["evidence"]]
        md += ["", "### Review items"] + [f"- ({r['type']}) {r['description']}" for r in rec["review_items"]] + ["", "---", ""]
    (out / "packet.md").write_text("\n".join(md), "utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=1), "utf-8")
    for r in reviewers:
        with open(out / f"scores_{r}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLS)
            w.writerows([[bid] + [""] * (len(COLS) - 1) for bid in key])
    print(f"exported {len(key)} blinded notes to {out}")


def _kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    if not n:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = (sum(a) / n) * (sum(b) / n) + (1 - sum(a) / n) * (1 - sum(b) / n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def score(run: Path) -> None:
    out = run / "review"
    key = json.loads((out / "key.json").read_text("utf-8"))
    sheets = {}
    for f in sorted(out.glob("scores_*.csv")):
        rows = {r["blind_id"]: r for r in csv.DictReader(open(f, encoding="utf-8")) if r.get("critical_error", "") != ""}
        if rows:
            sheets[f.stem.split("_", 1)[1]] = rows
    if not sheets:
        sys.exit("no completed score sheets found")
    num = lambda r, c: float(r[c]) if r.get(c, "") not in ("", None) else None
    variants = sorted({k["variant"] for k in key.values()})
    lines = ["# Blinded review summary", "", f"Reviewers: {', '.join(sheets)}", "",
             "| variant | notes scored | critical error rate | fact precision | attribution accuracy | reasoning (1-5) | plan (1-5) |", "|---|---|---|---|---|---|---|"]
    for v in variants:
        rs = [r for s in sheets.values() for bid, r in s.items() if key[bid]["variant"] == v]
        if not rs:
            continue
        # a note counts as critical if ANY reviewer marks it critical (conservative, pending adjudication)
        crit_notes = {bid for s in sheets.values() for bid, r in s.items() if key[bid]["variant"] == v and int(float(r["critical_error"]))}
        n_notes = len({bid for s in sheets.values() for bid in s if key[bid]["variant"] == v})
        fw, fa = sum(num(r, "facts_wrong") or 0 for r in rs), sum(num(r, "facts_assessed") or 0 for r in rs)
        rsu, ra = sum(num(r, "refs_supported") or 0 for r in rs), sum(num(r, "refs_assessed") or 0 for r in rs)
        mean = lambda c: (lambda xs: f"{st.mean(xs):.2f}" if xs else "n/a")([x for x in (num(r, c) for r in rs) if x is not None])
        lines.append(f"| {v} | {n_notes} | {len(crit_notes)}/{n_notes} ({100 * len(crit_notes) / n_notes:.0f}%) | "
                     f"{f'{100 * (1 - fw / fa):.1f}%' if fa else 'n/a'} | {f'{100 * rsu / ra:.1f}%' if ra else 'n/a'} | {mean('reasoning_score')} | {mean('plan_score')} |")
    cats = {}
    for s in sheets.values():
        for bid, r in s.items():
            for c in filter(None, (x.strip() for x in r.get("error_categories", "").split(";"))):
                cats.setdefault(key[bid]["variant"], {}).setdefault(c, 0)
                cats[key[bid]["variant"]][c] += 1
    lines += ["", "## Error categories (count of reviewer marks)", ""] + [f"- {v}: {dict(sorted(c.items()))}" for v, c in sorted(cats.items())]
    names = list(sheets)
    if len(names) >= 2:
        a, b = sheets[names[0]], sheets[names[1]]
        common = sorted(set(a) & set(b))
        ka = [int(float(a[i]["critical_error"])) for i in common]
        kb = [int(float(b[i]["critical_error"])) for i in common]
        dis = [i for i, x, y in zip(common, ka, kb) if x != y]
        lines += ["", "## Inter-rater agreement", "", f"Cohen's kappa on critical_error ({names[0]} vs {names[1]}, n={len(common)}): {_kappa(ka, kb):.2f}",
                  f"Notes needing adjudication (critical-error disagreement): {', '.join(dis) or 'none'}"]
    (out / "review_summary.md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("export", "score"):
        sys.exit(__doc__)
    run = Path(sys.argv[2])
    if sys.argv[1] == "export":
        args = sys.argv[3:]
        rv = args[args.index("--reviewers") + 1].split(",") if "--reviewers" in args else ["R1", "R2"]
        sd = int(args[args.index("--seed") + 1]) if "--seed" in args else 0
        export(run, rv, sd)
    else:
        score(run)
