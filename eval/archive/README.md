# Archived development runs (real model)

Copies of the evaluation runs reported in `docs/REPORT.md` §2.6, kept because `eval/results/` is git-ignored.

- **Model and service:** `qwen4-max` (generation) and `qwen-plus` (diagnosis judge) on the project owner's own
  Alibaba Cloud Model Studio workspace. This is a commercial hosted API, **not** the competition's self-hosted vLLM
  Qwen service. Results therefore do not transfer automatically to the designated competition model.
- **Data sent:** only CMB-Clin textbook teaching cases (public, Apache-2.0). No competition practice or evaluation
  case was sent to any external service, and none may be (see `docs/COMPETITION_QA.md`, Q8).
- **Contents per run:** `config.json` (endpoint redacted, no key), `per_case.csv`, `summary.md`, generated notes
  (`outputs_*.json`), verifier findings as produced at run time (`findings_*.json`), judge verdicts (`judge_dx.json`).
- The verifier rules changed after these runs; replay current rules on the saved notes with
  `python -m eval.reverify <run dir>` after copying a run back to `eval/results/` together with its `cases_used.json`
  (regenerate that file with `eval.run_external --mock`, or see the script).

| Run | Split | Prompts | Variants |
|---|---|---|---|
| `qwen4max_dev_v1` | dev (26) | v1 | A0 valid; A1/A2 void (120 s timeout) |
| `qwen4max_dev_v1_rerun` | dev (26) | v1 | A1, A2 |
| `qwen4max_dev_v2` | dev (26) | v2 | A2 |
| `qwen4max_val_v1_A0` | validation (17) | v1 | A0 |
| `qwen4max_val_v2_A2` | validation (17) | v2 | A2 |
