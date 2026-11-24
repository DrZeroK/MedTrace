# MedTrace — evidence-grounded initial progress notes

**English** | [简体中文](README.zh-CN.md)

MedTrace turns admission materials into an initial hospital-course draft with source attribution. It is for teaching and evaluation; generated clinical content requires clinician review.

## Official execution

Python 3.11 is the competition runtime. Install with `python -m pip install -r requires.txt`, then run `python main.py` without arguments. The organiser places `.env` and `input.json` beside `main.py`; starting in another directory still uses those source-root files.

`.env` contains exactly two non-empty keys:

```dotenv
MODEL_NAME=replace_with_model_name
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

Defaults fixed in code: A2, prompt v2, temperature 0, seed 42, at most two logical calls/case, two transient HTTP retries/call, 600-second request timeout, one worker, model repair off. Final organiser limits still require confirmation. An unsupported seed requires an explicit documented change; the client does not silently drop it.

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
