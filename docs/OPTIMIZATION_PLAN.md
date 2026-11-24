# MedTrace optimisation plan: scoring as high as the rubric allows

Status: draft for team decision, 2026-11-23. F1 and a first version of E1 are implemented (see §8).

## 1. What the score actually rewards

The official rubric (consolidated guide, Appendix 2) scores each case on five clinical dimensions, plus two
algorithm components (reproducibility, and improvement validation). Two rules dominate everything else:

| Rule | Effect on a case | What triggers it |
|---|---|---|
| Missing/unreadable output or a missing narrative section | **0** | timeout, parse failure, empty section |
| Fabricated key fact, or a chronology/number error that changes clinical judgment | **capped at 50%** | one wrong value is enough |
| Recommendation that could cause serious harm, or a serious omission | **0** (after third-expert review) | e.g. a drug the patient is allergic to |

So the order of work is: first make capped and zero cases impossible, then raise clinical depth, then polish
structure and attribution. A note that reads beautifully and contains one corrupted vital sign scores at most
half.

"A perfect score" can't be promised: medical judges score against reference points we do not see, and
reasonable clinicians disagree. The realistic target is **0 capped cases, 0 zero cases, and full marks on every
dimension we can check by rule**, with diagnostic and plan quality pushed as far as the designated model allows.

## 2. Where we stand (measured 2026-11-21, local qwen3:8b, thinking off, A2, prompt v2)

| Set | Cases | Success | Median / max latency | Output speed | High-severity findings |
|---|---:|---:|---|---|---|
| Synthetic SYN001–010 | 10 | 10/10 | 33.8 s / 39.8 s | ~42 tok/s | 3 in 2 cases |
| Practice set (临床智录_练习病历数据集) | 8 | 8/8 | 40.2 s / 50.7 s | ~35 tok/s | 0 (1 medium real error) |

Errors seen that would trigger the 50% cap if a judge noticed them:

1. **Digit corruption** in 2 of 10 synthetic cases: source `心率112次/分` → note `心率11、`; `SpO₂ 93%` →
   `SpO₂ 9、3%`. Confirmed present in the raw model reply, so it is the model, not our code. The verifier
   flags it, but the wrong value **stays in the narrative**; only a review item is added.
2. **Invented qualifier/threshold** (P05): `血压持续高于160/100mmHg` — the record has 180/110 and 162/105, never
   "持续高于160/100". Flagged as medium.
3. **Relabelled value, not caught** (P05): `GLU 10.8mmol/L` written as `空腹血糖10.8`. The number exists in the
   source, so the lexical verifier passes it.

Earlier real-model runs (docs/REPORT.md §2.6–2.7, PHASE1_RESULTS) add: diagnosis hits are flat across A0/A1/A2;
the repair call fired only on false alarms; and one case in test30 produced no valid JSON after two generations,
a **zero-score case**.

## 3. What others do, and what we take from it

| Source | Idea | Use here |
|---|---|---|
| Optum, "Verification Turns Capability Gaps into Routing Decisions" (arXiv 2610.19169) | A fixed verifier stack plus a refinement loop raised a 4B model's acceptance from 26.8% to near frontier level; remaining errors were mostly facts in the wrong section | Strongest evidence that **verification + targeted regeneration** matters most when the model is weak. Supports F1/F2 and a gated repair, not a blanket second call |
| Chain-of-Verification (Dhuliawala et al., ACL Findings 2024) | Draft → plan check questions → answer each **independently** → revise; factored answering stops the model copying its own errors | Our deterministic ledger already answers "is this value in the record" for free. Use the model only for checks rules can't do (qualifiers, attribution of value to test/time) |
| Granular fact-checking for healthcare LLMs (arXiv 2512.16189); proposition-level LLM-free checking | Split note and record into atomic claims and compare one-to-one | Same direction as our ledger; extend it from numbers to **value + label + qualifier triples** (F2) |
| Extract → retrieve → summarise oncology pipeline (CL4Health 2025) | Filter hallucinated facts **before** writing | Matches S2 (model problem list with verbatim quotes); worth testing with the rubric judge (D1) |
| LCDS discharge-summary system (arXiv 2507.05319) | Logic-controlled generation with source attribution and expert review | Supports keeping attribution deterministic and showing reviewers structured review items |
| Universal Self-Consistency (Chen et al., 2023) | Sample N answers, let the model pick the most consistent | Candidate for the **working diagnosis only** (short output, cheap); not for the whole note (D2) |
| Constrained decoding studies (arXiv 2611.10845, 2609.23742, JSONSchemaBench) | Grammar enforcement removes structural failures; accuracy cost on Qwen3-8B was small (~1.2 pt) | Use `json_schema` once the organiser publishes the supported subset; it attacks the zero-score parse failure (F4) |
| "LLM-induced note bloat and diagnostic overcall" (arXiv 2611.10601) | Long, overconfident notes degrade downstream reading | Keeps the v2 length budget and the overconfidence check; supports the anti-boilerplate work (S3) |

