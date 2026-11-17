# Negation rules vs CHIP-CDEE polarity labels

Aggregates only (the dataset is distributed under Tianchi terms and is not redistributed here). Rules were tuned on `train`; `dev` is held out.

| split | findings scored | precision | recall | F1 | false negated | missed negation | 不确定 findings whose sentence carries an uncertainty cue |
|---|---|---|---|---|---|---|---|
| train | 5966 | 0.989 | 0.980 | 0.984 | 30 | 54 | 223/254 |
| dev | 1460 | 0.986 | 0.978 | 0.982 | 9 | 14 | 47/65 |

Scored = finding name occurs once and has one gold polarity. Uncertainty is detected at sentence level only, so the last column is a coverage indication, not an accuracy figure.
