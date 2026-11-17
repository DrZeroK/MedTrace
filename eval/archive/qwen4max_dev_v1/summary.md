# External evaluation `qwen4max_dev_v1`

Dataset `cmb_clin` split `dev` (26 cases) | model `qwen4-max` | prompts `v1:af1abc016256`

| variant | cases | completed_ok_% | schema_valid_% | dx_hit_% | ddx_recall_% | measurement_cov_% | refs_valid_% | notes_with_verifier_high | mean_review_items | mean_note_chars | mean_calls | mean_latency_s | max_latency_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 | 26 | 100.0 | 100.0 | 39.1 (n=23) | 18.8 | 100.0 | 100.0 | 11 | 12.6 | 2576 | 1 | 90.5 | 230.3 |
| A1 | 26 | 46.2 | 100.0 | 21.7 (n=23) | 6.2 | 100.0 | 100.0 | 2 | 4.3 | 1838 | 1 | 292.13 | 369.97 |
| A2 | 26 | 34.6 | 100.0 | 13.0 (n=23) | 0.0 | 100.0 | 100.0 | 2 | 3.8 | 1535 | 1.08 | 294.89 | 370.09 |
