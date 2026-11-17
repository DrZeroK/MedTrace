# MedTrace — evidence-grounded initial progress notes

**English** | [简体中文](README.zh-CN.md)

Reads structured admission records (`input.json`), calls the configured (designated) LLM, and writes
`output.json` with, per case: **Case Features**, **Diagnostic Discussion**, **Diagnostic and Treatment Plan**,
**evidence** (statement → source ids) and **review items** (missing / conflicting / to-verify).

> **Status.** Tested end to end against a mock model and, on 26 development + 17 validation CMB-Clin cases, against a
> **non-designated commercial model** (qwen4-max, judge qwen-plus) on **public data only**; nothing has run on the
> designated competition service yet. See `docs/REPORT.md` §2.6 for what that run does and does not
> show. The I/O contract below is still an assumption until checked against the official technical instructions. See `docs/REQUIREMENTS.md` (what must be confirmed) and `docs/REPORT.md` (what has and
> has not been measured). This is a research/competition system, not a medical device; every note requires clinician review.

## Competition QA

See [Competition Technical Q&A](docs/COMPETITION_QA.md) for all nine organizer answers supplied by the project owner,
including offline resources, vLLM parameters, third-party API restrictions and pending submission requirements.
The document records the supplied answers; it does not certify the current implementation's compliance.

## Run

User-supplied textbook PDFs are available through a separate local full-text index;
see [textbook search](docs/TEXTBOOK_SEARCH.md) for keyword queries with source pages.

Offline knowledge support is implemented but disabled by default. The first content
catalog is **draft, not clinically approved**. See [knowledge deployment](docs/KNOWLEDGE_BASE.md)
for review, build, evaluation, packaging and rollback. Set `KB_PATH` to an approved
SQLite release's absolute path to enable it. Citations are written to a separate
`<output>.knowledge_audit.json`; the result JSON schema stays compatible.

```bash
pip install -r requirements.txt    # requests, python-dotenv, jsonschema (identical to requires.txt; Python >= 3.10)
cp .env.example .env               # set LLM_API_BASE / LLM_API_KEY / LLM_MODEL
python main.py                     # input.json -> output.json, logs/run_log.jsonl
```

Offline (no model needed): leave `LLM_API_BASE=mock://`, `cp input.example.json input.json`, `python main.py`.

Exit codes: `0` output written and schema-valid · `1` fatal (input unreadable, output unwritable, model not
configured) · `2` only with `STRICT_EXIT=1` when any case fell back.

## Submission package

```bash
python scripts/build_submission.py            # whitelist-only ZIP -> dist/submission.zip (prints file list, size, git commit)
```

The archive contains only runtime material (`main.py`, `medtrace/` with prompts, `requirements.txt`,
`requires.txt`, `.env.example`, `README.md`, `docs/RESOURCE_REGISTRATION.md`, `input.example.json`) — never
`.env`, `data/`, `eval/`, `data_pipeline/` or `tests/`. Optional `--knowledge /absolute/path/knowledge.sqlite`
bundles a validated approved release and manifest. Resource registration is in
`docs/RESOURCE_REGISTRATION.md`; no clinical knowledge release is approved yet, and the organiser's template is pending.

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
| `A2` *(default, strategy S1)* | deterministic verification; drops non-existent source ids; everything unresolved goes to `review_items`. `REPAIR_CALL=1` adds one targeted repair call when a high-severity finding exists (off by default) | 1 (2 with repair) |
| `S2` | model problem-list extraction with verbatim-quote check, then A2 | 2–3 |
| `A3` *(strategy S3)* | semantic review call returning patches; each patch must pass the deterministic verifier or it is rejected | 2 |

Prompts: `PROMPT_VERSION=v2` (concise, default) or `v1` (original long form). A second call is otherwise used only to
regenerate unparseable output; `MAX_CALLS_PER_CASE=1` forbids even that.

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
medtrace/llm.py         model client, retries          tests/                         83 regression / fault-injection tests
medtrace/runner.py      F  batch, logs, exit codes     docs/                          requirements, rubric, report, datasets
data_pipeline/          dataset audit, acquisition, QC, standardisation        data/standardized/   standardized external cases
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

## External data (Chinese clinical datasets)

```bash
python -m data_pipeline.acquire --list                 # audited datasets and whether they can be fetched automatically
python -m data_pipeline.acquire cmb_clin               # download (Apache-2.0), licence check, pinned sha256 -> data/raw/ (git-ignored)
python -m data_pipeline.cmb_clin                       # standardize + QC -> data/standardized/cmb_clin/
python main.py --input data/standardized/cmb_clin/cases.json --output out.json   # the standardized cases are valid input
python -m eval.run_external --dataset cmb_clin --split dev --variants A0,A1,A2  # diagnosis hit, differential recall, coverage
python -m data_pipeline.acquire medct_clinical_notes && python -m data_pipeline.medct_stress   # real-note stress test (aggregates only)
```
TypicalCase-DC (2,591 case reports in admission-record sections with gold diagnoses) is the larger evaluation set
but cannot be redistributed: place the Tianchi download in `data/raw/cblue/TypicalCase-DC/`, run
`python -m data_pipeline.typicalcase_dc`, then `python -m eval.run_external --dataset typicalcase_dc --split dev --tier A --limit 40`.

Audit and ranking: `docs/DATASETS.md`. Labelling rules: `docs/ANNOTATION_GUIDELINES.md`. QC report:
`data/standardized/cmb_clin/qc_report.md`.

## Declarations

- Model: only the endpoint configured in `.env`. Optional retrieval is entirely local via `KB_PATH`; no online retrieval or embedding is used.
- Data: `eval/cases.json` contains 16 synthetic teaching cases written for this project; no patient data.
  `data/standardized/cmb_clin/` is derived from CMB-Clin (Apache-2.0, textbook cases; see its `NOTICE.md`) and is used for evaluation only.
- Method: prompts in `medtrace/prompts/`, rules in `medtrace/verify.py`; no fine-tuning, no hidden reference answers.
