# Requirements extracted, and what is still unconfirmed

No official technical specification, sample `input.json` or model credentials were available when this was built.
Everything below marked **ASSUMED** is isolated behind configuration and must be checked against the official
instructions before the submission freeze. Owner: Role C, with Role A for the clinical items.

| # | Item | Current behaviour | Status | Where to change |
|---|---|---|---|---|
| 1 | Entry point | `python main.py` | given | — |
| 2 | Dependency file | `requires.txt` | given (unusual name — re-check) | — |
| 3 | Input fields | `case_id`, `record_cutoff`, `sources[].source_id`, `sources[].content` | given | `medtrace/inputs.py` |
| 4 | Input envelope | list, `{cases:[…]}`, or single case all accepted | **ASSUMED** | `inputs.split_envelope` |
| 5 | Input / output paths | `input.json` / `output.json` in the working directory | **ASSUMED** | `INPUT_PATH`, `OUTPUT_PATH` |
| 6 | Output field names | `case_features`, `diagnostic_discussion`, `treatment_plan`, `evidence`, `review_items` | **ASSUMED** | `OUTPUT_FIELD_MAP`, `OUTPUT_FIELDS` |
| 7 | Are extra fields (`evidence`, `review_items`) allowed? If only three text fields are allowed, should citations be inline? | separate arrays; inline off | **ASSUMED** | `OUTPUT_FIELDS`, `INLINE_CITATIONS=1` |
| 8 | Output language | follows the records | **ASSUMED** | `OUTPUT_LANG` |
| 9 | `record_cutoff` format and semantics | ISO / common date formats; date-only = end of day; UTC offsets honoured (source timestamps converted to the cutoff's offset); sources with a timestamp field and sentences with an explicit date after the cutoff are withheld from the model | **ASSUMED** | `CUTOFF_MODE`, `textutil.parse_cutoff` |
| 10 | Model API protocol | OpenAI-compatible `POST {base}/chat/completions`, bearer key | **ASSUMED** | `medtrace/llm.py` |
| 11 | Env variable names for endpoint/key/model | `LLM_*` plus common aliases | **ASSUMED** | `medtrace/config.py` |
| 12 | Model-call limit per case; do HTTP retries count? | 2 logical calls, 2 HTTP retries each | **ASSUMED** | `MAX_CALLS_PER_CASE`, `LLM_MAX_RETRIES` |
| 13 | Time limits | none by default | **ASSUMED** | `CASE_TIMEOUT`, `TOTAL_TIMEOUT`, `LLM_TIMEOUT` |
| 14 | Concurrency / rate limits | sequential | **ASSUMED** | `WORKERS` |
| 15 | Exit codes | 0 / 1 / (2 with `STRICT_EXIT`) | **ASSUMED** | `medtrace/runner.py` |
| 16 | Malformed or empty case | emitted in place with an explanatory note and review item | **ASSUMED** | `pipeline.run_case` |
| 17 | Log location / format | `logs/run_log.jsonl` + stderr | **ASSUMED** | `LOG_DIR` |
| 18 | Python version on the evaluation machine | written for 3.10+, tested on 3.13 only | **verify on 3.11** | — |
| 19 | Is retrieval / external knowledge permitted? | not used | n/a | — |
| 20 | Packaging (archive name, directory layout) | repository root | **ASSUMED** | — |

## Not done here (needs people or access)

- Run against the designated model; nothing in this repository is evidence about its clinical quality yet.
- Clinical review of the 16 synthetic cases and their annotations by the Clinical Lead; expansion to ~60 cases.
- Blinded two-reviewer scoring and adjudication (tooling is ready: `eval/blind_review.py`).
- Team assignment, rules/deadline confirmation, presentation materials.
