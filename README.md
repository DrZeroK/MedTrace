# MedTrace — evidence-grounded initial progress notes

**English** | [简体中文](README.zh-CN.md)

MedTrace turns admission materials into an initial hospital-course draft with source attribution. It is for teaching and evaluation; generated clinical content requires clinician review.

## Project status (2026-11-25)

**MedTrace did not pass the university-round acceptance check. Development has stopped and the repository is now public for reference and learning only.** Code, knowledge cards and docs are left as they were and are not maintained. No clinical content has been signed off by a clinician; do not use it for real care.

The original competition brief (background, scoring rubric, technical spec, in Chinese) is at [docs/比赛要求.pdf](docs/比赛要求.pdf).

### How far it got

| Stage | Status |
|---|---|
| Competition entry and output protocol (no-argument `main.py`, two-key `.env`, `output.json`/`run_log.json`, exit codes) | Done, with regression tests |
| Generation pipelines A0–A3/S2, default A2 | Done; official defaults A2, prompt v3, temperature 0, seed 37 |
| Deterministic verification and safe repair (numbers, units, negation, chronology, source IDs) | Done |
| Clinical safety rules (no antithrombotics in aortic syndromes, drug allergies, bleeding risk, dose engine) | Done as rule screens; not clinically validated |
| Offline knowledge base and retrieval (127 guideline cards + textbook chunks, SQLite FTS5) | Wired into the pipeline; cards are AI-checked only, not signed off; no approved release ships by default |
| Phase-one experiments (Chinese ConText rules, DSPy MIPROv2 instruction search) | Done and reported; candidates not promoted to default |
| Acceptance on the designated model qwen3.8-27b | **Failed**: 4 of 10 random cases produced unparseable JSON; 4/10 completed end to end. See the [root-cause analysis](docs/QWEN38_RANDOM10_JSON_RCA.zh-CN.md) (Chinese) |
| Blinded clinician review | Materials prepared, not carried out |
| JSON repair | Partial: unescaped ASCII quotes copied from the records are repaired; error-type-specific recovery and judge-score integrity checks are planned only (RCA P1/P2) |
| Case-triggered safety points, pneumonia severity, third-reviewer adjudication in the judge | Merged; thresholds and sources in the [source check](docs/SAFETY_POINTS_SOURCES.zh-CN.md) (Chinese); judge strictness not calibrated |

### Algorithms and technology

- **Fact ledger**: deterministic regex and Chinese-rule extraction that keeps each fact's verbatim sentence and `source_id`, cut at `record_cutoff`, and feeds a traceable prompt context.
- **Evidence-constrained generation**: an LLM (OpenAI-compatible Chat Completions, Qwen served by vLLM) writes structured JSON with per-statement source tags; missing sections are regenerated within the call budget, otherwise a conservative extract-only draft is emitted.
- **Deterministic verification**: checks generated statements against the ledger for numbers, units, negation, chronology and references; only provably safe edits are automatic (dropping non-existent source IDs, rewording unsupported "done" actions as planned), everything else becomes a review item.
- **Chinese ConText-style scopes**: self-authored rules after Harkema et al., ConText (2009), for negation/uncertainty/hypothetical and experiencer (patient vs relative); CHIP-CDEE dev three-class macro F1 0.786 → 0.919.
- **Offline retrieval (RAG)**: SQLite FTS5 + BM25 with scope-aware query building, population filters and rule-based reranking; no embeddings, no GPU, no extra model call. v4 test set top-5 recall 100%, evidence precision 81.2%.
- **Clinical rule screens**: graded aortic antithrombotic screen (elapsed-time phasing, indication windows), allergy and bleeding-risk screens, dose engine, severity guard; seven case-triggered safety points (allergy, stroke reperfusion, ectopic pregnancy, thiamine, hypokalaemia, drug hypoglycaemia, septic shock) added to the prompt, plus computed community-acquired pneumonia severity.
- **Prompt optimisation experiment**: DSPy MIPROv2 instruction search under a persistent 300-request cap with resume.
- **Evaluation**: numeric coverage, literal diagnosis hits, five-dimension LLM rubric judge, paired blinded-review packets.
- **Engineering**: Python 3.11; runtime depends only on `requests`, `python-dotenv` and `jsonschema`; `unittest` regressions; submission packaging with a SHA-256 manifest and prompt fingerprint.

### Known problems

- Unstable JSON output on the designated model is the direct cause of the failed acceptance; only unescaped quotes are repaired, other syntax errors still rely on a generic format-reminder retry, and the parser's trailing-comma cleanup can alter text inside strings.
- The rubric judge can cache incomplete five-dimension scores.
- Public experiments used non-designated models and public data only; they say nothing about performance on the designated service.

## Official execution

