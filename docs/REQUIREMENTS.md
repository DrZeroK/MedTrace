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
| JSON output mode | vLLM supports text/json_object/json_schema in principle; exact parameter and Schema-feature subset pending. The official path sends no response_format; development can send json_object; json_schema is not implemented |
| Embedding service and hardware scoring | Internal Embedding API planned; its NPU resources are organizer-managed and not counted in the participant hardware score; call volume is managed. The runtime remains CPU-only and must not self-deploy vector models; the current design uses no embedding |
| BGE-M3 reference profile | Dense 1024, max 8192 tokens, Chinese/multilingual, FP16, no Instruction, Dense API first. Endpoint, authentication, quota, and final model version pending |
| Lawful, pinned, registered and bundled offline resources | No external KB by default; validated releases load from the package |
| Source/result correspondence | SHA-256 manifest and result-bundle checks reject changed outputs, stale logs and changed resources |

Development configuration requires --development (or development=True from evaluation modules). It retains legacy experiments; it cannot influence the official no-argument entry point.

The organizer's answers through Q16 (2026-11-20) do not change the runtime design: no prefix-cache dependence (caching may be disabled at evaluation, so timings can be slower); algorithms run in a CPU-only environment; no embedding service is used at runtime; any future vector retrieval must use the organizer's internal Embedding API, and a bundled local knowledge base or index must be pinned, registered and within the published size limit.

The 2026-11-20 additions confirm that vLLM supports `text`, `json_object`, and `json_schema` in principle (exact parameter and JSON Schema feature subset pending), that Embedding NPU resources do not count against participant hardware scoring but call volume is managed, and that BGE-M3 (Dense 1024, 8192 tokens, FP16, no Instruction, Dense API first) is planned. The current runtime still sends no `response_format` and uses no embedding; the BM25 textbook experiment remains CPU-only and outside the submission.

Current packaging is for testing; the team ID has not been assigned. Formal results require authorised cases and genuine completed-run logs. Mock outputs are not official results.

External acceptance still required: designated model/service version; final request, case and task limits; token/call/retry/concurrency budgets; response_format/JSON Schema parameter list and examples; Embedding endpoint, authentication, quota and final BGE-M3 version; local KB/index size limit; package size and resource registration template; clinical review; team eligibility and signed declarations. Defaults are testing settings. For formal submission, render the project description in the organiser template and verify the ten-page limit.
