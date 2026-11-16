# MedTrace — technical report (working draft)

## 1. What exists

A complete, tested pipeline (`README.md`) with five interchangeable variants (A0, A1, A2, S2, A3), a deterministic
fact ledger and verifier, an offline mock model with fault injection, an evaluation set of 16 annotated synthetic
cases (11 development, 5 held out; 12 English, 4 Chinese; two per category), 7 one-fact perturbation tests,
ablation / perturbation / blinded-review tooling, and 44 automated tests.

## 2. What has been measured — and what has not

**Nothing below is evidence of clinical quality.** No designated-model credentials were available, so every number
comes from the mock model, which copies record sentences and adds template reasoning. The mock results answer two
engineering questions only: does the software hold up under failures, and does the deterministic verifier catch
known error types?

### 2.1 Verifier false alarms on faithful text
All 16 cases, every record sentence copied verbatim as a case feature: **0 high- and 0 medium-severity findings**.
(Verbatim text is the easiest case; paraphrase by a real model will raise false alarms — to be measured.)

### 2.2 Injected errors (mock, 16 cases × 3 seeds = 48 runs per variant; `eval/results/mock_faults_seed{1,2,3}`)
Eight error types injected into the generation call with probability 0.4–0.5 each (wrong number, unit swap, negation
flip, fabricated history, undocumented negative, non-existent source id, post-cutoff statement, plan item stated as
done), plus malformed JSON (0.15) and a hallucinating reviewer (0.5). The same errors are injected for every variant.

| Variant | Runs completed by the model | Injected errors still in the note | …of which not flagged for review | Source ids valid | Key-fact coverage (proxy) | Calls / case |
|---|---|---|---|---|---|---|
| A0 baseline | 41/48 | 152/178 | 152 | 91.9% | 96.5% | 1.00 |
| A1 grounded prompt | 41/48 | 152/178 | 152 | 97.9% | 96.5% | 1.00 |
| A2 + deterministic verification | 46/48 | 27/224 | **0** | 100% | 91.6% | 1.96 |
| S2 extraction → A2 | 46/48 | 27/224 | **0** | 100% | 91.6% | 2.96 |
| A3 + semantic review | 46/48 | 25/224 | **0** | 100% | 91.6% | 2.00 |

With a strict single-call budget (`mock_faults_single_call`, seed 1) A2 cannot repair, so 42/54 injected errors stay
in the text, but all 42 are listed under `review_items`; coverage 97.3%.

How to read this:
- A0 and A1 are identical here by construction: the mock ignores prompt content, so **the value of the grounded
  prompt (A1) is untested**. The 26 injected errors absent from A0/A1 output all belong to the 7 runs that failed on malformed JSON and fell
  back to the extract-only note. (An earlier version of this table said 148/178: the mock mis-logged faults that
  were later mutated by a second fault in the same sentence; fixed, with a regression test.)
- The injected error types and the verifier were written by the same author, so detection here is an upper bound.
  Real model errors (wrong inference, subtle paraphrase, omitted facts, wrong but source-present numbers attached to
  the wrong analyte or time point) are **not** covered by these checks.
