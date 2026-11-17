# Competition requirements and acceptance boundaries

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
| Ordered output per input; failures and empty input supported | Batch tests |
| Complete batch then atomic publication | Official mode never publishes intermediate results; interruption tests |
| Current-run run_log.json | Run IDs, case/request timestamps, counters, token usage and I/O hashes |
| Fixed prompt/parameter versions and seed | Code defaults, submission manifest, run_start configuration |
| Lawful, pinned, registered and bundled offline resources | No external KB by default; validated releases load from the package |
| Source/result correspondence | SHA-256 manifest and result-bundle checks reject changed outputs, stale logs and changed resources |

Development configuration requires --development (or development=True from evaluation modules). It retains legacy experiments; it cannot influence the official no-argument entry point.

Current packaging is for testing; the team ID has not been assigned. Formal results require authorised cases and genuine completed-run logs. Mock outputs are not official results.

External acceptance still required: designated model/service version; final request, case and task limits; token/call/retry/concurrency budgets; package size and resource registration template; clinical review; team eligibility and signed declarations. Defaults are testing settings. For formal submission, render the project description in the organiser template and verify the ten-page limit.
