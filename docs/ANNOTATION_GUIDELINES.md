# Annotation guidelines for MedTrace reference data

## 1. Label provenance — every label carries one of these, and they are never mixed silently

| `status` | Meaning | May be used as ground truth? |
|---|---|---|
| `verified_by_source` | Copied unedited from the dataset's own expert/textbook answer | Yes, for what it answers (note its `note` field) |
| `expert_reviewed` | Written or corrected by a project clinician, with reviewer id and date | Yes |
| `rule_derived_unreviewed` | Produced by a deterministic rule (measurements, negatives, differential names) | Only as a screening proxy; report as proxy |
| `model_generated_unreviewed` | Drafted by any LLM | **No.** Never scored against, never counted as reference, until promoted by review |

Promotion to `expert_reviewed` requires: the reviewer read the sources, corrected the text, and recorded
`reviewer`, `date`, and whether changes were made. Disagreements between two reviewers go to the Clinical Lead.

## 2. Standardized case (input)

- `case_id`, `record_cutoff`, `sources[{source_id, content}]`; `source_id` unique across the whole dataset.
- Source text is verbatim. Do not correct typos, units or OCR damage (for example `×109/L`); the verifier reads
  such forms. Do not translate or summarise.
- `record_cutoff` is the latest time at which everything in `sources` was known. If the origin has no dates
  (textbook cases) it is `null` — do not invent one.
- **Leakage rules.** Never in `sources`: the case title or any label naming the diagnosis; discharge or final
  diagnoses; operations, intra-operative findings, post-operative pathology; treatment given after admission and
  the response to it; outcome, follow-up. Past history before admission stays (previous surgery, outside-hospital
  treatment and results available on admission).
- If one sentence mixes admission-time and later content, do not edit it: mark the case `review_required` and let
  a clinician decide whether to split, drop the sentence, or drop the case.
- A record that itself states the diagnosis (for example a biopsy result on admission) is legitimate; flag it
  `diagnosis_stated_in_record` so diagnosis-hit metrics skip it.

## 3. Writing a reference initial progress note (`expert_reviewed`)

Fields: `case_features`, `diagnostic_discussion`, `plan`, `evidence`, `review_items`.

- **case_features** — only what the sources state. Values with units exactly as recorded, each with its time
  point. Keep negatives negative. Undocumented items are "未记录", never normal. One statement per line, each with
  the `source_id`(s) that support it.
- **diagnostic_discussion** — by problem, most urgent first: supporting findings, findings against, graded
  conclusion (明确 / 可能性大 / 可能 / 不能除外), 2–4 patient-specific differentials each with for/against, and
  what is still unknown. A diagnosis the record does not establish is never written as confirmed.
- **plan** — investigations, treatment, monitoring; every item answers a documented problem or a stated
  uncertainty and reads as a proposal. Check against documented allergy, medication, organ function, pregnancy,
  anticoagulation.
- **evidence** — `{statement, source_ids}` for every major factual statement.
- **review_items** — missing information that matters for a decision, conflicts between sources, anything the
  clinician must verify.
- Also list `must_not`: the statements that would be a severe error for this case (see `CLINICAL_RUBRIC.md`).
- The annotator may consult the textbook answer but must not import facts from withheld post-admission sections.

## 4. Fact-level annotation (for extraction and verification tests)

Per fact: `source_id`, verbatim `text`, `category` (complaint, history, exam, lab, imaging, medication, allergy),
`polarity` (positive / negative / pending-or-not-done / uncertain), `value`, `unit`, `time` if stated.
Polarity follows the text, not clinical expectation: "未扪及肿块" is negative for that examination only.

## 5. Splits

Assigned by `data_pipeline.quality.assign_splits` (deterministic hash of the disease label / near-duplicate
cluster). `dev`: prompt and rule development. `validation`: choosing between variants. `test`: one final
pre-registered comparison. A case never moves between splits; new cases get their split from the same function.
