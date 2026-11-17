# Offline knowledge deployment

Status: the offline implementation is available; **no clinical release is approved**.
`knowledge/entries.jsonl` contains 300 terminology drafts, 30 lab-unit drafts,
24 adult internal-medicine card drafts and 10 nonclinical rule templates.
All are `draft`. The builder refuses an empty approved set and refuses to publish
templates. Source links are candidates for review, not evidence of permission or
clinical endorsement. No guideline PDFs or external case answers are bundled.

Domestic-source permission and clinical pre-review started on 2026-11-17, prioritizing
PMPH textbooks, Chinese professional-society guidelines and expert consensus documents.
See [first review report](../knowledge/reviews/2026-11-17-cn-review-01/REVIEW_REPORT.md).
All 364 entries remain draft, with separate permission/sign-off fields; AI source
alignment checks are not clinical approval. Original catalogs are preserved in that
batch's `before/` snapshot. Foreign sources remain available there for comparison.

Engineering validation on 2026-11-17: all 98 tests passed (including 15 knowledge
tests) on Python 3.14.7 / SQLite 3.53.4. The 15 knowledge tests were rerun after the
final log-handle fix and passed. New modules also parse with Python 3.10 syntax;
the target Python/runtime, designated model and clinical quality are not validated.

## Content review and release

1. Review `knowledge/sources.json` and each entry. Obtain permission to use and
   redistribute the intended content; fill the exact source edition and section.
   Freeze the source version before approval (including any revised guidelines).
2. Review canonical names and aliases. Ambiguous aliases remain multiple matches;
   normalization never overwrites source text. Add short English aliases explicitly.
3. For labs, review accepted units against the analyte and method. The initial unit
   list is incomplete and supplies no reference intervals. An optional
   `reference_interval` has `low`, `high`, and nonempty `requires` (explicit population,
   specimen and method strings). Each required string must appear in the same fact.
   Missing conditions produce `insufficient`, not normal. No automatic conversion.
4. Replace risk templates with reviewed rules. Supported v1 numeric comparisons are
   strictly `above` and `below`, with analyte, unit, threshold and explicit `requires`.
   Equality is not a trigger. Templates have placeholder zero thresholds and must
   never be approved. Narrative contraindications and drug dose calculations are
   outside this numeric rule evaluator; they require reviewed cards and clinician review.
5. For every releasable entry, set `status=approved`, `reviewer`, `reviewed_at`, a
   cleared `license`, and an exact `locator`. Set `template=false` only after replacing
   all template content. Approval is a human content decision, never a builder action.
   For entries carrying review-batch records, also complete separate evidenced
   `permission_review` (`cleared`) and `clinical_review` (`signed_off`) decisions,
   each with reviewer/date/evidence. An AI pre-review cannot satisfy either decision.
6. Build a new absolute destination. Existing releases are never overwritten.

Example commands below use this checkout's absolute paths and an installed Python.
They deliberately require an approved input; the current draft catalog cannot publish.

```bash
/opt/homebrew/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/build_knowledge.py --source /Users/zerok/Documents/GitHub/MedTrace/knowledge/entries.jsonl --output /Users/zerok/Documents/GitHub/MedTrace/knowledge/releases/v1/knowledge.sqlite --version v1
```

Outputs are `knowledge.sqlite` and `knowledge.manifest.json`. The manifest contains
the database hash, counts, size, dependencies and approved source/permission records.
Retain releases and original sources. No automatic cleanup or deletion is performed.
On construction failure, preserve the incomplete artifact and use a new destination.

## Runtime and auditing

Set `KB_PATH` to the database's absolute path. Empty disables it. Startup verifies
the hash, schema, approval metadata, read-only SQL access and FTS5. Explicitly enabled
but invalid knowledge is fatal before generation. The batch and incremental entry
points preflight their audit output before model calls. Mid-case retrieval errors
degrade to the existing generation flow with a visible review item.

