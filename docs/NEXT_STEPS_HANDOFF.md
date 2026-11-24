# MedTrace — next-steps handoff

**English** | [简体中文](NEXT_STEPS_HANDOFF.zh-CN.md)

Written 2026-11-17 for a coding model taking over implementation. Read this file, then `docs/COMPETITION_QA.md`,
then the code you are about to touch. Do not treat README or report claims as proof; section 2 lists what was
re-verified against the code on the date above.

> **Reproducibility note (2026-11-17):** generated output used to depend on Python's per-process hash seed (the
> verifier iterated a `set`, so review-item order changed between identical runs). Fixed; the test
> `EndToEnd.test_output_independent_of_hash_seed` guards it. When comparing two runs byte for byte, any remaining
> difference is real. Avoid iterating sets or dicts built from sets where the order reaches the output.

## 1. Repository state

| Item | Value |
|---|---|
| Repository | https://github.com/DrZeroK/MedTrace |
| Working branch | `medtrace-pipeline` (all current work; **not merged** into `master` beyond PR #1) |
| State audited | commit `69640e1` (merge of `master` into `medtrace-pipeline`); this file is added in the commit after it |
| `master` | `149d906`: PR #1 (first pipeline version + 3 review fixes) plus the competition Q&A docs. About 20 later commits on `medtrace-pipeline` are not on `master` |
| Open pull requests | none (PRs #1, #2 and #4 merged into `master`) |
| `AGENTS.md` / `CLAUDE.md` | none in the repository |

Local-only, git-ignored material that a fresh clone will **not** have:

- `.env` — holds the project owner's commercial API key. Never commit it.
- `data/raw/` — downloaded datasets (CMB, MedCT notes, CBLUE Tianchi archives).
- `eval/results/` and `eval/archive/` — run outputs, kept locally only (not committed). `eval/archive/` holds the
  real-model development runs behind `docs/REPORT.md` §2.6; the numbers in the report are the record, the raw
  outputs are not redistributed.

## 2. Baseline, verified on the audited commit

Commands were re-run from the repository root with Python 3.11.16 on 2026-11-19.

| Check | Command | Result |
|---|---|---|
| Unit / integration tests | `python -m unittest discover -s tests` | 208 tests, all pass (about 27 s) |
| End-to-end on mock | `LLM_API_BASE=mock:// python main.py --input input.example.json --output /tmp/out.json` | exit 0, 1 case, schema-valid |
| Runtime import chain | import `medtrace.runner` and list loaded project modules | only `medtrace.*`; `eval/` and `data_pipeline/` are not imported at run time |
| Request payload | local HTTP capture of one `LLMClient.chat` call | `POST {base}/chat/completions` with `model, messages, temperature, stream=false`; `response_format` only if `LLM_JSON_MODE=1`; anything in `LLM_EXTRA_BODY` is merged at top level (so `seed` and `chat_template_kwargs` *can* be sent, but only through that generic JSON option) |
| Defaults with no `.env` | `load_config()` | `PIPELINE=A2`, prompts `v2`, `MAX_CALLS_PER_CASE=2`, `REPAIR_CALL` off, `LLM_TIMEOUT=600`, `LLM_MAX_RETRIES=2`, `temperature=0`, no `max_tokens`, no JSON mode, official safety ceilings 300 s/case and 3600 s/batch (development remains unlimited), `output.json` |

Not re-run for this handoff (they need a model endpoint or local-only data): any real-model evaluation,
`data_pipeline.*` builds, CHIP-CDEE negation scoring, MedCT stress test.

**Python version:** the complete suite was re-run on Python 3.11.16 (the version named in the project brief) on 2026-11-19; 208 tests pass. The code uses `X | None` annotations with `from __future__ import annotations`, so 3.10+ should work.

## 3. Requirements: confirmed, assumed, unresolved

Source for "confirmed": `docs/COMPETITION_QA.md` (organizer answers supplied by the project owner; no official
document URL or version). Later official specifications override it.

### 3.1 Confirmed by the organizer Q&A

| # | Requirement | Current implementation |
|---|---|---|
| C1 | No external third-party APIs at evaluation; inference only through the designated self-hosted vLLM Qwen service. Competition practice and evaluation cases must never be uploaded to third-party platforms (Q8) | Runtime calls only the configured endpoint. **But** the only real-model evidence so far used the owner's commercial `qwen4-max` / `qwen-plus` endpoint, on public CMB-Clin cases only. `.env.example` contains a commercial-endpoint example line that should be reworded (WP-5) |
| C2 | No public internet during evaluation; no runtime install or download (Q3) | Runtime needs no network except the model endpoint. `data_pipeline/acquire.py` downloads data but is development-only and not imported at run time |
| C3 | Local knowledge bases, rule bases, retrieval and multi-stage algorithms are permitted if lawfully sourced, version-pinned, bundled and offline (Q1) | No knowledge base or retrieval exists. The verifier is rule code, not a registered resource |
| C4 | Resources must be registered (name, source, version, purpose, size, dependencies); teams with none state "None" (Q2). Template pending | No registration document exists (WP-4) |
| C5 | Complete dependency documentation "such as `requirements.txt`" (Q3) | Only `requires.txt` exists (name taken from the original project brief). No `requirements.txt` (WP-4) |
| C6 | `seed` may be passed at the top level of the request body; may be omitted with an explanation if unsupported (Q4) | **Done (WP-1, 0aaad62; updated 2026-11-19):** first-class `LLM_SEED`; the official entry point sends 42 and, if a 400 explicitly rejects `seed`, strips it and retries once for the rest of the run |
| C7 | Thinking is controlled with `chat_template_kwargs: {"enable_thinking": false}`; omission means the server default, which is not necessarily "off" (Q7) | **Done (WP-1, 0aaad62; updated 2026-11-19):** first-class `LLM_ENABLE_THINKING`; the official entry point sends `false`; development omits unless set; a 400 naming the field is stripped and retried once |
| C8 | Retries initiated by the participant's algorithm count toward the model-call budget, in principle (Q5) | **Done (WP-2, 0aaad62):** `MAX_REQUESTS_PER_CASE` counts every HTTP attempt incl. retries (default 0 = unlimited until the organiser publishes a limit); `MAX_CALLS_PER_CASE` still counts logical calls; official time ceilings bound the practical total |

### 3.2 Permitted in principle, subject to the deployed version / unified API specification

- `temperature` and `response_format` (Q6/Q14). `json_object` is implemented as `LLM_JSON_MODE`; `json_schema` is not implemented. The official path sends no `response_format` yet; the exact parameter and JSON Schema feature subset is pending.
- Selecting a Thinking mode per strategy (Q7); "specific support will be confirmed through unified API examples".
- Reasonable third-party Python dependencies (Q3); compatibility requirements pending.

### 3.2a Organizer answers Q10-Q13 (2026-11-18)

- **Prefix caching (Q10):** centrally managed and planned to be disabled at official evaluation; no cachemark is needed. Do not rely on cache hits for latency or cost budgets.
- **Reproducibility (Q11):** a fixed seed is permitted but does not guarantee identical output; pin code, dependencies and knowledge-resource versions and control in-algorithm randomness.
- **Embedding (Q12):** an internal-network Embedding API (e.g. BGE-M3) is planned on the Ascend stack; self-deploying GPU/NPU embedding models is not supported in principle; local knowledge bases and pre-built indexes may be submitted within a size limit to be published.
- **Hardware (Q13):** model inference runs on the organizer's Ascend stack; the participant algorithm runs in an isolated CPU-only environment and must not deploy additional LLMs or GPU/NPU inference services. OS/CPU/memory/storage/runtime limits are still pending.
- **Design fit:** the current runtime uses a deterministic ledger plus optional SQLite FTS; it does not use embeddings, GPU/NPU work or prefix caching. Any future vector RAG must use the organizer's Embedding API.

### 3.2b Organizer answers Q14-Q16 (2026-11-20)

- **response_format (Q14):** vLLM Ascend natively supports `text`, `json_object`, and `json_schema`; `json_schema` is permitted in principle. The exact parameter range and JSON Schema features are subject to compatibility validation of the deployed version. The official path currently sends no `response_format`; `json_object` exists as a development option; `json_schema` is not implemented. Extend the acceptance probe after the parameter list and examples are published.
- **Embedding resource scoring (Q15):** the internal Embedding API's NPU resources are organizer-managed; their memory and compute usage are not counted in the participant hardware score. Call count and usage are centrally managed, so quota and latency remain the constraints, not hardware score.
- **BGE-M3 (Q16):** BAAI/bge-m3 on Ascend 910B; Dense 1024, max 8192 tokens, Chinese/multilingual, FP16, no Instruction for normal retrieval, Dense API first. A low-frequency HTTP test API is planned; endpoint, authentication, examples, quota, and final model version are pending. Current runtime uses no embedding; the BM25 textbook experiment is CPU-only, draft and outside the submission.
- **Decision:** keep the no-embedding/BM25 default; do not bundle a vector index until the final model version, endpoint/auth/quota, and index size limit are published. Test `json_object` first, then `json_schema` if the subset is suitable.

### 3.3 Unresolved — awaiting the organizer. Do not hard-code assumed values

- Per-request timeout, total runtime per case, token budget, model-call limit, retry limit (Q5).
- Final result filename (`output.json` vs `results.json`) and result data structure (Q9).
- Algorithm package size limit, dependency compatibility rules, resource registration template (Q2, Q3).
- Qwen model name, endpoint configuration method, default Thinking mode, supported parameters, API examples.
- `response_format`/`json_schema` parameter list, supported Schema feature subset, and examples.
- Embedding endpoint, authentication, call examples, quota, and final BGE-M3 version/precision.
- Complete input and output schemas, exit-code rules, platform-fault handling.

### 3.4 Implementation assumptions (ours, not the organizer's)

All 20 rows of `docs/REQUIREMENTS.md` were written **before** the Q&A and several are now stale (rows 6, 10, 11,
12, 13, 15). Key assumptions still in the code: output field names (`treatment_plan`; the project brief once said
`plan`), envelope mirroring, `evidence` / `review_items` as extra arrays, cutoff semantics, exit codes 0/1/2,
bearer-token auth, environment variable names (`LLM_API_BASE` and aliases).

## 4. Audit findings

### 4.1 Input / output and failure handling — solid, schema unconfirmed
- `medtrace/inputs.py`: accepts a list, a wrapped list or a single case; malformed cases are isolated; cutoff applied at source and sentence level (explicit dates only; UTC offsets handled).
- `medtrace/runner.py`: seeds a complete valid output file first, replaces case by case, atomic rename; exit 0 / 1 / 2 (`STRICT_EXIT`).
- Gaps: one output path only (no `results.json` alias); schema and exit codes are assumptions.

### 4.2 Designated Qwen / vLLM integration — generic, not yet targeted
- `medtrace/llm.py` speaks OpenAI-compatible chat completions. `seed` and `chat_template_kwargs` are first-class; the official entry point sends seed 42 and `enable_thinking: false`. A 400 that explicitly names an unsupported field strips that field and retries once, caching the decision for the run. `reasoning_content` in responses is ignored (correct), `<think>` blocks are stripped.
- Not yet exercised against the competition vLLM server; real-model evidence used commercial hosted endpoints.
- The official path still sends no `response_format`. `json_object` is available in development; `json_schema` is not implemented. After the organizer publishes the parameter list and examples, extend `scripts/api_acceptance.py` to probe them; reuse the 400 field-compatibility fallback.

### 4.2a Endpoint acceptance script
- `python scripts/api_acceptance.py` uses the official two-key `.env`; `--development` uses the development env; `--repeats 1-5`, `--timeout`, `--json-out`.
- It sends only a tiny synthetic JSON prompt. It reports the endpoint used verbatim, Authorization presence, seed/thinking compatibility, HTTP/JSON status, latency, and prompt/completion/total/reasoning/cached tokens.
- Exit 0 = HTTP and JSON checks pass (and official mode sent no Authorization); 1 = HTTP/JSON failure or official Authorization; 2 = configuration or mock-endpoint error.
- The script is development-only and is not shipped in the submission ZIP.

### 4.3 Runtime, token, call, timeout, retry accounting — the weakest area
- Tokens: `CallStats` accumulates prompt/completion/total tokens and `usage_missing`; `run_end` carries run totals.
- Calls: `CallStats` tracks `calls`, `http_attempts`, `retries`; `MAX_REQUESTS_PER_CASE` counts every HTTP attempt and `MAX_CALLS_PER_CASE` counts logical calls (see C8).
- Time: the official no-argument entry point applies safety ceilings of 300 s/case and 3600 s/batch; development `CASE_TIMEOUT`/`TOTAL_TIMEOUT` still default to unlimited. These are not the organizer's Q5 limits and must be updated when those are published. A deadline produces schema-valid fallback records and still writes the complete batch.
- `logs/run_log.jsonl` records per-case calls, attempts, retries, token use, latency, payload-compatibility events and final verifier finding details; `run_end` carries run totals.

### 4.4 Offline deployment and resource registration — not started
- No packaging script, no `requirements.txt`, no registration document, no offline-install check.
- Repository carries development material that should not ship (`eval/archive/` 4 MB, `data/standardized/`, `data_pipeline/`, `tests/`).
- Runtime falls back to stdlib if `requests`, `python-dotenv` or `jsonschema` are missing (tested earlier in a bare venv).

### 4.5 Patient-fact traceability vs medical knowledge
- Every generated statement carries `sources`; `evidence` is derived deterministically; invalid ids are dropped (A2).
- Official `review_items` exclude verifier/QA messages that quote the draft; those findings remain in the run log. `overconfident` is allowlisted and surfaced with clean wording because diagnostic certainty affects management. Model, ledger, cutoff and knowledge-degradation items remain clinician-facing.
- Narrative sections are rendered as prose (one paragraph per section) in both development and official output. Evidence stays in the separate `evidence` array.
- Batch A is **APPROVED** (2026-11-19): Change 1 approved; Change 2 approved with edits (add `初步诊断` / `working diagnosis` wording). The project owner waived the formal signature. Approval record and revised snapshot hashes: `docs/CLINICAL_REVIEW_BATCH_A.md` (Chinese: `docs/CLINICAL_REVIEW_BATCH_A.zh-CN.md`). Keep the approved wording frozen in regression tests.
- The deterministic verifier checks Case Features strictly, the discussion lightly (unit-bearing numbers, negation flips at low severity), the plan almost not at all.
- There is **no explicit separation** between patient facts and model medical knowledge inside the discussion and plan: a statement's `kind` is `assessment|differential|uncertainty|investigation|treatment|monitoring`, with no "knowledge" marker. There is no retrieved knowledge at all today, so nothing to register.
- No embedding is used at runtime; the BM25 textbook RAG remains draft, CPU-only and outside the submission. If dense RAG is added, call the organizer's Embedding API (BGE-M3 Dense 1024, 8192 tokens, no Instruction) and keep a BM25/no-embedding fallback.
- Verifier precision on unseen model prose is **not established**: each fresh batch produced new false-alarm patterns (`docs/REPORT.md` §2.6). High-severity findings are surfaced as review items only; the repair call is off by default.

### 4.6 Chinese clinical data and evaluation
- `data_pipeline/`: audited registry of datasets; CMB-Clin (74 cases, Apache-2.0, committed); TypicalCase-DC (2,578 cases, 836 clean, local only); CHIP-CDEE negation test (held-out F1 0.982); MedCT real-note stress test (0 false alarms on verbatim text).
- `eval/`: `run_ablation` (16 synthetic cases, mock fault injection), `run_external` (standardized datasets), `judge_dx` (judge-model diagnosis scoring), `reverify` (offline verifier replay), `perturb`, `blind_review`.
- No dataset contains reference first-progress-note text; no clinician has reviewed any output.

### 4.7 Real-model evidence vs mock-only evidence

| Evidence | Model | Status |
|---|---|---|
| 26 dev + 17 validation CMB-Clin cases, variants A0 / A1 / A2, prompts v1 and v2 | commercial `qwen4-max`, judge `qwen-plus` | Real, archived in `eval/archive/`. **Not the designated model.** Diagnosis scores are judge-model proxies on 13–20 cases |
| Fault-injection ablation, perturbation mechanics, all failure-handling tests | mock | Software behaviour only; says nothing about clinical quality |
| Negation F1, verbatim false-alarm rates | no model | Rule-level, real text |
| CMB-Clin test split (30), TypicalCase-DC, synthetic `must_not` checks, S2, A3, perturbations with a real model, blinded review | — | **Not done** |
| Anything on the competition's vLLM Qwen | — | **Not done; no access yet** |

## 5. Work packages

Rules for every package: keep `python main.py` working with no arguments; keep the output record fields and
`OUTPUT_FIELD_MAP` / `OUTPUT_FIELDS` behaviour; do not change defaults that affect generated text unless the
package says so; add or update tests; all existing tests must still pass; never commit `.env`, `data/raw/`,
or anything from Tianchi downloads.

Legend: **[ORG]** needs organizer clarification · **[MODEL]** needs designated-model access · **[CLIN]** needs clinical review.

### P0 — required for a compliant submission

#### WP-1 First-class vLLM request parameters and token usage capture
*Depends on: nothing. Recommended first package.*
- Files: `medtrace/config.py`, `medtrace/llm.py`, `medtrace/pipeline.py` (log fields only), `.env.example`, `tests/test_medtrace.py`.
- Steps:
  1. Add settings `LLM_SEED` (int, empty = omit) and `LLM_ENABLE_THINKING` (`true` / `false`, empty = omit) to `Config` and `load_config`.
  2. In `LLMClient._chat`, when set, send `"seed": <int>` at the top level and `"chat_template_kwargs": {"enable_thinking": <bool>}`. Apply `LLM_EXTRA_BODY` last so it can still override. When unset, the fields must be absent (server default).
  3. Parse the response `usage` object when present; add `prompt_tokens`, `completion_tokens`, `total_tokens` to `CallStats` (summed over attempts that returned 200). Missing `usage` must not fail the call.
  4. Add those three fields to the per-case log entry in `Pipeline.run_case`, and run totals (tokens, calls, HTTP attempts) to the `run_end` event in `runner.py`.
  5. Document both settings in `.env.example` with the Q&A wording (seed optional; omission of thinking = server default).
- Acceptance: payload-capture tests prove (a) neither field is sent by default, (b) each is sent correctly when configured, (c) `LLM_EXTRA_BODY` overrides; a test server returning `usage` yields correct per-case and run totals; a response without `usage` still succeeds; generated notes on the mock are byte-identical before and after.
- Validate: `env -u LLM_API_BASE python -m unittest discover -s tests` and `LLM_API_BASE=mock:// python main.py --input input.example.json --output /tmp/out.json`.

#### WP-2 Unified model-call budget (retries count)
*Depends on: WP-1 (same files). Limit values **[ORG]**.*
- Files: `medtrace/llm.py`, `medtrace/config.py`, `medtrace/pipeline.py`, tests.
- Steps: introduce `MAX_REQUESTS_PER_CASE` (0 = unlimited) counting **every HTTP attempt**, retries included; refuse an attempt that would exceed it (raise `BudgetExceeded`, which already degrades to a flagged note); keep `MAX_CALLS_PER_CASE` semantics; record `budget_exhausted` in the case log. Do not invent an official number. Update 2026-11-19: the official entry point enforces 300 s/case and 3600 s/batch safety ceilings (not organizer limits); `MAX_REQUESTS_PER_CASE` remains 0.
- Acceptance: with `MAX_REQUESTS_PER_CASE=2` and a server failing every request, exactly 2 HTTP requests are made for the case and the output is still schema-valid; existing retry tests pass.

#### WP-3 Result filename compatibility **[ORG]**
*Depends on: nothing.*
- Files: `medtrace/config.py`, `medtrace/runner.py`, `.env.example`, tests.
- Steps: add `OUTPUT_ALIASES` (comma list, default empty); after each atomic write of the primary file, write identical content atomically to each alias in the same directory. Do not change the default primary name. Document that `OUTPUT_ALIASES=results.json` covers both names during prechecks (Q9).
- Acceptance: with the alias set, both files exist, are byte-identical and valid at every checkpoint; with it unset, behaviour is unchanged.

#### WP-4 Offline packaging, dependency file and resource registration **[ORG] for template and size limit**
*Depends on: nothing.*
- Files: new `requirements.txt`, new `scripts/build_submission.py`, new `docs/RESOURCE_REGISTRATION.md`, `README.md`.
- Steps: (1) add `requirements.txt` with the same pins as `requires.txt` and keep both in sync with a test; (2) write a build script producing a ZIP containing only `main.py`, `medtrace/` (prompts included, no `__pycache__`), `requirements.txt`, `requires.txt`, `.env.example`, `README.md`, and the registration document — no `eval/`, `data/`, `data_pipeline/`, `tests/`, `.env`; print the file list and total size; (3) write the registration document: knowledge bases "None", rule bases "None beyond program code", list prompts and verifier rules as code with version = git commit, dependencies with versions; mark the template as pending.
- Acceptance: unzip into an empty directory, create a fresh virtualenv, `pip install -r requirements.txt`, run `LLM_API_BASE=mock:// python main.py` on `input.example.json` with network otherwise unused; a test asserts the ZIP contains no `.env`, no `data/`, no `eval/`.

#### WP-5 Documentation reconciliation with the Q&A
*Depends on: WP-1 to WP-4 for final wording; can start now.*
- Files: `docs/REQUIREMENTS.md`, `README.md`, `.env.example`, `docs/REPORT.md` (status lines only).
- Steps: rewrite `REQUIREMENTS.md` into three tables (confirmed / permitted in principle / unresolved) following section 3 of this file, keeping every qualification from the Q&A; replace the commercial-endpoint example in `.env.example` with a neutral placeholder and a warning that only the designated service may be used for competition cases; in `README.md` state that real-model results so far come from a non-designated commercial model on public data.
- Acceptance: no statement in those files presents an assumption as an official rule; `grep -n dashscope` returns nothing outside `eval/archive/`.

#### WP-6 Time-budget safety net **[ORG] for limits, [MODEL] for measurements**
*Depends on: WP-1, WP-2.*
- Files: `medtrace/runner.py`, `medtrace/pipeline.py`, `medtrace/config.py`, tests.
- Steps: when `CASE_TIMEOUT` is set, cap each request's timeout by the remaining case time (already done) **and** skip optional steps (regeneration, repair) when the remaining time is below a configurable reserve; log `time_budget_skipped`. Add a `--dry-run-latency` style summary to the run log (p50 / max per case). No default limit is to be invented.
- Acceptance: with a slow mock server and `CASE_TIMEOUT=5`, every case finishes within about 5 s plus overhead with a valid flagged note; totals appear in `run_end`.

### P1 — needed for a defensible result

#### WP-7 First run against the designated vLLM service **[MODEL]**
- Blocked until endpoint, model name and API examples are provided. Then: confirm which of `seed`, `response_format`, `chat_template_kwargs` are accepted (the organizer says unsupported parameters should error explicitly); measure latency and tokens with Thinking on and off on CMB-Clin dev (`python -m eval.run_external --dataset cmb_clin --split dev --variants A0,A2 --workers 1`); record results in `docs/REPORT.md` under a new section clearly separated from §2.6.
- Only public or self-authored cases unless the organizer states that practice cases may be sent to that service (it is the designated one, so they presumably may; confirm).

#### WP-8 Verifier precision on unseen prose
**Done (see `docs/REPORT.md` §2.7).** Tuned on a 20-case tier-A dev sample (22 high findings, all false alarms, six recurring patterns fixed); held-out disjoint 40-case A2 sample raised 0 high-severity findings. CHIP-CDEE dev F1 0.9818 and CMB-Clin verbatim 0 false alarms held. MedCT regression not re-run (raw data not on this machine). Medium findings still unlabelled; the lexical verifier cannot catch true clinical errors.
*Depends on: a model endpoint (the owner's cloud endpoint or the designated service).*
- Files: `medtrace/verify.py`, `medtrace/textutil.py`, tests, `docs/REPORT.md`.
- Steps: generate notes for a 40-case TypicalCase-DC tier-A dev sample (`--tier A --limit 40`); hand-label every high-severity finding as true or false; fix only patterns seen at least twice; replay with `python -m eval.reverify`; then measure once on a *different* 40-case sample and report precision without further tuning. Re-run the CHIP-CDEE and MedCT regression scripts after each rule change.
- Acceptance: reported high-severity precision on the second, untouched sample; no regression on CHIP-CDEE dev F1 (0.982) or the verbatim zero-false-alarm checks.

#### WP-9 Final held-out comparison and clinician review **[CLIN]**
**In progress — materials ready, awaiting clinicians + designated model.** A proxy A0 vs A2 comparison (prompts v2) was run on the CMB-Clin **validation** split (17 cases, commercial qwen3.5-27b, public data) and a two-reviewer blinded packet exported to `eval/results/cmbclin_val_proxy/review/` (packet.md, scores_R1/R2.csv, sealed key.json). Automatic proxies: A0 dx_hit 53.8% / coverage 86.2% / 2 notes with high findings; A2 dx_hit 46.2% / coverage 90.8% / 1 note (n=13 eligible; not significant). The **test split (30 cases) is deliberately preserved** for the final comparison on the designated model. Clinician scoring/adjudication, rubric sign-off, and the 716+1 `review_required` case decisions are outstanding human tasks.
- Run the pre-registered comparison once on the CMB-Clin test split (30 cases): baseline A0 vs default A2 (prompts v2). Export with `python -m eval.blind_review export <run>` for two reviewers using `docs/CLINICAL_RUBRIC.md`; score and adjudicate. A clinician must also decide the 716 TypicalCase-DC cases and 1 CMB-Clin case held as `review_required`, and sign off the rubric.

#### WP-10 Mark knowledge-derived statements
**Done.** Optional `basis` (record/knowledge/inference) on discussion/plan statements, carried into evidence when set; verifier flags `knowledge_record_value`; prompts v2 a1 and mock updated; off-enum basis dropped at parse. Validated on the real-model holdout (WP-8).
*Depends on: nothing; prompt change needs WP-7 or another model run to validate.*
- Files: `medtrace/prompts/v2/*/a1.txt`, `medtrace/note.py`, `medtrace/verify.py`, tests.
- Steps: add an optional per-statement field `basis: "record" | "knowledge" | "inference"` for discussion and plan statements; carry it into `evidence` entries; require `sources` for `record`, forbid patient-specific numbers in `knowledge` statements (verifier check). Keep the three text fields unchanged.
- Acceptance: schema still validates; mock updated; a test shows a `knowledge` statement containing a record value is flagged.

#### WP-11 Python 3.11 and continuous checks
**Done.** `.github/workflows/ci.yml` runs the unittest suite (incl. the package smoke test) on Python 3.10/3.11/3.13 with `requirements.txt`, mock only; all green (actions on Node 24). No 3.11-specific breakage.
- Add a GitHub Actions workflow running the unit tests on Python 3.10, 3.11 and 3.13 with only `requirements.txt` installed, plus the WP-4 package smoke test. Fix whatever 3.11 surfaces.

### P2 — optional improvements, only with measured benefit

- **WP-12 Local knowledge base / retrieval** (permitted by Q1; must be registered under WP-4 and bundled offline). Candidate source already on disk locally: CMeIE-V2 relation triples — but they are under Tianchi terms, so licensing must be cleared before bundling. Evaluate against the no-retrieval default on held-out cases first.
- **WP-13 Per-finding uncertainty** in the ledger (currently sentence-level; 47 of 65 uncertain CHIP-CDEE findings covered).
- **WP-14 S2 and A3 with a real model**; keep only if they beat A2 under the published call and time limits.
- **WP-15 Expand the evaluation set** toward the planned 60 clinician-reviewed cases; synthetic set is 16.
- **WP-16 Merge `medtrace-pipeline` into `master`** through a pull request once P0 is done (owner's decision).

### Dependency summary

```
WP-1 ──► WP-2 ──► WP-6 ──► WP-7 [MODEL]
WP-3, WP-4 ─────► WP-5
WP-7 ──► WP-8 ──► WP-9 [CLIN]
WP-4 ──► WP-11        WP-10 (independent)        WP-12 needs WP-4 + licence clearance
```

## 6. Items that need a person

| Who | What |
|---|---|
| Organizer | Limits (timeout, runtime, tokens, calls, retries); result filename and schema; exit codes; package size; registration template; model name, endpoint, default Thinking mode, supported parameters; whether practice cases may be used for prompt development |
| Project owner | Designated-service credentials when available; decision on merging to `master`; what the CMF-NERD confidentiality undertaking permits |
| Clinician | Review of generated notes (blinded), rubric sign-off, held cases, reference first-progress notes |

## 7. Ready-to-copy prompt for the first work package (WP-1)

```
You are working in the MedTrace repository (https://github.com/DrZeroK/MedTrace), branch `medtrace-pipeline`.
Implement work package WP-1 from docs/NEXT_STEPS_HANDOFF.md: first-class vLLM request parameters and token usage capture.

Before editing, read: docs/NEXT_STEPS_HANDOFF.md (sections 3, 4.2, 4.3 and WP-1), docs/COMPETITION_QA.md (Q4, Q5, Q7),
medtrace/config.py, medtrace/llm.py, medtrace/pipeline.py (run_case and its log dictionary), medtrace/runner.py
(the emit calls), .env.example, and the Http and EndToEnd test classes in tests/test_medtrace.py.

Scope:
1. Config: add LLM_SEED (integer; empty or unset means "do not send") and LLM_ENABLE_THINKING ("true"/"false";
   empty or unset means "do not send"). Add matching Config fields and load them in load_config().
2. medtrace/llm.py: when configured, send "seed": <int> at the top level of the request body and
   "chat_template_kwargs": {"enable_thinking": <bool>}. Apply cfg.extra_body last so LLM_EXTRA_BODY still overrides.
   When not configured, neither key may appear in the payload.
3. Token usage: read the "usage" object from successful responses when present and accumulate prompt_tokens,
   completion_tokens and total_tokens on CallStats. A response without "usage" must still succeed. The in-process
   mock path contributes zero tokens.
4. Logging: add the three token counts to the per-case log entry built in Pipeline.run_case, and add run totals
   (tokens, logical calls, HTTP attempts, retries) to the "run_end" event in medtrace/runner.py.
5. .env.example: document both settings, stating that seed is optional and that omitting the thinking setting
   leaves the server default (which is not necessarily "off").

Constraints:
- Do not change any default that alters generated text; output on the mock model must be byte-identical before and after.
- Keep `python main.py` working with no arguments; keep the output record fields unchanged.
- Do not hard-code any official limit; none has been published.
- Do not touch eval/, data_pipeline/ or prompts. Do not commit .env or anything under data/raw/.
- Do not call any real model endpoint. Use the local HTTP server pattern already used in the Http tests.

Tests to add (tests/test_medtrace.py):
- payload capture: by default neither "seed" nor "chat_template_kwargs" is sent;
- with LLM_SEED=42 and LLM_ENABLE_THINKING=false both are sent with the exact shapes above;
- extra_body overrides both;
- a server returning usage {prompt_tokens: 5, completion_tokens: 7, total_tokens: 12} yields those totals in the
  case log; a server omitting usage still returns a valid note;
- run_end in logs/run_log.jsonl carries the run totals.

Validate with:
  env -u LLM_API_BASE python -m unittest discover -s tests
  LLM_API_BASE=mock:// python main.py --input input.example.json --output /tmp/out.json

All 50 existing tests must still pass. Commit on `medtrace-pipeline` with a clear message and push (no force-push).
Report: files changed, the new settings and their defaults, test counts before and after, the commit SHA, and
anything in the scope you could not complete and why.
```