No open-source system targets the Chinese 首次病程记录 task directly; the closest published work is a paediatric
pneumonia model (arXiv 2409.02608) whose evaluation resembles first ward-round notes.

## 4. The plan

Each item lists the rubric dimension it serves, the change, how we measure it, and the acceptance rule. The
pre-registered selection rule (REPORT.md §5) still applies: a more complex variant ships only if it beats the
simpler one on held-out cases without losing coverage and within the call/time limits.

### Phase 0 — a scoreboard that matches the rubric (prerequisite)

Without this, every later change is judged by proxies (literal diagnosis match, numeric coverage) that the
judges do not use.

- **E1 Rubric judge.** Score each note on the five Appendix 2 dimensions, apply the 50% cap and zero rules, and
  report "capped cases" and "zero cases" as headline numbers. A clinician writes 3–6 reference points per case
  for the 8 practice cases and ~20 synthetic cases, the way the judges will. Judge model: the strongest model we
  available (the cloud endpoint is allowed for all case sets). Calibrate once against two-person human scoring of 10 notes; keep the judge
  only if it agrees with humans on which cases are capped.
- **E2 Fixed splits.** Practice set (8, closest to official format) as the primary dev set; synthetic 100 split
  60 dev / 40 holdout; CMB-Clin test30 stays untouched until the final confirmation.
- **E3 Model matrix.** Every experiment runs on (a) local qwen3:8b as the low-end floor and (b) the designated
  service when available, thinking off and on. A change that only helps the large model is fine; one that hurts
  the small one is a warning about robustness.

### Phase 1 — make capped and zero cases impossible (highest value)

- **F1 Number fidelity by construction** (dim 1). For each `number_not_in_source` finding: if removing the
  inserted punctuation gives a value present in the same source near the same label (`9、3%` → `93%` next to
  `SpO₂`), repair it deterministically and log the repair. Otherwise remove the statement from the narrative and
  keep the review item (today `ON_UNRESOLVED=drop` drops every high finding; narrow it to number findings so
  verifier false alarms elsewhere cannot delete good text). Acceptance: 0 unrepaired number findings in narrative
  on all dev runs; no regression on the CMB-Clin 1,629-sentence verbatim guard.
- **F2 Value–label–qualifier binding** (dim 1). Extend the ledger from "this number appears" to "this number
  belongs to this test, time point and qualifier". New checks: qualifier words (空腹/餐后/持续/最高/平均/首次/复查)
  attached to a value must appear with that value in the source; comparison phrases (高于/超过/低于 + value) in
  patient statements must match a recorded value, otherwise they must be `basis: knowledge`. Would have caught
  both P05 errors. Acceptance: catches the P05 pair and a set of seeded perturbations; ≤1 new false alarm per 10
  practice notes.
- **F3 Planned vs performed** (dim 3; a rubric failure mode named explicitly). Rule check on plan statements for
  completed-action wording (已予/已行/已给予/予…后) without a matching record entry; `c_unsupported_completed`
  wording already exists. Acceptance: seeded cases caught, 0 false alarms on practice notes.
- **F4 No zero-score cases** (all dims). (a) Send `response_format: json_schema` once the organiser publishes
  the supported subset, falling back to `json_object`, then text; measure parse failures and content quality
  with and without. (b) Make the timeout/parse fallback score above zero: today it emits ledger excerpts plus
  "需医生书写" placeholders, which a judge may treat as a missing section. Replace the placeholder discussion
  and plan with a short deterministic problem list and investigations drawn from the ledger, clearly labelled.
  Acceptance: 0 cases without three substantive sections across all dev runs, including forced-timeout tests.
