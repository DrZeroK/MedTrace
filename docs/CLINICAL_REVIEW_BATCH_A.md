# Clinical review and sign-off: Batch A output wording and rendering

**English** | [简体中文](CLINICAL_REVIEW_BATCH_A.zh-CN.md)

Status: **APPROVED** — project owner approval received 2026-11-19; formal signature waived by the owner

Snapshot date: 2026-11-19

Base commit: `f885545` plus the Batch A working-tree changes listed in section 4

Review owner: MedTrace team

Reviewer / approver: project owner (direct approval; formal clinician signature waived by the owner on 2026-11-19)

## 1. Purpose and scope

This review covers exactly two output-layer changes:

1. Official narrative sections are rendered as prose instead of a numbered list.
2. A definitive diagnostic statement that the records do not support is surfaced as a medium-severity review item with clean wording.

This is **not** a clinical validation of generated notes, the prompts, the model, or other verifier findings. It does not authorize clinical use without clinician review.

Examples below use the public demo case or synthetic text. No competition case or real patient record is included.

## 2. Change 1: official narrative sections are prose

What changes:

- `medical_record.case_features`, `medical_record.diagnostic_discussion` and `medical_record.plan` join their statements into one paragraph.
- Order, wording, evidence and review items are unchanged. No clinical text is rewritten.
- Legacy/development output keeps the numbered list.

Before (illustrative):

```
1. 成人，乏力2周，活动后心悸。
2. 结膜苍白，双下肢轻度水肿。
3. 血红蛋白82 g/L，肌酐185 μmol/L。
```

After (official output):

```
成人，乏力2周，活动后心悸。结膜苍白，双下肢轻度水肿。血红蛋白82 g/L，肌酐185 μmol/L。
```

English example:

Before:

```
1. 68-year-old man with fever and cough for 3 days.
2. Temp 38.6 °C, HR 104 bpm.
```

After:

```
68-year-old man with fever and cough for 3 days. Temp 38.6 °C, HR 104 bpm.
```

Reviewer questions:

1. Is the prose sample readable and unambiguous for a senior clinician?
2. Does any sentence boundary or punctuation change meaning? The renderer only removes numbering/separators; it does not rewrite text.
3. Do you prefer prose, line breaks without numbers, or the current numbered list? If line breaks are preferred, the text can stay unchanged and only numbering is removed.
4. Are there specialty-specific formatting requirements, for example one clinical problem per paragraph?

Decision received (2026-11-19): **Approve**.

Formal sign-off:

- [ ] Approve
- [ ] Approve with edits
- [ ] Reject

Required edits or conditions:

## 3. Change 2: diagnostic overconfidence is surfaced

Trigger condition:

- A diagnostic discussion statement contains definitive wording: `确诊`, `明确诊断`, `诊断明确`, `诊断已明确`, `诊断成立`, `确定诊断`, `可确诊`; English `confirmed`, `definite/definitely`, `definitive`, `diagnostic of`, `certainly`.
- None of those certainty cues appears anywhere in the records.
- The finding is medium severity and does not rewrite the note.

Action (revised 2026-11-19): add one clinician-facing review item per flagged statement, using this exact wording:

- Chinese: `记录中初步诊断的确定程度可能高于资料支持，请复核初步诊断表述。`
- English: `The note states the working diagnosis more definitively than the records support; review the working diagnosis.`

Clinical decision (2026-11-19): **Approved with edits.** Required edit: add `初步诊断` / `working diagnosis` wording. The revised wording above supersedes the first draft.

Trigger example (public demo DEMO001):

- Records: `入院初步判断为贫血及肾功能异常，原因待查；血红蛋白82 g/L，肌酐185 μmol/L。`
- Draft discussion: `贫血诊断明确。`
- Expected: the review item above appears; the note is not automatically rewritten.

Anti-trigger example:

- Records: `贫血诊断明确；血红蛋白82 g/L。`
- Draft discussion: `贫血诊断明确。`
- Expected: no `overconfident` item.

Known limitation: the check is statement-level and generic. If any source contains a certainty cue, the check is suppressed for the whole case. It does not distinguish the primary diagnosis from a differential diagnosis. This is deliberate to reduce false positives, but the reviewer should decide whether it is clinically acceptable.

Reviewer questions:

1. Is the wording accurate, non-judgmental and actionable?
2. Is `复核诊断表述` the right action, or should it say `核对诊断依据` / `请结合资料复核诊断`?
3. Should the trigger apply to any diagnostic statement in the discussion, or only the primary diagnosis?
4. Should this be a review item (current behavior), or should it trigger a rewrite/removal? The pipeline does not automatically rewrite clinical wording today.
5. Are there false-positive scenarios that should be excluded, for example guideline-defined diagnostic criteria or pathology-confirmed diagnoses?
6. Is medium severity appropriate? It is surfaced for review but does not block the record.

Decision:

- [ ] Approve
- [ ] Approve with edits
- [ ] Reject

Required edits or conditions:

## 4. Reviewed snapshot

Base commit: `f885545` plus uncommitted Batch A changes on 2026-11-19. The review applies only to the exact hashes below.

- `medtrace/note.py`: `803c880031c4d98d43ded9a5b261fcc4fec63a035b6f8881846de3cdece1c9bd`
- `medtrace/pipeline.py`: `0f52650c8ba7ce169a1a702818d76a7b172c583b9c77ca0da8f3e2fa21dabad3`
- `medtrace/verify.py`: `720dd47d6d5ded818a464f2a4487aef91a777aeec9277795c00d573f1a2656bd`
- `medtrace/textutil.py`: `ef94f57e8d7acee540bd8d4869b773d4608e21b1e66c788a0fd35c267fa05a60`
- `tests/test_medtrace.py`: `518f11ccfe2e04d078a41e759e35b63beec9e29a364ddc3fecfde4fa54954a12`

This snapshot supersedes the first 2026-11-19 snapshot: the Change 2 wording was revised per clinical feedback.

Test status at this snapshot: 201 tests pass on Python 3.11.16.

Post-approval note (2026-11-19): Batch B later added reasoning/cached-token logging in `pipeline.py`/`llm.py`/`runner.py` and `scripts/api_acceptance.py`. None of those changes alters the approved renderer or the overconfident wording; the exact approved string remains frozen in `tests/test_medtrace.py::test_overconfident_is_visible_with_clean_wording`. The hashes above are the Batch A approval snapshot.

If the approved wording or renderer changes, this approval is invalid and the new wording must be reviewed again.

## 5. Approval record

Approver: project owner

Date: 2026-11-19

Decision: **Approved all Batch A changes.** Change 1 approved; Change 2 approved with edits (add `初步诊断` / `working diagnosis` wording).

Formal signature: **waived by the project owner.** No separate signed copy is required for this internal approval.

Scope: the two output-layer changes described in section 1, applied to the code snapshot in section 4. This is not a clinical validation of generated notes and does not authorize clinical use without clinician review.

Approval checkboxes:

- [x] Approve Change 1
- [x] Approve Change 2 with edits
- [ ] Reject

Signature fields (not required for this approval):

Reviewer name / credentials / department:

Signature / signed copy hash:

Conflict of interest:

Optional second reviewer:

## 6. Handling after sign-off

- If approved: this document is marked `APPROVED`; no separate signed copy is required because the project owner waived the formal signature. Freeze the wording in regression tests.
- If edits are required: apply them to a new snapshot, update the hashes, and review again. Do not edit the signed snapshot.
- If rejected: revert to the numbered list and/or remove the overconfident review item, and record the reason.
- The repository is private, but minimize personal data in any committed signature page.