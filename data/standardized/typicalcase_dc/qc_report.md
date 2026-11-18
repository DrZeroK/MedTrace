# TypicalCase-DC quality-control report

The case texts are journal case reports obtained under Tianchi terms; `cases.json` / `references.json` are kept only in the private repository and must not be published or redistributed.

- Labelled items: 2591; kept: 1319; multi-patient texts dropped: 9; exact duplicates: 2; corrupt or unlabelled: 1; unstructured: 1
- Excluded by the 2026-11-18 admission-input review: 1259
- Cases containing explicit dates (usable for chronology and cutoff tests): 262
- Identifier patterns redacted: {'already_masked_name': 10}

## Quality tiers

| tier | cases |
|---|---|
| B | 716 |
| A | 603 |

A = no post-admission cue and the record does not state the diagnosis: eligible for the diagnosis-hit metric. B = record states a diagnosis (for example a biopsy result): usable for fidelity metrics only. review_required = post-admission content suspected (operation findings, treatment response, discharge, follow-up, or a treatment/diagnosis sub-heading): excluded from every split until a clinician cuts the record at admission.

## Splits (cases with the same gold-diagnosis set share a split)

| split | cases |
|---|---|
| test | 657 |
| dev | 370 |
| validation | 292 |

Tier A per split:

| split | tier A cases |
|---|---|
| test | 300 |
| dev | 169 |
| validation | 134 |

## Completeness

| level | cases |
|---|---|
| complete | 1315 |
| partial | 4 |

## Complexity

| level | cases |
|---|---|
| high | 716 |
| medium | 602 |
| low | 1 |

## Gold diagnoses per case (5 = five or more)

| n | cases |
|---|---|
| 1 | 975 |
| 2 | 103 |
| 3 | 90 |
| 5 | 79 |
| 4 | 72 |