- **F5 Harm screen** (zero rule). Deterministic check that no plan item names a drug or class matching a recorded
  allergy, and that anticoagulant/thrombolytic advice is flagged when the record mentions bleeding or recent
  surgery. High severity: drop or rewrite as a conditional, plus a review item. Acceptance: seeded cases caught.

### Phase 2 — clinical depth (dims 2 and 3, most of the per-case points)

- **D1 Reason first, write second.** Call 1 (short JSON): problem list ranked by urgency, each with supporting
  facts (verbatim quotes, checked as in S2), against-points, 2–3 case-specific differentials with the
  discriminating test. Call 2: write the note from that plan with thinking off. Try thinking **on** for call 1
  only, where reasoning helps and the output is short. Compare S2/D1 vs A2 on dim 2 and dim 3 of the rubric
  judge. Cost: ~2× latency; see §5.
- **D2 Self-consistency on the working diagnosis.** Sample 3 short problem lists (fixed seeds 42/43/44,
  temperature ~0.7) and choose the most consistent (majority or USC). Ship only if dim 2 improves on holdout
  and the call budget allows it.
- **D3 Offline knowledge for differentials.** The 21-book BM25 textbook index exists but is outside the
  submission. Retrieve criteria for the top 2 problems and pass them as `basis: knowledge` hints. Risk: the
  rubric penalises generic textbook lists, so judge on "case-specific differential" specifically. Requires
  resource registration and the published size limit. Ship only with a measured gain.
- **D4 Plan completeness per problem.** Every problem gets investigation + management + monitoring (what, how
  often, what would change management). Rule check that monitoring items exist and that each plan item cites
  a problem. Most of this is already in prompt v2; add the check and a one-shot regeneration only when it fails.

### Phase 3 — structure and attribution (dims 4 and 5)

- **S1 Evidence entries.** Pick 3–5 evidence entries deterministically: chief complaint, the key abnormal
  values, and one or two `inference` entries for the main inference boundaries, each with verified source IDs.
  Removes model variance from a dimension rules can fully control.
- **S2 Review items that matter.** A small presentation-specific checklist (chest pain → ECG, troponin series;
  pregnancy → fetal monitoring, liver function; fever → cultures, PCT) generates "not documented" items only
  when the item is actually absent. Keep the cap of 6, rank by effect on management.
- **S3 Anti-boilerplate.** Detect sentences reused across cases within a batch (n-gram overlap) and the
  practice set; tighten the prompt where generic text recurs. Judges score "not directly reusable for an
  unrelated case".
- **S4 Prompt tuning for the small model.** Add one Chinese worked example (from synthetic data, not DEMO001
  verbatim, to avoid copying), and test whether listing the ledger values as "copy exactly" slots reduces digit
  corruption further.

### Phase 4 — the two algorithm components

- **R1 Improvement validation** (scored separately). For every shipped change: the problem it solves, a
  baseline-vs-improved table on the same public practice cases, and its cost (calls, latency, tokens). The
  ablation tooling (`eval/run_ablation.py`) exists; extend it to output the rubric-judge table.
- **R2 Reproducibility.** Already strong (pinned deps, fixed seed, run logs, hash manifest). Keep every new
  resource pinned and registered; rerun the clean-environment package test after each phase.

## 5. Time and call budget

Measured on qwen3:8b: one call ≈ 34–51 s per case. The official limits are not yet published (Q5).

| Design | Calls/case | Est. time/case (8B) | 100 cases, 1 worker |
|---|---:|---:|---:|
| A2 today | 1 | ~40 s | ~67 min |
| D1 (reason + write) | 2 | ~70–80 s | ~2 h |
| D1 + D2 (3 short samples) | 4 | ~100 s | ~2.8 h |

Our own 3600 s batch ceiling is already tight for 100 practice-length cases on the 8B floor. So: make every
optional stage deadline-aware (the `time_reserve` mechanism exists), order stages by value (F-checks are free,
D1 next, D2 last), and set `WORKERS` from the organiser's concurrency limit: vLLM batches parallel requests well,
while local Ollama mostly serialises them.

## 6. Order of work

1. E1–E2 (scoreboard) — nothing else can be judged without it.
2. F1, F2, F3, F5 (deterministic, no extra calls, directly remove caps).
3. F4 (zero-score avoidance), as soon as the json_schema subset is published.
4. D1, then D4; D2 and D3 only if budget and holdout results allow.
5. S1–S4.
6. R1 write-up from the accumulated ablation tables; freeze ≥48 h before the deadline.