Retrieval uses case text **after record cutoff filtering**, Chinese bigrams with term
frequency, whole English terms and short aliases; FTS5 BM25 ranks titles above bodies.
It requires an exact topic/alias anchor and selects at most 5 complete cards totaling
2,500 text characters. An adult card requires an explicitly documented age 18–120;
unknown or conflicting ages do not enable it. Negative/pending terms may retrieve
context, but their original polarity is preserved in the ledger and audit.
Symptom-only semantic matching and cross-sentence rule applicability are deliberately
not inferred. Improve aliases using the dev split before considering embeddings.

Only A1/A2/S2/A3 receive knowledge; A0 remains the comparison baseline. There are no
extra model calls for retrieval. General numeric knowledge must quote a supplied
approved card exactly in a separate `basis=knowledge` statement; matching a number
alone cannot bypass patient-value verification. An exact approved quotation validates
its provenance only: it does not establish suitability for the patient.

`output.json` keeps its existing schema. `output.json.knowledge_audit.json` records
run ID, input/output hashes, knowledge version/hash, source metadata, per-case
normalization with polarity, retrieved cards, rule states and final statement references.
An ID-valid reference still requires clinical support review. Compare output hashes
before consuming an audit; the two files are separately atomic, not a transaction.
The same sidecar is produced by incremental updates; per-case logs also carry audit
data for existing evaluation tooling. The sidecar is local clinical output and should
be retained/protected like the generated note.

## Evaluation and release gates

`eval/knowledge_questions.json` contains 80 self-authored provisional questions:
40 dev and 40 heldout, each with 32 answerable and 8 no-answer questions.
The heldout split must not be used for alias/card tuning. Clinical relevance annotation
is pending; this is a retrieval scaffold, not clinical validation or a performance claim.

Run from the checkout with Python's module search path set explicitly:

```bash
PYTHONPATH=/Users/zerok/Documents/GitHub/MedTrace /opt/homebrew/bin/python3 -m eval.knowledge --kb-path /Users/zerok/Documents/GitHub/MedTrace/knowledge/releases/v1/knowledge.sqlite --questions /Users/zerok/Documents/GitHub/MedTrace/eval/knowledge_questions.json --split dev --output /Users/zerok/Documents/GitHub/MedTrace/eval/results/kb-v1-dev.json
```

After clinical annotation, target Recall@5 ≥90%, false injection ≤5% and steady-state
retrieval/rules P95 ≤100 ms on the target machine. The evaluator reports retrieval
latency; benchmark the combined rule path separately. Engineering fixtures do not
establish these targets. Source metadata and referenced IDs must be complete/valid.

For generation comparisons, build a P0-only release (approved terms/labs) and a
P0+P1 release. Run the existing `eval.run_external` entry point three times with
`KB_PATH` empty, P0, and P0+P1, using distinct run names, the same public cases,
model, seed, prompt version, strategy A2 and call budget. Never use evaluation
answers as knowledge. On competition data, use only the designated service.
Have clinicians blindly compare diagnostic specificity, differential relevance,
plan relevance, numerical errors, references and severe errors. Any new severe error
blocks P1 activation; revise and test independent cases before retrying.

## Packaging and rollback

The submission builder takes optional `--knowledge /absolute/path/knowledge.sqlite`.
It validates that release and bundles exactly the database and manifest under
`resources/knowledge.sqlite` and `resources/knowledge.manifest.json`, with the resource
documentation. Draft content, evaluation questions and clinical answer datasets are
excluded. Configure KB_PATH to the absolute extracted resource path on the target.
Do not relocate a release independently from its companion manifest.

Validate Python >=3.10 and SQLite FTS5 on the target; run a mock smoke test without
public network access. Record database hash, prompt fingerprint, model configuration
and package size. Roll back by pointing KB_PATH to a retained prior release or clearing
it. Embeddings, vector services and case retrieval remain deferred until measured
lexical-retrieval failures justify them.