Python 3.11 is the competition runtime. Install with `python -m pip install -r requires.txt`, then run `python main.py` without arguments. The organiser places `.env` and `input.json` beside `main.py`; starting in another directory still uses those source-root files.

`.env` contains exactly two non-empty keys:

```dotenv
MODEL_NAME=qwen3.8-27b
ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
```

ENDPOINT is the complete HTTP(S) URL, used unchanged. Official requests send no Authorization header and inherit neither proxies nor netrc credentials. Development environment settings cannot override the official model, endpoint, paths, prompts or parameters.

Input is a JSON array. Each case has a unique non-empty string `case_id`, a valid string `record_cutoff` (timestamp or `T0`), and `sources` containing unique non-empty string `source_id` and non-empty string `content`. Invalid identifiers or a non-array document are task errors; invalid per-case materials produce a failed record in place.

`output.json` is published beside main.py only after the batch finishes. Output order and identifiers match input:

```json
[{"case_id":"DEMO001","status":"success","medical_record":{"case_features":"…","diagnostic_discussion":"…","plan":"…","evidence":[{"statement":"…","source_ids":["S01"],"kind":"fact"}],"review_items":[]},"error":null}]
```

Failure uses `status="failed"`, `medical_record=null`, and `error={"code":"…","message":"…"}`. Empty input yields `[]`. Successful generation requires all three narrative sections and case-local evidence. Missing model sections trigger regeneration within the call budget, then failure.

Exit codes: **0** complete protocol-valid output written (individual failures allowed); **1** task/runtime or output/log-writing error; **2** missing/invalid configuration or basic input protocol error. `logs/run_log.jsonl` retains appended events; `run_log.json` beside the output contains only the current completed run, with timestamps, run ID, per-attempt records, counts, token usage and input/output hashes.

Defaults fixed in code: A2, prompt v3, temperature 0, seed 37, at most two logical calls/case, two transient HTTP retries/call, 600-second request timeout, one worker, model repair off. Final organiser limits still require confirmation. If the service explicitly rejects the seed, the client retries without it and logs the change. Repeated requests can produce different text even with the same seed.

## Test packaging

`python scripts/build_submission.py --output /absolute/new/submission.zip` builds a test archive and refuses to overwrite an existing file. A team ID has not been assigned; current packaging is for tests. The archive contains a SHA-256 manifest, prompt fingerprint and source revision, and excludes `.env`, datasets, evaluation code, tests, development templates and local logs.

Optional `--knowledge /absolute/path/knowledge.sqlite` accepts a validated release and bundles its manifest. Official execution automatically loads `resources/knowledge.sqlite`; there is no approved clinical release by default.

After running an extracted algorithm package, use `python scripts/build_submission.py --results-from /absolute/extracted/package --output /absolute/new/results.zip`. This checks record structure, case order, completed-run logs, counters, I/O hashes and unchanged algorithm resources before packaging `output.json`, `run_log.json` and the algorithm manifest. Mock results remain test results and must not be presented as official results.

## Development and tests

For an offline smoke test, extract into a new directory and run `python main.py --development --input /absolute/extracted/input.example.json --output /absolute/extracted/test_output.json` with `LLM_API_BASE=mock://` and `OUTPUT_PROTOCOL=official` in the process environment. This explicitly uses a mock, not the competition service.

For configurable experiments, use `.env.development.example` in a separate working directory and `python /absolute/path/main.py --development`. Development mode supports legacy endpoint/key aliases and path overrides and produces the same official output protocol by default (`OUTPUT_PROTOCOL=legacy` opts into the old flat contract). Evaluation modules explicitly use development configuration.

Run `python -m unittest discover -s tests -v` for regressions, including isolated ZIP tests of the official two-key configuration and no-argument entry point. Tests retain their artifacts.

## Method and evidence

The pipeline builds a fact ledger, generates source-tagged statements and checks numbers, units, negation, chronology and references. Unresolved issues are flagged; final structure is checked before publication. Rules cannot establish clinical correctness or detect all omissions; relative time expressions and complex paraphrases remain limitations.

Historical experiments used mocks and non-designated models on public data. They do not establish performance on the designated service. Engineering validation, designated-service acceptance and clinician assessment are separate checks.

Phase-one development candidates add Chinese ConText-style scopes and DSPy MIPROv2 instruction optimization under a persistent 300-request cap. Official defaults remain unchanged and clinical review is pending. See the repository's [experiment protocol](https://github.com/DrZeroK/MedTrace/blob/codex/context-prompt-experiments/docs/PHASE1_EXPERIMENTS.md) for splits, resume safeguards and reports.

See [requirements](docs/REQUIREMENTS.md), [project description](docs/PROJECT_DESCRIPTION.md), [declarations](docs/DECLARATIONS.md), [resource registration](docs/RESOURCE_REGISTRATION.md) and [optional knowledge support](docs/KNOWLEDGE_BASE.md).
