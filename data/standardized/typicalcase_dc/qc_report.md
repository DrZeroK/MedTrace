# TypicalCase-DC quality-control report

The case texts are journal case reports obtained under Tianchi terms; `cases.json` / `references.json` are kept only in the private repository and must not be published or redistributed.

- Labelled items: 2591; kept: 2578; multi-patient texts dropped: 9; exact duplicates: 2; corrupt or unlabelled: 1; unstructured: 1
- Cases containing explicit dates (usable for chronology and cutoff tests): 664
- Identifier patterns redacted: {'already_masked_name': 11}

## Quality tiers

| tier | cases |
|---|---|
| B | 1026 |
| A | 836 |
| review_required | 716 |

A = no post-admission cue and the record does not state the diagnosis: eligible for the diagnosis-hit metric. B = record states a diagnosis (for example a biopsy result): usable for fidelity metrics only. review_required = post-admission content suspected (operation findings, treatment response, discharge, follow-up, or a treatment/diagnosis sub-heading): excluded from every split until a clinician cuts the record at admission.

## Splits (cases with the same gold-diagnosis set share a split)

| split | cases |
|---|---|
| test | 940 |
| excluded_pending_review | 716 |
| dev | 524 |
| validation | 398 |

Tier A per split:

| split | tier A cases |
|---|---|
| test | 425 |
| dev | 232 |
| validation | 179 |

## Completeness

| level | cases |
|---|---|
| complete | 2283 |
| partial | 295 |

## Complexity

| level | cases |
|---|---|
| high | 1614 |
| medium | 963 |
| low | 1 |

## Gold diagnoses per case (5 = five or more)

| n | cases |
|---|---|
| 1 | 1884 |
| 2 | 194 |
| 5 | 182 |
| 3 | 175 |
| 4 | 143 |