## 7. Open questions for the organiser or team

- Designated model and version, thinking default, and the json_schema subset (Q5/Q14 follow-ups).
- Per-case and batch time limits, call and retry budgets, concurrency.
- Whether official inputs include the doctor's 初步诊断, as the practice set does. Today the pipeline drops a
  copied diagnosis list at the top of the discussion; confirm this matches what judges expect.
- A clinician to write reference points (E1) and do the calibration scoring.

## 8. Progress

### 2026-11-23: F1 number fidelity, E1 rubric judge (first version)

- **F1** (`verify.repair_numbers`, A2/S2/A3 only): rejoins a punctuation-split value when the joined form with its
  neighbouring characters is in the records and the split form is not; otherwise removes the clause holding a
  value the records lack, and adds one clinician-facing review item. It never empties Case Features: if every
  statement would go, the draft is kept and the finding stays visible.
- **E1** (`eval/rubric_judge.py`): judge scores the five dimensions 0–10; the zero and 50%-cap rules are applied
  in code; optional clinician reference points per case.

Controlled comparison, same 18 cases (8 practice + SYN001–010), local qwen3:8b, thinking off, official settings.
Results are in `eval/results/f1_qwen3_8b_20261123/`, which is gitignored.

| Case | Baseline note | F1 note | Judge total, baseline → F1 |
|---|---|---|---|
| SYN003 | `心率1、12次/分` | `心率112次/分` (= source) | 50 → 100 |
| SYN009 | `弥散量为预计值的4,8%` | `…48%` (= source) | 50 → 96 |
| SYN005 | `SpO₂ 95%（原文为96%）` | clause removed, review item added | 50 → 50 (cap now from another judge-claimed error) |

High-severity verifier findings dropped from 3 to 0. Other notes were identical between arms, except P01, where
generation differed run-to-run with no F1 change, so P01 is noise. Test suite: 249 tests pass.

**The 8B judge is not reliable enough to use as the scoreboard.** On identical notes it is consistent, but many of
its zero/cap calls are wrong on reading. Examples: `SpO₂ 92%` flagged although the record says 92%; a heart-rate
discrepancy that is in the record itself; "尿路感染待排" called a serious omission. Mean totals (52.7 → 63.2) are
therefore not meaningful in absolute terms. Next for E1: a stronger judge (designated model, or a larger local
model with thinking on), clinician reference points for the 8 practice cases, and calibration against two
clinician-scored batches before any later change is judged by it.

### 2026-11-23: F2 qualifier binding

- `qualifier_not_in_source` (high in Case Features, medium in Discussion; knowledge statements exempt): a
  qualifier (空腹/餐后/随机/持续/最高/最低/平均/峰值) followed within 10 characters by a value that the records give,
  but never with that qualifier in the 15 characters before it in the same clause. Values absent from the records
  stay with the number check.
- `strip_unsupported_qualifiers` (A2/S2/A3): deletes such a qualifier, which only weakens the claim back to what the
  records say ("空腹血糖10.8" → "血糖10.8").
- Real notes: on the 18 qwen3:8b notes it flags exactly one statement, the P05 `空腹血糖10.8` error, with no false
  alarms. Verbatim guard: 33,537 record sentences (CMB-Clin, TypicalCase-DC, practice, synthetic 100) copied as
  statements raise 0 findings. The first version raised 2 there, because it read a truncated "0" from "0.61";
  that is fixed and has a test.
- Not done: the comparison-phrase rule (高于/超过 + value). In P05 the invented `160/100` is already caught by
  the number check (medium in Discussion); it stays flagged, not removed.

### 2026-11-23: F3 planned vs performed

- The existing `unsupported_completed` check (a plan clause worded as done, with record support below 0.5) now
  recognises more Chinese forms: 已/已经 + 行/予/给予/完成/完善/开始/输注/置入/使用/应用/静滴/静推/口服/注射/送检/留取,
  and 已于.
- `retense_completed` (A2/S2/A3) rewrites an unsupported "已(经)+verb" clause as "拟+verb" ("已行冠状动脉造影" →
  "拟行冠状动脉造影") and adds one review item asking whether it was performed. Done-actions the records support are
  untouched. "已于…" and English wording stay flagged and are not rewritten.
