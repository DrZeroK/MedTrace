"""External test of MedTrace's negation rules against CHIP-CDEE (CBLUE): real Chinese EMR sentences in which
every clinical finding carries a polarity label (肯定 / 否定 / 不确定).

    # place the Tianchi download at data/raw/cblue/CHIP-CDEE/ (account + terms required; never committed)
    python -m data_pipeline.cdee_negation        # -> data/standardized/chip_cdee/negation_report.md (aggregates only)

Protocol: rules may be tuned on CHIP-CDEE *train* only; CHIP-CDEE *dev* is the held-out report set (the official
test labels are withheld by the organisers). A finding is scored when its name occurs exactly once in the text
and has a single gold polarity; the rule predicts "negated" when that occurrence lies inside a negation span.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from medtrace import textutil as T

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "cblue" / "CHIP-CDEE"
OUT = ROOT / "data" / "standardized" / "chip_cdee"


def evaluate(items: list) -> dict:
    c = collections.Counter()
    for x in items:
        sents = T.split_sentences(x["text"])
        gold = collections.defaultdict(set)
        for e in x.get("event", []):
            gold[e["core_name"]].add((e.get("tendency") or "").strip())
        for name, tends in gold.items():
            occ = [s for s in sents if name in s]
            if len(tends) != 1 or len(occ) != 1 or occ[0].count(name) != 1:
                c["skipped"] += 1
                continue
            g = next(iter(tends))
            pred = not T.term_positive_in(name.lower(), occ[0])
            if g == "不确定":
                c["uncertain_total"] += 1
                c["uncertain_sentence_has_cue"] += T.has_uncertain_cue(occ[0])
                c["uncertain_predicted_negated"] += pred
            else:
                c[("tp" if pred else "fn") if g == "否定" else ("fp" if pred else "tn")] += 1
    p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
    r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
    return {"scored": c["tp"] + c["fn"] + c["fp"] + c["tn"], "tp": c["tp"], "fn": c["fn"], "fp": c["fp"], "tn": c["tn"],
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "skipped_ambiguous_or_repeated": c["skipped"], "uncertain_total": c["uncertain_total"],
            "uncertain_sentence_has_cue": c["uncertain_sentence_has_cue"], "uncertain_predicted_negated": c["uncertain_predicted_negated"]}


def main() -> dict:
    res = {s: evaluate(json.loads((RAW / f"CHIP-CDEE_{s}.json").read_text("utf-8"))) for s in ("train", "dev")}
    OUT.mkdir(parents=True, exist_ok=True)
    row = lambda s: (f"| {s} | {res[s]['scored']} | {res[s]['precision']:.3f} | {res[s]['recall']:.3f} | {res[s]['f1']:.3f} | "
                     f"{res[s]['fp']} | {res[s]['fn']} | {res[s]['uncertain_sentence_has_cue']}/{res[s]['uncertain_total']} |")
    (OUT / "negation_report.md").write_text("\n".join([
        "# Negation rules vs CHIP-CDEE polarity labels", "",
        "Aggregates only (the dataset is distributed under Tianchi terms and is not redistributed here). "
        "Rules were tuned on `train`; `dev` is held out.", "",
        "| split | findings scored | precision | recall | F1 | false negated | missed negation | 不确定 findings whose sentence carries an uncertainty cue |",
        "|---|---|---|---|---|---|---|---|", row("train"), row("dev"), "",
        "Scored = finding name occurs once and has one gold polarity. Uncertainty is detected at sentence level only, "
        "so the last column is a coverage indication, not an accuracy figure.", ""]), "utf-8")
    return res


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1))
