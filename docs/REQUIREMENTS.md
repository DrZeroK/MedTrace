# Requirements: confirmed, permitted in principle, unresolved, and assumed

Source of "confirmed" and "permitted in principle": `docs/COMPETITION_QA.md` — the organizer's answers supplied
by the project owner (no official announcement URL, publication date or version number was provided). **Later
unified technical specifications, actual API examples and the official evaluation configuration take precedence.**
This document does not certify compliance. Items marked **ASSUMED** are ours, isolated behind configuration, and
must be checked against the official instructions before the submission freeze.

Given (not assumed): entry point `python main.py`; input fields `case_id`, `record_cutoff`,
`sources[].source_id`, `sources[].content` (`medtrace/inputs.py`).

## 1. Confirmed by the organizer Q&A

| # | Requirement (Q ref) | Qualification kept verbatim in spirit | Implementation |
|---|---|---|---|
| C1 | No external third-party APIs; inference only through the designated self-hosted vLLM Qwen service; competition practice and evaluation cases must never be uploaded to third-party platforms (Q8) | Includes commercial models, online embedding, online retrieval | Runtime calls only the configured endpoint. The only real-model evidence so far used a **non-designated commercial** model (qwen4-max / qwen-plus) on **public CMB-Clin cases only**; nothing has run on the designated service. `.env.example` carries a neutral placeholder, not a commercial endpoint |
| C2 | No public internet during evaluation; no runtime install or download (Q3) | Only designated internal services may be called | Runtime needs no network except the model endpoint; `data_pipeline/acquire.py` downloads data but is development-only and not imported at run time |
| C3 | Local knowledge bases, rule bases, retrieval and multi-stage algorithms permitted (Q1) | Lawfully sourced, version-pinned, bundled, able to run independently offline | Optional read-only SQLite/FTS5 retrieval and numeric rules implemented; all initial content is draft and no clinical release is approved. See `docs/KNOWLEDGE_BASE.md` |
| C4 | Resources must be registered: name, source, version, purpose, file size, dependencies; teams with none state "None" (Q2) | Unified registration template pending [ORG] | Optional releases carry source/permission/version metadata and hashed manifests. No approved external resources currently ship by default; registration template pending |
| C5 | Complete dependency documentation "such as `requirements.txt`" (Q3) | Package size and compatibility requirements pending [ORG] | `requirements.txt` added, identical to `requires.txt`, kept in sync by a test |
| C6 | `seed` may be passed at the top level of the request body (Q4) | May be omitted with an explanation if unsupported; a fixed seed does not guarantee identical outputs | First-class `LLM_SEED` (WP-1, done); omitted when unset |
| C7 | Thinking controlled via `chat_template_kwargs: {"enable_thinking": …}` (Q7) | Omission uses the server default, which is **not necessarily "off"**; per-strategy selection in principle | First-class `LLM_ENABLE_THINKING` (WP-1, done); omitted when unset |
| C8 | Participant-initiated retries count toward the model-call budget, in principle (Q5) | Calls affected by competition-platform faults handled under unified exception-handling rules; specific limits pending [ORG] | `MAX_REQUESTS_PER_CASE` counts **every HTTP attempt including retries** (WP-2, done), default 0 = unlimited until published; `MAX_CALLS_PER_CASE` still counts logical calls |

## 2. Permitted in principle (subject to the deployed version / unified API specification)

| Item (Q ref) | Qualification | Implementation |
|---|---|---|
| `temperature` and `response_format` (Q6) | Final support subject to the deployed competition version and unified API specification; unsupported parameters should error explicitly | `LLM_TEMPERATURE`, `LLM_JSON_MODE`; untested against the competition service |
| Per-strategy Thinking mode (Q7) | Specific support confirmed through unified API examples | `LLM_ENABLE_THINKING` / `LLM_EXTRA_BODY` |
| Reasonable third-party Python dependencies (Q3) | Compatibility requirements pending [ORG] | `requirements.txt`; stdlib fallbacks for all three deps |

