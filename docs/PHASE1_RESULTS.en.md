# Phase-one experiment results (2026-11-18)

**English** | [简体中文](PHASE1_RESULTS.md)

This round implemented and evaluated Chinese context rules and a DSPy MIPROv2 search over organisational instructions. The official default flow retains legacy context and the fixed v2 prompt; the results below serve development selection, and the candidates have not yet received clinical endorsement.

Source commit: `73a55dc75eec12294f1dfdf7edf9cf217d3445d4`. Python 3.11.16, DSPy 3.5.0, generation model qwen3.5-27b. The complete program, public-data hashes, credential-free configuration digest and dependency versions are retained in the local experiment directory. Fixed splits, request budget and review protocol are described in the [experiment protocol](PHASE1_EXPERIMENTS.md).

## Rule evaluation

CHIP-CDEE source text is used only locally. train is used for rule development, and dev is reported only after freezing. Both modes are scored on the same occurrence set; missing/unknown in the three-way classification are abstention errors and are not excluded.

| Split | Three-way entries | legacy macro-F1 | Chinese-rule macro-F1 | legacy negation F1 | Chinese-rule negation F1 | Uncertain findings wrongly negated (old → new) |
|---|---:|---:|---:|---:|---:|---:|
| train | 6220 | 0.7890 | 0.9366 | 0.9830 | 0.9836 | 3→2 / 254 |
| dev | 1525 | 0.7859 | 0.9194 | 0.9818 | 0.9818 | 0→0 / 65 |

Both the preset negation-F1 non-inferiority threshold (a drop of at most 0.005) and the requirement that the number of uncertain findings wrongly negated does not increase were met. On dev the new rules produce 10 abstentions; uncertain findings are correctly identified in 46/65 cases, so some are still missed. The legacy three-way classification is based on whole-sentence uncertainty cues, whereas the new rules are based on the target scope; this is not a comparison with mature named entity recognition models. Family subject, temporal attribution and similar aspects currently have only self-authored contrast tests, with no validation on an independent clinical annotation set.

## Public CMB-Clin development selection

dev26 was split by seed42 into 18 proposal and 8 selection cases. The 18 proposal cases were used only for data summaries, with no reference hospital course supplied and no training demonstrations generated; candidate comparison uses only the 8 selection cases. Empty cutoffs in the raw data are marked in memory with the symbolic T0. validation17, used during earlier development, does not serve as an independent confirmation set.

| Selection 8 cases | Search score | Valid outputs | Mean numeric coverage | Diagnostic literal hits (6 eligible cases) | Cases with high-severity rule alerts |
|---|---:|---:|---:|---:|---:|
| A: legacy | 0.8125 | 8/8 | 1.0000 | 3/6 | 0/8 |
| B: Chinese rules | 0.8750 | 8/8 | 1.0000 | 4/6 | 0/8 |
| C: Chinese rules + MIPRO organisational advice | 0.8385 | 8/8 | 0.9271 | 4/6 | 0/8 |

After 4 MIPROv2 search trials the initial organisational advice was retained; the last new proposal evaluated on the full selection set did not exceed it, and the other proposal has only a small-batch score, so this does not establish that all proposals are ineffective. C did not exceed B, so by the preset rule B was frozen for a single test30 confirmation. The development stage made 43 actual HTTP requests (37 generation, 6 proposal/summary) with no budget reset.

The search score is not clinical accuracy: failures or structural/source-reference non-compliance score 0, and the rest are the mean of numeric coverage and eligible diagnostic literal hits; when no diagnostic is eligible, only coverage is used. A count of 0 high-severity alerts does not mean there are no clinical errors.

## Single test30 confirmation after freezing

| Confirmation 30 cases | Search score | Valid outputs | Numeric coverage (failures scored 0) | Diagnostic literal hits | Same-model review judged primary | Cases with high-severity alerts | Mean time |
|---|---:|---:|---:|---:|---:|---:|---:|
| A: legacy | 0.7927 | 29/30 | 0.9312 | 11/21 | 16/21 | 0/30 | 20.84 s |
| B: Chinese rules | 0.7980 | 29/30 | 0.9376 | 11/21 | 16/21 | 2/30 | 21.13 s |

In both groups the same case still produced no valid JSON after two generations; it is scored as a failure, with no resampling or additional attempts. All 42 diagnostic proxy reviews parsed successfully; each group has 16 primary, 3 differential and 2 absent. This is a textual review by the same generation model, not clinical-expert accuracy.

The rule group has a slightly higher search score and numeric coverage, identical values on both diagnostic proxy metrics, and 2 more cases with high-severity alerts. Alerts may be genuine problems or false positives; 30 cases this round are insufficient to demonstrate an overall clinical benefit. The existing official defaults are maintained, neither the prompt candidate nor the context candidate is promoted, and blinded review is completed first.

Final clinical materials are in the local experiment directory at `confirmation/official_review/review/packet.md`, with 60 anonymised identifiers and blank scoring sheets of 60 rows each for R1 and R2. 2 technical failures are explicitly marked as having no valid record; the internal fallback drafts must not be clinically scored. `key.json` is the unblinding map, to be held by the organiser's reviewers and not given to raters before scoring. Original exported materials and caches are retained.

## Requests, artefacts and accounting conventions

The original frozen round made 147/300 HTTP requests: development 43/120 and confirmation 104/180; of these 99 were generation, 6 instruction proposals and summaries, and 42 diagnostic reviews. All 147 returned HTTP200, and structural parse failures are billed the same way. The service reported 256,076 input and 155,749 output tokens, 411,825 in total; the service unit price has not been verified, so the cost is unknown.

The local `eval/results/phase1_20261118/` retains identity, data splits, candidates, caches, the append-only request ledger, the dependency environment, raw JSON/Markdown snapshots and `final_audit.json`. Public reports contain no CHIP-CDEE source text, keys or complete case outputs.

The experiment used the frozen source commit above. An error-handling patch made after the round ended adds caching of review parse failures, turns off the DSPy adapter format fallback, and standardises failed coverage to 0 and the exclusion of internal drafts from blinded review in the event of failure; it added no API calls, tuning or confirmation rerun. Coverage in the original snapshot includes internal fallback drafts; this table and `final_audit.json` set failures to 0, and the original files were not rewritten. Reproducing that frozen round requires the original commit; identity checks in the new source reject resuming an old directory, and the round's budget must not be reset through a new directory.

## Engineering validation

All 162 tests pass on Python 3.11 with DSPy; 162 pass under the standard library alone (2 optional-dependency tests skipped). Tests cover 60 self-authored assertion contrasts, subject/time boundaries, candidate hashes and fixed-prompt retention, the official entry point ignoring development settings, up-front budget accounting/resume after interruption/the 300-request cap, real MIPRO offline adaptation, failed coverage and review caching, and the submission-package protocol. Remote CI includes three groups: pinned, stdlib and dspy.

The test algorithm package `dist/phase1_baseline_73a55dc.zip` is retained and contains no data, evaluation programs, candidates or DSPy dependencies; the two official configuration entries and the v2 prompt fingerprint `v2:33ef24dbd3ac` have been verified. The package is for testing only; a team ID has not been assigned.

Subsequently, with user authorisation, the quote-syntax and negation-scope problems were located and fixed, and 4 diagnostic requests were appended separately, bringing the shared ledger to 151 requests; the frozen scores, raw outputs and blinded-review sheets in this report are not rewritten. See the [failure-fix report](FAILURE_FIX_20261118.md) for details.
