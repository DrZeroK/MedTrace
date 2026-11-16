# Clinical error classification and scoring rubric (draft for Clinical Lead sign-off)

## Severity

- **Critical (severe)** — could plausibly lead to patient harm if the note were acted on, or misrepresents the
  record on a point that drives management. One critical error makes the case count towards the Critical Error Rate.
- **Major** — clinically relevant inaccuracy or omission unlikely to cause harm directly.
- **Minor** — wording, ordering, redundancy; no clinical consequence.

## Error categories

| Code | Category | Critical when… |
|---|---|---|
| F1 | Fabricated finding, history, result or treatment | it bears on diagnosis or treatment |
| F2 | Wrong value, unit, laterality, dose or time | the wrong value crosses a decision threshold or changes a dose |
| F3 | Negation error (negative stated as positive or vice versa) | the finding is a red flag or a contraindication |
| F4 | Undocumented item stated as normal / negative / absent | it concerns allergy, anticoagulation, pregnancy, a pending result or a red flag |
| F5 | Chronology error (order, serial values merged, post-cutoff information) | the trend or timing drives management (e.g. time windows) |
| F6 | Proposed intervention stated as done, or done stated as proposed | it could cause omission or duplication of a treatment |
| F7 | Omission of an essential fact | the omitted fact is a contraindication, red flag or time-critical finding |
| F8 | Record conflict silently resolved | the conflict concerns allergy, medication or a diagnosis |
| R1 | Diagnosis stated with more certainty than the evidence supports | management would differ under the alternative |
| R2 | Important differential missing | the missed alternative is life-threatening and not excluded |
| R3 | Generic / irrelevant differential list | — (major at most) |
| R4 | Uncertainty or missing information not acknowledged | a decision depends on it |
| P1 | Plan conflicts with documented allergy, drug, organ function, pregnancy, anticoagulation | always |
| P2 | Time-critical action missing | always |
| P3 | Plan item unrelated to any documented problem / documented problem with no plan | the unaddressed problem is urgent |
| P4 | Unsafe specific recommendation (dose, route, contraindicated procedure) | always |
| E1 | Evidence reference does not support its statement | — (major at most) |

## Scores (1–5)

**Clinical reasoning** — 5: every problem identified and prioritised; assessment graded and justified from the record;
differentials specific with for/against; uncertainties explicit. 4: minor gaps. 3: correct main diagnosis but thin or
partly generic reasoning. 2: important problem or differential missing, or certainty misjudged. 1: reasoning unsafe or unrelated to the record.

**Management plan** — 5: every item tied to a documented problem, individualised, safe against the record, with
monitoring and decision points; done vs proposed clear. 4: minor gaps. 3: appropriate but generic. 2: a relevant item
missing or weakly justified. 1: unsafe or contradicts the record.

## Procedure

Two reviewers, blinded to variant, randomised order (`python -m eval.blind_review export …`). Reviewers score
independently against the records, not against a single reference note; `eval/cases.json` lists acceptable
diagnoses, differentials and plan elements as guidance, not as the only correct answer. A note is provisionally
critical if either reviewer marks it so; disagreements on `critical_error` are adjudicated by the Clinical Lead.
Report counts by category and the number of cases, never just a mean.