## 3. Unresolved — awaiting the organizer (do not hard-code assumed values)

| Item (Q ref) | Current mitigation |
|---|---|
| Per-request timeout, total runtime per case, token budget, model-call limit, retry limit (Q5) | Configurable (`LLM_TIMEOUT`, `CASE_TIMEOUT`, `TOTAL_TIMEOUT`, `MAX_CALLS_PER_CASE`, `MAX_REQUESTS_PER_CASE`); defaults unlimited; token usage now logged (WP-1) |
| Final result filename (`output.json` vs `results.json`) and data structure (Q9) | `OUTPUT_ALIASES` writes both names beside the primary (WP-3, done); primary name unchanged |
| Algorithm package size limit, dependency compatibility rules, resource registration template (Q2, Q3) | Whitelist build script `scripts/build_submission.py`; registration draft pending template |
| Model name, endpoint configuration method, default Thinking mode, supported parameters, API examples | Generic OpenAI-compatible client; nothing hard-coded |
| Complete input/output schemas, exit-code rules, platform-fault handling | Configurable field map / envelope / exit codes; see assumptions below |

## 4. Our assumptions (ASSUMED — not official rules)

| Item | Current behaviour | Where to change |
|---|---|---|
| Input envelope | list, `{cases:[…]}`, or single case all accepted | `inputs.split_envelope` |
| Input / output paths | `input.json` / `output.json` in the working directory | `INPUT_PATH`, `OUTPUT_PATH`, `OUTPUT_ALIASES` |
| Output field names | `case_features`, `diagnostic_discussion`, `treatment_plan`, `evidence`, `review_items`. The data-work brief once named the third field `plan`; if official, set `OUTPUT_FIELD_MAP={"treatment_plan":"plan"}` | `OUTPUT_FIELD_MAP`, `OUTPUT_FIELDS` |
| Extra fields (`evidence`, `review_items`) allowed? inline citations? | separate arrays; inline off | `OUTPUT_FIELDS`, `INLINE_CITATIONS=1` |
| Output language | follows the records | `OUTPUT_LANG` |
| `record_cutoff` format and semantics | `T0` accepted as a symbolic marker: supplied facts are available at T0, no calendar filtering without a date mapping; ISO / common dates: date-only = end of day, UTC offsets honoured, post-cutoff sources/sentences withheld | `CUTOFF_MODE`, `textutil.parse_cutoff` |
| Model API protocol | OpenAI-compatible `POST {base}/chat/completions`, bearer key; exact endpoint/model/JSON-mode unconfirmed | `medtrace/llm.py` |
| Env variable names | `LLM_*` plus common aliases | `medtrace/config.py` |
| Time limits | none by default; `TIME_RESERVE_SECONDS` is our safety margin, not an official limit | `CASE_TIMEOUT`, `TOTAL_TIMEOUT`, `LLM_TIMEOUT` |
| Concurrency / rate limits | sequential | `WORKERS` |
| Exit codes | 0 / 1 / (2 with `STRICT_EXIT`) | `medtrace/runner.py` |
| Malformed or empty case | emitted in place with an explanatory note and review item | `pipeline.run_case` |
| Log location / format | `logs/run_log.jsonl` + stderr | `LOG_DIR` |
| Python version | written for 3.10+, tested on 3.13 only | verify on 3.11 (WP-11) |
| Packaging (archive name, layout) | whitelist ZIP via build script | `scripts/build_submission.py` |

## Not done here (needs people or access)

- Run against the designated model; nothing in this repository is evidence about its clinical quality yet.
- Clinical review of the synthetic cases and annotations by the Clinical Lead; expansion to ~60 cases.
- Blinded two-reviewer scoring and adjudication (tooling ready: `eval/blind_review.py`).
- Team assignment, rules/deadline confirmation, presentation materials.
