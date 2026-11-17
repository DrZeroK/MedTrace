# Open Chinese clinical datasets — audit and ranking

Audit date 2026-11-16. Machine-readable version: `data_pipeline/registry.json`.

**How to read "verified".** GitHub raw files were reachable from the start; Hugging Face was opened on 2026-11-17
and the two datasets hosted there were then re-checked directly (their rows below replace earlier search-based
statements, some of which turned out wrong). Tianchi and ModelScope remain blocked. "Verified" means the licence file or data was fetched and inspected directly.
"Search only" means the statement comes from search-result summaries and must be re-checked by a person before use.
Nothing was downloaded that requires an account, a gate, or an agreement.

| Rank | Dataset | What it is | Licence | Verified? | Fit for MedTrace | Decision |
|---|---|---|---|---|---|---|
| 1 | **CMB-Clin** ([repo](https://github.com/FreedomIntelligence/CMB), [paper](https://arxiv.org/abs/2308.08833)) | 74 textbook inpatient teaching cases (history, examination, auxiliary tests) with expert-consensus answers on diagnosis + basis, differential, treatment | Apache-2.0 | Yes: LICENSE and data downloaded and inspected | Very high: same input shape, and the answers correspond to the Diagnostic Discussion and Plan | **Acquired, standardized, in use for evaluation** |
| 2 | **MedCT-clinical-notes** ([HF](https://huggingface.co/datasets/TigerResearch/MedCT-clinical-notes), [paper](https://arxiv.org/abs/2501.06465)) | 7,437 real note *fragments* (median ~67 characters) with 61,660 SNOMED-linked entity spans; plus 2K discharge notes with search labels and 91 with summaries. No patient or encounter id | Apache-2.0, not gated | Yes (2026-11-17): card, file list and NER files downloaded and profiled | Medium — lower than first assumed. Fragments cannot be rebuilt into admission cases, spans have no polarity, discharge notes leak final diagnoses. Useful as real-language stress data | **Acquired for stress testing only.** Real patient text: raw files stay local, only aggregate statistics are committed |
| 3 | **CBLUE** ([repo](https://github.com/CBLUEbenchmark/CBLUE), [paper](https://arxiv.org/abs/2106.08087)) | Team-supplied Tianchi downloads of CHIP-CDEE, CDN, CTC, STS, YIER. CHIP-CDEE: 1,971 real EMR sentences, 10,899 findings labelled 肯定/否定/不确定 | Code Apache-2.0 (verified). Data under the Tianchi terms accepted by the downloader; no licence text in the archives | Files inspected 2026-11-17 | CHIP-CDEE: high for negation testing. CDN: possible later use. CTC, STS, YIER: not relevant | **CHIP-CDEE in use as the external negation test.** Raw files local only; aggregates committed |
| 4 | **IMCS-21 / IMCS-V2** ([repo](https://github.com/lemuria-wchen/imcs21), [paper](https://academic.oup.com/bioinformatics/article/39/1/btac817/6947983)) | 4,116 online paediatric consultations with symptom present/absent/uncertain labels and two reference reports per dialogue | No licence file in the repository or the Tianchi archives; Tianchi terms apply | Team-supplied archives inspected and scored 2026-11-17 | Low. Negation rules score F1 0.42 here versus 0.98 on CHIP-CDEE, mainly because labels are dialogue-level (a symptom in a doctor's question is labelled by the patient's later answer) and the text is colloquial chat | Inspected, **deliberately not used** for tuning or evaluation: tuning record-style rules on chat would make them worse for records |
| 5 | **LungCURE** ([HF](https://huggingface.co/datasets/Fine2378/LungCURE), [paper](https://arxiv.org/abs/2604.06925)) | 1,000 real multimodal lung-cancer cases, ZH + EN, staging and treatment tasks | Card tag says MIT; the paper page shows CC BY-NC-SA 4.0 — conflicting, treat as the stricter. Gated (login and contact details) | Partly (2026-11-17): metadata only; README and data need login | Low-medium: one disease, oncology staging rather than admission notes | Not acquired. Gate must be accepted personally by the account holder; evaluation only, never tuning |
| 6 | **CliMedBench** ([repo](https://github.com/Optifine-TAT/CliMedBench), [paper](https://arxiv.org/abs/2410.03502)) | 33,735 questions in 14 clinical scenarios, largely from real EHRs | Unverified; access reportedly by researcher application | No | Medium (QA format) | Not acquired |
| 7 | **CCKS 2017–2019 EMR NER / Yidu-S4K** ([overview](https://arxiv.org/abs/2003.03875)) | Annotated real EMR passages (diseases, tests, operations, drugs, anatomy) | Evaluation agreement; third-party mirrors are not an authorised source | No | Medium for entity extraction only | Not acquired |
| 8 | **MedCD, CDrugRed, CardioEHR, OEHR** | Real Chinese EHR collections behind logins or data-use agreements | DUAs | No | Unknown until document types are confirmed | Not acquired |
| 9 | **CBLUE batch 2**: CMeEE-V2, CMeIE-V2, CMedCausal, CMF-NERD, CN-Diabetes-QC | Textbook entity and relation annotation, causal relations in online answers, few-shot NER, diabetes question classes | Tianchi terms; CMF-NERD additionally carries a confidentiality undertaking | Files inspected 2026-11-17 | Low: textbook prose, not records; no polarity, values or chronology | Inspected, **not used**. CMeIE-V2 synonym triples kept locally in case diagnosis-name matching in evaluation needs them |

## Why this order

1. **Task match beats size.** The system is scored on an initial progress note. CMB-Clin is the only open set whose
   input *and* expert answers line up with that task, and it can be used today.
2. **Licence clarity.** Only CMB (data) and CBLUE (code) have a verifiable open licence. Everything from real
   hospitals is gated, agreement-bound or unlabelled.
3. **Privacy.** Textbook cases carry no real identifiers. Real-EHR sets must not enter the repository at all, and
   whether they may be used even privately depends on rules we have not seen.

## What the datasets can and cannot be used for

- **Evaluation and prompt development:** CMB-Clin (dev split for prompts; validation and test held back).
- **Robustness testing of rules:** MedCT-clinical-notes fragments (aggregate results only).
- **Fine-tuning:** none at present. No dataset here has been cleared for training, the official pipeline must use
  the designated Qwen model unmodified, and 74 cases are too few to train on anyway.
- **Retrieval at inference:** none. No external retrieval service is used in the formal run.

## Not found

No open dataset of paired Chinese admission records → 首次病程记录 was found. A reference Case Features text
therefore does not exist in any acquired source; it has to be written by clinicians (see `ANNOTATION_GUIDELINES.md`).
