# Open Chinese clinical datasets — audit and ranking

Audit date 2026-11-16. Machine-readable version: `data_pipeline/registry.json`.

**How to read "verified".** From the build environment only GitHub raw files were reachable; Hugging Face, Tianchi
and ModelScope were blocked. "Verified" means the licence file or data was fetched and inspected directly.
"Search only" means the statement comes from search-result summaries and must be re-checked by a person before use.
Nothing was downloaded that requires an account, a gate, or an agreement.

| Rank | Dataset | What it is | Licence | Verified? | Fit for MedTrace | Decision |
|---|---|---|---|---|---|---|
| 1 | **CMB-Clin** ([repo](https://github.com/FreedomIntelligence/CMB), [paper](https://arxiv.org/abs/2308.08833)) | 74 textbook inpatient teaching cases (history, examination, auxiliary tests) with expert-consensus answers on diagnosis + basis, differential, treatment | Apache-2.0 | Yes: LICENSE and data downloaded and inspected | Very high: same input shape, and the answers correspond to the Diagnostic Discussion and Plan | **Acquired, standardized, in use for evaluation** |
| 2 | **MedCT-clinical-notes** ([HF](https://huggingface.co/datasets/TigerResearch/MedCT-clinical-notes), [paper](https://arxiv.org/abs/2501.06465)) | Paper reports ~3.1 M notes from ~597 k patients of a Zhejiang tertiary hospital | Not shown in search results. The sibling terminology dataset is Apache-2.0; that does not carry over | No (host blocked) | Potentially very high — the only large source of real Chinese inpatient notes found | Blocked: read the dataset card, licence and de-identification statement first; real patient data also needs the competition's data rules checked |
| 3 | **CBLUE** ([repo](https://github.com/CBLUEbenchmark/CBLUE), [paper](https://arxiv.org/abs/2106.08087)) | CMeEE entities, CMeIE relations, CHIP-CDEE clinical-finding events with polarity, CHIP-CDN diagnosis normalisation | Code Apache-2.0 (verified). Data only via Tianchi under its own terms (not verified) | Partly | Medium-high for fact extraction and negation tests; low for note generation | Team member downloads with a Tianchi account after reading the terms; adapter to be written then |
| 4 | **IMCS-21** ([repo](https://github.com/lemuria-wchen/imcs21), [paper](https://academic.oup.com/bioinformatics/article/39/1/btac817/6947983)) | 4,116 online paediatric consultations with entity, symptom present/absent/uncertain and report annotations | **No licence file** (verified: 404). No licence = no permission to redistribute or train | Yes (absence verified) | Medium: good external test of negation/uncertainty; domain is outpatient paediatric chat | Not acquired. Ask the authors for terms; private evaluation at most |
| 5 | **LungCURE** ([HF](https://huggingface.co/datasets/Fine2378/LungCURE), [paper](https://arxiv.org/abs/2604.06925)) | 1,000 real multimodal lung-cancer cases, ZH + EN, staging and treatment tasks | Reported CC BY-NC-SA 4.0; gated; described as test-only | No (search only) | Low-medium: one disease, oncology staging rather than admission notes | Not acquired. Gate must be accepted personally by the account holder; evaluation only, never tuning |
| 6 | **CliMedBench** ([repo](https://github.com/Optifine-TAT/CliMedBench), [paper](https://arxiv.org/abs/2410.03502)) | 33,735 questions in 14 clinical scenarios, largely from real EHRs | Unverified; access reportedly by researcher application | No | Medium (QA format) | Not acquired |
| 7 | **CCKS 2017–2019 EMR NER / Yidu-S4K** ([overview](https://arxiv.org/abs/2003.03875)) | Annotated real EMR passages (diseases, tests, operations, drugs, anatomy) | Evaluation agreement; third-party mirrors are not an authorised source | No | Medium for entity extraction only | Not acquired |
| 8 | **MedCD, CDrugRed, CardioEHR, OEHR** | Real Chinese EHR collections behind logins or data-use agreements | DUAs | No | Unknown until document types are confirmed | Not acquired |

## Why this order

1. **Task match beats size.** The system is scored on an initial progress note. CMB-Clin is the only open set whose
   input *and* expert answers line up with that task, and it can be used today.
2. **Licence clarity.** Only CMB (data) and CBLUE (code) have a verifiable open licence. Everything from real
   hospitals is gated, agreement-bound or unlabelled.
3. **Privacy.** Textbook cases carry no real identifiers. Real-EHR sets must not enter the repository at all, and
   whether they may be used even privately depends on rules we have not seen.

## What the datasets can and cannot be used for

- **Evaluation and prompt development:** CMB-Clin (dev split for prompts; validation and test held back).
- **Fine-tuning:** none at present. No dataset here has been cleared for training, the official pipeline must use
  the designated Qwen model unmodified, and 74 cases are too few to train on anyway.
- **Retrieval at inference:** none. No external retrieval service is used in the formal run.

## Not found

No open dataset of paired Chinese admission records → 首次病程记录 was found. A reference Case Features text
therefore does not exist in any acquired source; it has to be written by clinicians (see `ANNOTATION_GUIDELINES.md`).
