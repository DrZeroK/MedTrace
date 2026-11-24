# Phase one: Chinese context and prompt candidates

**English** | [简体中文](PHASE1_EXPERIMENTS.md)

This phase adds only explicit development candidates. The official entry point still uses the fixed v2 prompts, legacy context and the original competition output protocol, and does not read `CONTEXT_MODE` or `PROMPT_CANDIDATE_PATH`. DSPy is a development dependency only; experiments, caches and candidates do not enter the algorithm submission package.

The Chinese rules follow [ConText's scope approach](https://doi.org/10.1016/j.jbi.2009.05.002); the rules are written by this project and introduce no external lexicon, pretrained weights or clinical ontology. Each context scope records the source offset, rule, assertion, and temporal or subject attributes; original facts and numbers remain unchanged. Coverage includes negation, uncertainty, not recorded, family members, past, present and conditionals, and ambiguity is kept pending verification. Conflicts triggered by shared phrases are review prompts only.

DSPy is pinned to `dspy[optuna,numpy]==3.5.0`. It uses MIPROv2, seed42, 3 instruction candidates, 4 optimization trials, batch size 4 and a single thread. Internally, v3.5 still bootstraps demonstrations for the proposal stage even when the demonstration cap is zero; the project's version-pinned adapter disables this step, so bootstrapped and labelled demonstrations are both zero. The proposal data summary uses only 18 public cases and provides neither reference hospital courses nor fabricated gold-standard records. The optimized content is only an upfront organisational suggestion; the fixed v2 fact constraints, cutoff, sources and JSON protocol are then preserved in full. The candidate still requires human review.

## Data and selection

- Only public CMB-Clin at a fixed path may enter the experiment service; arbitrary case paths are not accepted.
- dev26 is deterministically split by seed42 into proposal18 and selection8; candidates are scored on selection8 only. test30 is used for a single confirmation after the candidate is frozen, and the cache supports resume. validation17, previously used for development, is not treated as an untouched independent validation set.
- CMB-Clin has no temporal trajectory; empty cutoffs are marked in memory as the symbol T0, no real date is inferred, and date-specific cutoff filtering cannot be verified. Raw data files are not rewritten, and their hashes are written into the experiment identity.
- A is legacy; B is the Chinese context rules; C is the rules plus the optimized organisational suggestion. C is selected only if its search score on selection8 is strictly higher than B's; otherwise B is selected. This freezes only the confirmation candidate and does not decide official rollout.
- Cases with failed output or with structural/source-reference non-compliance score 0; other cases score the mean of numeric coverage and literal reference-diagnosis hits. When there is no eligible diagnosis metric, only numeric coverage is used. Rule findings, literal diagnosis hits and same-model diagnostic reviews are all proxy metrics and cannot represent clinical accuracy.
- CHIP-CDEE is evaluated locally only, and only summaries are saved. train may tune the rules; dev is only reported. Both modes use the same eligible occurrence set. The three classes are affirmative, negated and uncertain; empty original tendency labels are treated as affirmative. missing/unknown counts as an abstention error and is not removed from the denominator. The thresholds are that negation F1 does not drop by more than 0.005 and that the number of uncertain cases misread as negated does not increase.

## Budget and resume

All proposal, generation and review requests, and regeneration requests after parse failures, pass through the same `RequestBudget`. Development allows at most 120 and confirmation reserves 180, for at most 300 HTTP requests in total. Automatic HTTP retries are off; DSPy caching is off and only the experiment cache validated by this project is used. There is no implicit SDK service routing. Before each request is sent, a reservation is appended and synchronously written to disk; a crash or failure consumes quota in the same way. A process lock prevents concurrency in the same directory. Identity includes program, data, prompt and credential-free configuration digests, and resume is refused after the configuration or code change. Do not create another directory to reset the quota of the same experiment.

Logs do not store authentication headers or keys. They record the request hash, purpose, model, status and service-reported token counts; when the unit price has not been verified, the cost is explicitly unknown. The generation cache contains public cases and outputs and must not be used to store private medical records. All experiment artifacts are retained and the tool performs no cleanup.

First load the authorised development `.env` in the project root, and replace Python in the absolute paths below with the interpreter that has the development dependencies installed; the three stages must use the same directory:

```sh
/absolute/path/to/python -m eval.phase1 rules --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
/absolute/path/to/python -m eval.phase1 develop --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
/absolute/path/to/python -m eval.phase1 confirm --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
/absolute/path/to/python -m eval.phase1 report --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
```

Artifacts include `experiment.json`, `splits.json`, the append-only `requests.jsonl`, candidate JSON, the generation cache, `optimization.json`, the frozen `selection.json`, the confirmation summary and JSON/Markdown report snapshots. Changed source files, exhausted budget or service failure preserve completed work; do not bypass the identity check. If `JUDGE_MODEL` is specified explicitly it is included in the experiment identity; otherwise the generation model is used, and the review results state that it is a same-model review.

`confirmation/review/packet.md` together with the blank `scores_R1.csv` and `scores_R2.csv` is for independent blinded clinical review; `key.json` is the unblinding map and is not provided to reviewers before scoring. Technical failures are explicitly marked as having no valid record, and internal fallback drafts are not shown. Rollout is discussed only after severe-error, factual-accuracy, source-support, reasoning and plan scores and disagreement adjudication are complete. The tool does not fabricate expert scores or automatically change official defaults.

The results of this round's frozen experiment and the final blinded-review path are in the [results report](PHASE1_RESULTS.md). The raw snapshots are retained; the source after the error-handling patch differs from the original experiment identity, so the old directory cannot be resumed directly.
