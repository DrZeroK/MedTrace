# MedTrace — evidence-grounded initial progress notes

Reads structured admission records (`input.json`), calls the configured (designated) LLM, and writes
`output.json` with, per case: **Case Features**, **Diagnostic Discussion**, **Diagnostic and Treatment Plan**,
**evidence** (statement → source ids) and **review items** (missing / conflicting / to-verify).

> **Status.** The software is complete and tested end to end against a *mock* model. It has **not yet been run
> against the designated model**, and the I/O contract below is an assumption until checked against the official
> technical instructions. See `docs/REQUIREMENTS.md` (what must be confirmed) and `docs/REPORT.md` (what has and
> has not been measured). This is a research/competition system, not a medical device; every note requires clinician review.

## Run

```bash
pip install -r requires.txt        # requests, python-dotenv, jsonschema  (Python >= 3.10; developed for 3.11)
cp .env.example .env               # set LLM_API_BASE / LLM_API_KEY / LLM_MODEL
python main.py                     # input.json -> output.json, logs/run_log.jsonl
```

Offline (no model needed): leave `LLM_API_BASE=mock://`, `cp input.example.json input.json`, `python main.py`.

Exit codes: `0` output written and schema-valid · `1` fatal (input unreadable, output unwritable, model not
configured) · `2` only with `STRICT_EXIT=1` when any case fell back.

## Input / output (assumed contract — configurable)

```json
[{"case_id": "…", "record_cutoff": "2026-03-02T18:00:00",
  "sources": [{"source_id": "S1", "content": "…"}]}]
```
A top-level list, an object wrapping a list (`cases`/`data`/`records`), or a single case are accepted; output mirrors the input envelope and order.

```json
[{"case_id": "…",
  "case_features": "…", "diagnostic_discussion": "…", "treatment_plan": "…",
  "evidence": [{"section": "case_features", "statement": "…", "source_ids": ["S1"]}],
  "review_items": [{"type": "missing|conflict|verify", "description": "…", "source_ids": []}]}]
```
Field names, field selection, envelope, inline citations and language are set in `.env`
(`OUTPUT_FIELD_MAP`, `OUTPUT_FIELDS`, `OUTPUT_ENVELOPE`, `INLINE_CITATIONS`, `OUTPUT_LANG`) — no code change needed
when the official schema is confirmed. Notes are written in the language of the records (English / Chinese).

## How it works

```
input.json ─ A input processing ─ B fact ledger ─ D generation (LLM) ─ E1 deterministic verification ─ F output.json
              validate, cutoff     numbers+units,   prompt carries      numbers, units, negation,       atomic write,
              (source- and         negatives,       ledger + rules;     dates/cutoff, references,       ordered,
              sentence-level)      pending/missing, statement-level     done-vs-proposed, support       per-case
                                   conflicts        source ids          │                               isolation
                                                                        └─ targeted repair / E2 semantic review (guarded patches)
```

| `PIPELINE` | What it adds | Model calls |
|---|---|---|
| `A0` | direct structured prompt (baseline) | 1 |
| `A1` | fact ledger in the prompt, hard evidence rules, statement-level attribution | 1 |
| `A2` *(default, strategy S1)* | deterministic verification; drops non-existent source ids; one targeted repair call only if a high-severity finding exists; everything unresolved goes to `review_items` | 1–2 |
| `S2` | model problem-list extraction with verbatim-quote check, then A2 | 2–3 |
| `A3` *(strategy S3)* | semantic review call returning patches; each patch must pass the deterministic verifier or it is rejected | 2 |

`MAX_CALLS_PER_CASE=1` gives a strict single-call run (findings are flagged instead of repaired).

Reliability properties (all covered by tests): a complete, valid `output.json` exists from the first second
(seeded with verbatim-extract notes, replaced case by case, atomic rename); a case can never abort the batch;
model failure, malformed JSON, timeouts and exhausted budgets degrade to a flagged extract-only note; nothing dated
after `record_cutoff` reaches the model; the verifier never rewrites clinical text.

## Layout

```
main.py                 entry point                    medtrace/prompts/v1/{en,zh}/   version-controlled prompts
medtrace/inputs.py      A  input + cutoff              medtrace/mock_llm.py           offline mock + fault injection
medtrace/ledger.py      B  fact ledger                 medtrace/mock_server.py        HTTP mock (500s, timeouts, garbage)
medtrace/pipeline.py    C–E orchestration, guards      medtrace/update.py             incremental record updates
medtrace/verify.py      E1 deterministic checks        eval/                          cases, ablation, perturbation, blinded review
medtrace/llm.py         model client, retries          tests/                         33 regression / fault-injection tests
medtrace/runner.py      F  batch, logs, exit codes     docs/                          requirements, rubric, report
```

## Reproduce the experiments

```bash
python -m unittest discover -s tests                         # or: pytest
python -m eval.run_ablation --name my_run                     # A0/A1/A2/S2/A3 on eval/cases.json with the configured model
python -m eval.run_ablation --name heldout --split heldout    # untouched validation subset — use for final selection only
python -m eval.perturb --variant A2                           # one-fact-changed robustness tests
python -m eval.blind_review export eval/results/my_run        # blinded, randomised packet + score sheets
python -m eval.blind_review score  eval/results/my_run        # per-variant metrics, kappa, adjudication list
python -m medtrace.update previous_input.json new_input.json  # regenerate after records change
```
Each run directory stores outputs, per-case metrics, the full configuration (without the key), prompt fingerprint and seed.
Remote inference is not guaranteed byte-identical even at temperature 0; compare runs by metrics, not by diff.

## Declarations

- Model: only the endpoint configured in `.env`. No other model, external service, retrieval or internet access is used at run time.
- Data: `eval/cases.json` contains 16 synthetic teaching cases written for this project; no patient data.
- Method: prompts in `medtrace/prompts/`, rules in `medtrace/verify.py`; no fine-tuning, no hidden reference answers.
