# Failure cause and fix: 2026-11-18

**English** | [简体中文](FAILURE_FIX_20261118.md)

The JSON failure on cmbclin-001 was reproduced, and after the fix the same public case recovered to a successful record. The two negation conflicts were changed to ambiguity review prompts; no raw data, frozen score or expert rating was rewritten.

## Root cause of the JSON failure

A replay with exactly the same request hash as the original failed request returned HTTP200 with `finish_reason=stop`, but the JSON reported `Expecting ',' delimiter` at line 16, column 65. A second diagnostic run reproduced the same position. The returned content used a Chinese left quotation mark and an unescaped straight double quote inside one `text` string, for example:

```text
"text": "服用“药物甲10mg"后缓解。"
```

The straight double quote terminated the JSON string early, and the following “后缓解” then became invalid syntax. This reproduction was not output-token exhaustion or a network error; the Chinese quotation marks in the input text are themselves paired, and the mixing occurred in the generated result. The four historical responses were not saved, so it cannot be asserted that each had exactly the same character error, but the same request has reproduced this fault twice.

Previously the program's second attempt simply resent the prompt and seed unchanged, without pointing out the format problem. Now, only after JSON parsing or required-section verification fails, an explicit format-correction requirement is appended: escape double quotes inside strings, output the complete object with all three parts, and preserve the original facts/cutoff/sources/fixed fields. The program does not automatically guess or patch JSON or rewrite medical facts, and remains bound by the original limit of at most 2 calls per case and the request/time budget. The first request and the v2 prompt file are unchanged.

Parse exceptions now carry the JSON error type and line/column position; the call log stores the response SHA-256, finish reason, content type and character count, and does not store the full case response by default. Raw diagnostic responses for public cases are kept only in a locally ignored directory.

## Root cause of the two high-level findings

A comma in the source text may separate both a negated list and a new assertion. The old rule stopped negation at the comma and then defaulted to positive treatment, causing:

- In cmbclin-019, “diabetes history” produced a `negation_flip` against the generated negated wording.
- In cmbclin-026, “nausea and vomiting” produced a `negation_flip` against the generated negated wording.

The development context rules now keep a comma-separated phrase that follows a negation and has no explicit predicate as `unknown`, producing a medium-level `context_scope_ambiguous` review prompt. The negation scope is not extended directly, and ambiguity is not treated as an explicit positive. Explicit negation, contrast, temporal/numeric values, subject switches, affirmative predicates and fixed expressions such as 无尿 (anuria) keep their respective meanings. Official defaults remain the legacy context.

An offline re-check of the existing generated text for the original two cases turned the targeted high-level conflicts into ambiguity reviews; this is not a new clinical-correctness score, and it does not mean that other review items have been resolved.

## Verification and budget

- 167 regression tests pass; the standard-library mode passes (2 optional-dependency tests skipped). New tests cover quote syntax, correction retry, the single-call limit, response logging without source text, and ambiguity/explicit-positive/explicit-negative boundaries after a comma.
- CHIP-CDEE uses only train for the fix regression; negation F1 stays at 0.9836, and uncertain cases misread as negated remain 2/254; dev was not used to re-tune the rules or recompute confirmation-set rankings.
- Real fix replay: request 150 reproduced the quote error; request 151 returned valid JSON after the format correction, the final official structure check succeeded, and high/medium-level rule findings were both 0. The clinical content still requires expert review.
- This round appended 4 diagnostic requests: request 148 reproduced the fault; request 149 stalled for a long time while waiting for service response headers, was interrupted, and its charged reservation was retained; requests 150 and 151 completed the fix verification. The later diagnostic run used a 45-second request timeout and a 120-second overall process limit. The shared ledger stands at 151/300 (development 43, confirmation and subsequent diagnostics 108), with no quota reset.

The original [phase-one confirmation results](PHASE1_RESULTS.md) are still reported against the frozen 147 requests. Locally, `eval/results/phase1_20261118/diagnostics/` retains the replay code identity, request/response digests, raw public responses, the training regression and the offline review records; these do not enter the official package or a public PR.
