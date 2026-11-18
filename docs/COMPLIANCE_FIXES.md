# Competition compliance fixes — 2026-11-18

**English** | [简体中文](COMPLIANCE_FIXES.zh-CN.md)

The earlier audit's engineering issues are addressed below. Packaging is for testing;
the team ID has not been assigned. This record does not claim designated-service or clinical acceptance.

| Audit issue | Change | Regression evidence |
|---|---|---|
| Invalid input silently accepted | Strict official per-case validation; string/unique case IDs checked before calls | Invalid-material isolation and identifier tests |
| Missing medical sections labelled successful | Complete-section parsing, bounded regeneration, final record/reference validation | Missing-section fail/recover and validator tests |
| Credentials/proxies inherited | Official header omits keys; requests trust_env disabled; urllib proxies disabled; redirects refused | Poisoned-env, transport and header tests |
| Configuration and paths drift | Only source-root two-key .env; fixed source-root input/output and code parameters | No-argument ZIP entry point launched from unrelated cwd |
| Early output publication | Official output published only after batch completion | Model-time nonexistence and interrupted-run preservation tests |
| Incomplete run records | Current-run JSON export, run IDs, case/request timestamps, counters and I/O hashes | Real loopback calls and result-bundle consistency checks |
| Seed omitted | Default seed=42, preserved in request/log configuration | Captured request test |
| Stale submitted documentation | English/Chinese README, requirements, knowledge deployment, project description and declarations aligned | Packaged docs, links and two-key template tests |
| Test artifacts incomplete | Algorithm manifest and validated results ZIP; originals retained; existing archives refused | Manifest hashes, changed-output/stale-log rejection tests |
| Default branch missing fixes | Default-branch change prepared directly from master, retaining all existing master files | Separate master-based worktree runs the same full suite |

Python 3.11.16 local verification: 148 tests pass with the pinned dependency set;
the same 148 checks run without site packages (one optional jsonschema parity check is skipped).
Both paths exercise loopback HTTP and synthetic engineering fixtures; no external model is called.
Dependency archives and test artifacts are retained, and no real .env is read by the regression fixtures.

Additional guards preserve distinct source identifiers, load reviewed bundled knowledge without
extra official configuration keys, and verify output/log/algorithm correspondence before result packaging.

External acceptance remains separate: actual designated model and interface limits, clinical review,
resource permission and registration, and signed formal competition materials. For formal submission,
use the assigned team ID and verify the formatted project description is at most ten pages.