- Real notes: the 18 qwen3:8b plans contain no done-wording at all; the only match was "拟予…". So F3 is a guard
  against a failure the rubric names, not a fix for one observed on this model.

### 2026-11-23: F5 harm screen

- **Allergy** (`allergy_conflict`, high): drug allergies the records state as present, grouped into 8 drug classes
  (penicillins, cephalosporins, quinolones, sulfonamides, aminoglycosides, macrolides, aspirin/NSAIDs, contrast
  media). A plan clause that would give a drug of a recorded class is removed in A2/S2/A3, with a review item
  naming the drug and the allergy. A clause that already handles the allergy (过敏, 改用, 避免, 皮试…) is left
  alone, and the plan is never emptied. Denied allergies and relatives' allergies don't count.
- **Bleeding** (`bleeding_risk`, medium, shown to clinicians): the plan includes anticoagulant, antiplatelet or
  thrombolytic therapy, and the records state bleeding, an aortic dissection or intramural haematoma, or low
  platelets as present. Flag only, because some cases need anticoagulation despite bleeding. Wording such as
  评估出血风险, 暂缓 or 权衡 suppresses it.
- Allergy extraction survey on 2,100+ public cases (synthetic 100, CMB-Clin, TypicalCase-DC): 11 drug allergies
  found, all correct on reading, after excluding a relative's allergy (the first version read "母亲对阿莫西林…过敏"
  as the patient's).
- Real notes: on the 18 qwen3:8b notes it raises nothing. Two cases record bleeding risk (P05 intramural haematoma,
  SYN005 haemoptysis), and neither plan proposes antithrombotics. P07's dual antiplatelet therapy is not flagged,
  because it records no bleeding. As with F3, this is a guard, not a fix for an observed error.

### 2026-11-23: D1 reasoning step (S2), measured

S2's first call now produces a ranked problem list. Each problem carries verified quotes, a certainty grade, 2–3
differentials (for, against, discriminating test) and missing items. Same 18 cases, local qwen3:8b:

| | A2 (default) | D1 |
|---|---|---|
| Completed | 18/18 | 18/18 |
| Time per case, median / max | 38.7 s / 53.0 s | 70.9 s / 93.7 s |
| Calls | 18 | 36 |
| High / medium findings | 0 / 4 | 0 / 2 |
| Rubric judge, before caps | 88.1 | 87.2 |
| Rubric judge, with caps / capped / zero | 47.6 / 2 / 8 | 51.6 / 2 / 7 |

- **Decision (pre-registered rule): D1 is not promoted.** It doubles latency and shows no measurable gain. Most of
  the judge's zero verdicts are wrong on reading, for example ursodeoxycholic acid for ICP called "harmful".
- D1's reasoning call returned invalid JSON on 2/18 cases. Those fell back to A2 behaviour.
- **Test-server caveat:** this Ollama server ignores `chat_template_kwargs`, so thinking was on in every qwen3:8b run
  so far; `reasoning_effort: "none"` is what disables it there. The `REASON_THINKING` arm was therefore a duplicate.
  The model context is 8,192 tokens, which the judge prompt likely exceeds on practice cases.

### 2026-11-23: two safety gaps found by reading the D1 notes

- **Aortic syndromes** (`aortic_antithrombotic`, high). When the records document an aortic dissection or
  intramural haematoma, plan clauses giving anticoagulant, antiplatelet or thrombolytic therapy are removed, with a
  review item. Only explicit stop or withhold wording (暂停, 停用, 避免…) keeps such a clause. Seen in A2 P05:
  "继续阿司匹林300mg/日，氯吡格雷300mg/日" with an intramural haematoma. **This is a clinical rule pending clinician
  sign-off.** Other recorded bleeding stays a medium flag.
- **Invented allergies** (`allergy_not_in_source`, high, all sections). A drug allergy stated in the note but not in
  the records is removed: first the parenthetical holding it, then the clause. One review item asks the clinician
  to confirm the allergy history. Hypothetical wording ("如青霉素过敏…") is left alone. Seen in SYN001, both A2 and
  D1: "拟予头孢类抗生素（青霉素过敏，需替代方案）" with no allergy in the record.
- On all saved real notes (four 18-case runs), the rules flag exactly those errors: P05 once, SYN001 three times.
  They flag nothing else. Verbatim guard: 33,537 record sentences raise 0 allergy findings.
