# Deterministic-layer stress test on real note fragments (MedCT-clinical-notes)

Aggregate statistics only; no note text is reproduced here. Source: TigerResearch/MedCT-clinical-notes (Apache-2.0), real hospital note fragments.

| Item | Value |
|---|---|
| Fragments in file | 7437 |
| Unique fragments of at least 15 characters | 5554 |
| Sentences produced by the splitter | 23380 |
| Unit-bearing measurements recognised | 6035 |
| Sentences with a negation cue | 4965 |
| Sentences marked pending / not done | 338 |
| Sentences the record itself marks uncertain | 1204 |
| **Verifier false alarms on verbatim text (high or medium)** | **0** (none) |
| Identifier patterns redacted before processing | {'possible_name': 1, 'named_field': 1} |

What this does and does not show: the verifier does not raise alarms on faithful real-language text. It says nothing about whether negation scope and polarity are *correct* (the dataset's entity spans carry no polarity labels), and nothing about model output.
