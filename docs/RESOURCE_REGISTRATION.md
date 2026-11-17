# Resource registration (MedTrace)

Status: **draft — the organiser's registration template is pending [ORG]** (competition Q&A Q2).
This document follows the fields the Q&A asks for (name, source, version, purpose, size, dependencies)
and will be reformatted once the official template is published. The authoritative version of every
code resource is the git commit of the submission package; `python scripts/build_submission.py`
prints that commit and the prompt fingerprint at build time.

## Knowledge bases

**No approved clinical release yet.** Optional SQLite knowledge support is implemented;
`KB_PATH` is empty by default. Draft content under `knowledge/` is not shipped.
When an approved release is supplied to `build_submission.py --knowledge`, its database
and manifest ship under `resources/`. The manifest registers each entry's source,
version, purpose/type, scope, permission and reviewer, plus total size, SHA-256 and
dependencies (Python >=3.10, SQLite FTS5). See `docs/KNOWLEDGE_BASE.md`.

## Rule bases

**No approved external rule release yet.** The deterministic verifier is ordinary Python (`medtrace/verify.py`,
`medtrace/textutil.py`, `medtrace/ledger.py`); its negation/uncertainty cue lists were tuned on public
datasets (CHIP-CDEE train split) but no labelled data is shipped or loaded at run time.

## Code resources

| Name | Source | Version | Purpose | Dependencies |
|---|---|---|---|---|
| Prompt templates `medtrace/prompts/v1`, `medtrace/prompts/v2` | self-authored | git commit of package; fingerprint printed by build script (v2 default) | generation / extraction / repair / review instructions (zh + en) | none |
| Verifier rules `medtrace/verify.py`, `medtrace/textutil.py`, `medtrace/ledger.py` | self-authored | git commit of package | deterministic fact grounding, negation/number/unit checks, omission flags | none |
| Pipeline / client / runner `medtrace/*.py`, `main.py` | self-authored | git commit of package | orchestration, OpenAI-compatible client, batch I/O | see below |

## Third-party dependencies (`requirements.txt`, identical to `requires.txt`)

| Package | Pin | Purpose | Fallback if absent |
|---|---|---|---|
| requests | >=2.28 | HTTP client | urllib (stdlib) — `medtrace/llm.py` `_post` |
| python-dotenv | >=1.0 | `.env` loading | minimal parser — `medtrace/config.py` `load_dotenv_files` |
| jsonschema | >=4.0 | output schema validation | manual required/type checks — `medtrace/note.py` |

The runtime completes with none of the three installed (stdlib fallbacks). No runtime install or
download occurs; the only network use is the configured model endpoint (competition Q&A Q3).

## Data

No dataset is bundled in the submission package. Development datasets (CMB-Clin, TypicalCase-DC,
CHIP-CDEE, MedCT) live under git-ignored `data/` and are used only offline for evaluation; those
obtained under Tianchi terms are not redistributed.

## Pending organiser items [ORG]

- Official registration template and required fields (Q2).
- Algorithm package size limit and dependency compatibility rules (Q3).
