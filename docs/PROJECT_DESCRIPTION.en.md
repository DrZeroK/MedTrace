# MedTrace project description (test version)

**English** | [简体中文](PROJECT_DESCRIPTION.md)

MedTrace generates an initial hospital course note draft from admission materials, outputting case features, diagnostic discussion, plan, evidence and review items. Its use is limited to teaching, competition and research evaluation. Neither the input nor the generated results may be used directly for real clinical care.

## Method and improvements

1. Parse the materials cutoff, and filter content explicitly later than the cutoff by source and sentence; T0 is retained as the organiser marker with no calendar mapping.
2. Build a fact ledger that aggregates numbers, units, negation, pending-result information and possible conflicts.
3. Generate source-tagged statements using the fixed v3 prompt and the A2 flow. Defaults are temperature 0 and seed 37, with at most two logical calls; the second is used only to regenerate results that cannot be parsed or lack sections.
4. Verify numbers, units, negation, sources and completed/planned wording. Invalid references are removed, and unresolved issues become review items. Extra model repair calls are off by default.
5. Check the official input, complete medical sections, success/failure structure and case-local references. A failed case keeps its position; output.json is published atomically after the whole batch finishes, together with a checkable run_log.json.

The default official entry point reads only MODEL_NAME and the complete ENDPOINT from .env beside main.py and makes keyless HTTP calls; it ignores development-environment model aliases, paths, authentication and proxies. Development mode must explicitly use --development.

## Resources and reproduction

The test package contains source code, v1/v2 prompts in two languages, dependencies, an input example, documentation and a SHA-256 manifest. By default it carries no external knowledge base or model weights. A reviewed optional knowledge base can be bundled into the resources directory and is loaded automatically from that directory at run time, without depending on development-machine paths.

Algorithm packages and test result packages are built from allowlists. The build refuses to overwrite existing archives, and original packages remain in place. The submission manifest records the source commit, prompt fingerprint and per-file hashes; the run log contains this run's identifier, timestamps, model parameters, case mapping, call/retry counts, token usage and input/output digests.

## Validation and limitations

Automated checks cover the official no-argument entry point, isolation of invalid input, retry/failure on missing model sections, authentication and proxy isolation, complete result publication, log correlation and packaging exclusions. Offline mock results demonstrate the engineering flow and do not represent the medical quality of the designated model. Historical public-data experiments and their limitations are retained in the repository's docs/REPORT.md and are not current official results.

Rule checks cannot reliably judge whether clinical inferences are correct, nor detect every omission. Relative times, complex negation and abbreviations may still cause misjudgements. Repeated requests to the same model can produce different text even with a fixed seed. Acceptance against the designated service, final time limits/budget, clinical review and official resource permissions still require confirmation before the competition.

This file is the source of the short project description; before formal submission it must be laid out in the organiser template with the limit of no more than 10 pages verified, and this test version must not be presented as completed registration or formal acceptance.
