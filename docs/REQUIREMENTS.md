# Competition requirements and acceptance boundaries

**English** | [简体中文](REQUIREMENTS.zh-CN.md)

The supplied consolidated guide, Appendix 3, defines the implemented runtime protocol. The latest organiser release takes precedence. Earlier Q&A naming uncertainties do not override this implementation of the complete local guide.

| Requirement | Implementation and regression coverage |
|---|---|
| Python 3.11, requires.txt, main.py without arguments | CI and isolated package entry-point tests |
| Only MODEL_NAME and complete ENDPOINT from .env beside main.py | Official parser; poisoned cwd/environment tests |
| No required key, Authorization, inherited credentials or proxies | Keyless client and transport tests |
| Fixed root input.json and output.json | Official configuration ignores environment path overrides |
| Array input; unique non-empty string case IDs | Task-level validation; exit 2 |
| Valid cutoff, unique string source IDs, string content | Per-case validation; failed records remain in place |
| Complete sections, evidence and review strings | Strict model parsing, final structure and case-local reference checks |
| Clinician-facing review_items | Official output excludes verifier/QA messages that quote the draft back at the reader; high-value findings such as diagnostic overconfidence are surfaced with clean wording; model, ledger, cutoff and knowledge-degradation items remain |
| Ordered output per input; failures and empty input supported | Batch tests |
| Complete batch then atomic publication | Official mode never publishes intermediate results; interruption tests |
| Official runtime safety ceiling | 300 s per case and 3600 s per batch in the no-argument entry point (safety values, not organizer limits); development remains unlimited; a deadline produces a schema-valid fallback record and still publishes the complete batch |
| Current-run run_log.json | Run IDs, case/request timestamps, counters, token usage and I/O hashes |
| Fixed prompt/parameter versions and seed | Code defaults, submission manifest, run_start configuration |
| Lawful, pinned, registered and bundled offline resources | No external KB by default; validated releases load from the package |
| Source/result correspondence | SHA-256 manifest and result-bundle checks reject changed outputs, stale logs and changed resources |

Development configuration requires --development (or development=True from evaluation modules). It retains legacy experiments; it cannot influence the official no-argument entry point.

The organizer's latest answers (Q10-Q13) do not change the runtime design: no prefix-cache dependence (caching may be disabled at evaluation, so timings can be slower); algorithms run in a CPU-only environment; no embedding service is used at runtime; any future vector retrieval must use the organizer's internal Embedding API, and a bundled local knowledge base or index must be pinned, registered and within the published size limit.

Current packaging is for testing; the team ID has not been assigned. Formal results require authorised cases and genuine completed-run logs. Mock outputs are not official results.

External acceptance still required: designated model/service version; final request, case and task limits; token/call/retry/concurrency budgets; package size and resource registration template; clinical review; team eligibility and signed declarations. Defaults are testing settings. For formal submission, render the project description in the organiser template and verify the ten-page limit.