- Coverage drops from 96.5% to 91.6% with repair because the mock "repairs" by deleting the whole flagged sentence,
  taking true facts with it. A real model is instructed to rewrite rather than delete, but the same trade-off is a
  genuine risk and must be measured; if it appears, prefer `MAX_CALLS_PER_CASE=1` (flag, don't repair).
- All 22 hallucinated reviewer patches were rejected by the patch guard.
- Unrecoverable runs (two consecutive malformed responses) still produced a schema-valid, flagged extract-only note.

### 2.3 Engineering
100% schema-valid output and correct case order in every run, including: malformed/empty cases, invalid JSON input
(exit 1, no partial file), HTTP 500s, timeouts, unreachable endpoint, garbage responses, exhausted call and time
budgets, parallel workers. Clean-environment check: fresh virtualenv with only `requires.txt` → run and tests pass;
a run with none of the three dependencies installed also completes (stdlib fallbacks).

### 2.4 Perturbation tests (mock; `eval/results/perturb_mock`)
Mechanics pass: the ledger detects the change in 6/6 record edits, the post-cutoff result never leaks, and no
unaffected key fact is lost. Reasoning-level expectations fail, as they must with a mock that does not reason.
Two limits of the deterministic layer showed up and are left to the model/reviewer: a reworded contradiction
("neck supple" vs "reports neck stiffness") and a medication-status contradiction ("on apixaban" vs "stopped
apixaban") are not detected by rule.

### 2.5 External Chinese data: CMB-Clin (added)

Dataset audit and ranking are in `docs/DATASETS.md`. One dataset could be both verified and acquired: CMB-Clin
(Apache-2.0, 74 textbook inpatient cases with expert answers). Standardisation results
(`data/standardized/cmb_clin/qc_report.md`): 74 kept, 0 duplicates or near-duplicates, 57 tier A, 16 tier B,
1 held for clinician review; post-admission course sections withheld in 5 cases; splits dev 26 / validation 17 /
test 30, grouped by disease label. Reference answers exist for diagnosis/differential (60 cases) and treatment
(64); no reference Case Features exists and none was generated.

What this real-format Chinese text showed about the deterministic layer (no model involved):

| Check | Result | Consequence |
|---|---|---|
| Verifier false alarms on 1,717 verbatim record statements | 0 high, 0 medium | Holds on real-format Chinese, including full-width `％ ／` and `×109/L` (handling added) |
| Ledger "conflict" flags | 38 before, 3 after | 35 were negative findings tied to a site or time ("无头晕" earlier, "头晕" now) — essentially all false. Conflicts are now raised only for an explicitly denied history that another source asserts. Cost: contradictions phrased as plain negatives are left to the model/reviewer |
| New check: value reported under the wrong measurement | 86/86 synthetic swaps of two values inside one sentence caught; 0 false alarms on verbatim text | Mechanical test by construction; closes the "right number, wrong analyte" gap for labelled values only |
| New check: allergy / pending-result content missing from the note | 0 false alarms on verbatim text | Surfaced as review items; general completeness remains a reviewer judgement |

`python -m eval.run_external` reports diagnosis hit (61 eligible cases), differential recall against the expert
answer, measurement coverage and verifier findings per variant. It has only been run with the mock (mechanics:
26/26 dev cases completed, schema-valid); the mock does not reason, so there are **no model results yet**.

## 3. Known limitations

- Verifier is lexical: it cannot tell a correct inference from a wrong one, cannot detect omissions, and checks
  that a number exists in the records, not that it is attached to the right test or time point.
- Negation scope is heuristic (clause-level cue lists for English and Chinese).
- Sentence-level cutoff only sees explicit dates; relative expressions ("next day") are not resolved. Dates written
  inside record text carry no UTC offset and are read in the cutoff's own local clock. Source timestamps with an
  offset are converted to the cutoff's offset; if only one side has an offset they are compared as written and a
  warning is logged.
- `must_not` and key-fact metrics are regex proxies; they will miss and mis-fire. They screen, they do not judge.
- 16 cases cannot support the stated targets (≥98% coverage, 0 critical errors) with useful confidence: with 0
  critical errors observed in n cases, the one-sided 95% upper bound on the true rate is about 3/n (≈19% for n=16,
  ≈5% for n=60).
- Prompts have never been seen by the designated model; expect at least one iteration on JSON compliance and length.

## 4. Next steps, in order

1. Confirm the 20 items in `docs/REQUIREMENTS.md` against the official instructions.
2. First real-model (Qwen) run: `python -m eval.run_external --dataset cmb_clin --split dev --variants A0,A1,A2`
   and `python -m eval.run_ablation --name real_v1 --split dev`. Read the raw outputs before the tables.
3. Clinical Lead reviews cases/annotations and the rubric; blinded two-reviewer scoring of A0 vs A1 vs A2 on dev.
4. Identify the three highest-impact baseline weaknesses from the error categories; change one thing at a time.
5. Measure verifier false-alarm rate on real output; tune thresholds on dev only.
6. Decide A2 vs A3 vs single-call on measured critical errors, coverage loss and latency; confirm once on held-out.
7. Expand the case set towards 60; freeze ≥48 h before the deadline.

## 5. Selection rule (pre-registered)

Keep a more complex variant only if, on held-out cases under identical settings, it lowers the reviewer-assessed
critical error count without lowering key-fact coverage by more than 1 percentage point, and stays inside the
official call and time limits. Otherwise ship the simpler one.
