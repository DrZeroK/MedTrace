# Local plain-text search and structured knowledge cards across two textbooks

**English** | [简体中文](TEXTBOOK_SEARCH.md)

## 21-textbook unified search

The filtered 21-book plain-text corpus is at `data/reference_indexes/textbooks-text-21-v2/`:
7,965 pages and 10,491,035 characters. The searchable database excludes human parasitology and contains 20 books,
7,683 pages, 10,105,699 characters and 15,146 chunks. References/recommended reading, indexes, exercise/answer pages,
advertisements/back covers and repeated headers are removed; body appendices and utility tables are kept.
See [TEXTBOOK_LIBRARY_21.en.md](TEXTBOOK_LIBRARY_21.en.md) for per-book cutoffs, extraction and OCR details.

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '阑尾炎' --book 外科学第10版 --limit 5
```

Drop `--book` to search across books. Human parasitology is retained only as corpus/OCR and is not in the searchable
database, so a book-filtered query returns nothing; verify clinical or teaching content against a lawfully obtained PDF.
The rest of this file describes the two-book structured cards and term/lab/rule store.

A filtered offline plain-text corpus and search index are complete: 2 textbooks, 1515 pages, 2,176,489 characters.
The corpus is at `data/reference_indexes/textbooks-text-v2/`, consisting of `内科学第10版.txt`, `诊断学第10版.txt`
and `corpus.manifest.json`. `textbooks.sqlite` and its `.manifest.json` are a rebuildable index generated from that corpus,
and `verification.json` records this round's self-check results. The whole directory is excluded from Git and the submission package.
The unfiltered source corpus is retained in `textbooks-text-v1/` for traceability or rule changes.

On top of the plain text, `textbooks-kb-v1/` stores 4493 draft `card` entries under the knowledge-base entry schema
(2640 internal medicine, 1853 diagnostics, 2,121,289 characters); `textbooks-kb-v2/` adds 326 `term`, 118 `lab` and
7 `rule` entries checked against the original PDF text, for 4944 entries in total. See “Structured knowledge cards”
and “Term/lab/rule refinement and PDF audit” below.

Plain-text search and indexing do not depend on PDFs: both use only the Python standard library, import no PDF parser, perform no OCR,
and store neither PDF paths nor PDF page numbers. Term/lab/rule refinement has a separate one-time PDF audit step
(`scripts/pdf_text.swift` + `scripts/textbook_types.py`) that only records evidence in entry metadata; runtime retrieval never reads a PDF.

## Filtering rules

v2 is generated from the v1 plain-text corpus and can be reproduced:

- Drop the “推荐阅读” (recommended reading) page at the end of each part; from the last such page, drop every following page
  (bilingual index, colour plates and blank pages).
- Drop blank pages.
- Drop navigation lines such as “本章数字资源”, “本节数字资源”, “本章目标测试” and “本节目标测试”, plus `JOEE` font-artifact lines.
- Drop leading page numbers; for repeated part/chapter/section running headers, keep only the first occurrence.

Results:

- Internal medicine: 23 of 951 pages removed (8 recommended-reading pages, 10 index pages, 4 colour-plate pages, 1 blank), 928 kept.
- Diagnostics: 16 of 603 pages removed (1 recommended-reading page, 11 index pages, 4 blank), 587 kept.
- Removed lines in internal medicine: 744 navigation/artifact, 873 leading page numbers, 738 repeated headers;
  diagnostics: 159, 564 and 503 respectively.
- Removed pages leave gaps in the numbering; for example internal medicine jumps from 167 to 169 after page 168 is dropped.
  `页 N` remains the v1 text page ordinal rather than being renumbered, so it can be matched against the source corpus.

## Corpus format

Each book is one UTF-8 text file with a title and note, followed by page records:

```text
# 书名：内科学第10版
# 说明：纯文本正文库；页序号为文本内顺序，书页为原书页码标签，推算表示页码由起始偏移推断、未经页眉核对。
--- 页 1（书页 1，推算） ---
第一篇
绪论
--- 页 2（书页 2，页眉） ---
第一篇　绪论
一、　内科学概况
...
```

`页 N` is the sequential page number in the v1 corpus and may have gaps after filtering; `书页 M` is the printed page label
and may repeat when appendices restart numbering. `页眉` means the label came from the top of the page; `推算` means it was
inferred from a verified starting offset and must be confirmed against the body text.

## Queries

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-v2/textbooks.sqlite --query '心力衰竭' --limit 5
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-v2/textbooks.sqlite --query '低血糖' --book 内科学第10版 --full-page
```

Multiple keywords are matched with AND, and Chinese bigrams and complete English words are ranked with BM25; a single Chinese
character uses literal matching. At most one chunk is returned per page, book-title filtering is supported, and `--full-page`
returns all body text from that text page.

Output includes the book title, text page number, printed page number, page-number evidence, ranking score and source text;
it does not include a PDF path. Because the body preserves original line breaks, words split across lines may be missed;
split them into shorter keywords. Search performs no medical synonym inference and does not automatically convert textbook
content into clinical rules.

## Structured knowledge cards

`data/reference_indexes/textbooks-kb-v1/` stores the body text under the `medtrace/knowledge.py` entry schema:

- `entries.jsonl`: 4493 `card` entries, 2,121,289 characters (2640 internal medicine, 1853 diagnostics).
  Each card has `id`, `type`, `title`, `text`, `source`, `version`, `locator`, `license`, `status`, `scope`, `aliases`,
  plus `permission_review`, `clinical_review`, `candidate_source_ids`, `source_id`, `source_note`,
  `structure`, `page_start`/`page_end`, `printed_page_start`/`printed_page_end` and `page_basis`.
- `outline.json`: card membership under `part → chapter → section → topic → subtopic → label`.
- `manifest.json`: source hashes, card counts, `validate_entry` result and permission status.
- `cards.sqlite` / `cards.manifest.json`: a local draft index generated from the cards with `release=false`.
- `verification.json`: structural validation and retrieval probes.

`source` is the official catalogue metadata URL in `knowledge/sources.json`; the body comes from the user-provided
10th-edition electronic copy, and `source_note` records that permission boundary. The commands below target a first build
or new paths; existing outputs are never overwritten, so use a new path to rebuild.

Hierarchy parsing recognises “第X篇/章/节”, “【...】”, “一、...” and “（一）...”; an inline “【...】” label is split into
its own heading. Cards longer than 1800 characters are split at line boundaries with a `（1/N）` suffix.
`scope` is provisionally `adult` for internal medicine and `general` for diagnostics; every entry is
`status=draft`, `license=pending`, `permission_review=not_granted` and `clinical_review=not_signed`, so none is releasable.
All cards use type `card`: lab units/specimens/methods and numeric rules still need manual review and are not auto-converted
to `lab` or `rule`.

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py structure --corpus /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-v2 --out /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py build --entries /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/entries.jsonl --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/cards.sqlite
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/cards.sqlite --query '低血糖' --limit 5
```

`structure` uses the PMPH-IM10/PMPH-DX10 metadata in `knowledge/sources.json`; a new textbook needs a source mapping first.
`cards.sqlite` is only a draft research index, not an approved knowledge-base release; `scripts/build_knowledge.py` still
refuses all drafts. Because the textbook body has no redistribution permission, the structured cards stay under
`data/reference_indexes/` (Git-ignored) and can move into the formal knowledge-base directory under the same schema only
after review and permission clearance.

## Term/lab/rule refinement and PDF audit

`textbooks-kb-v2/` adds typed entries on top of the 4493 v1 cards, after checking each one against the original PDF text:

- `entries.jsonl`: 4944 entries = 4493 `card` + 326 `term` + 118 `lab` + 7 `rule`.
- `typed.jsonl`: the 451 `term`/`lab`/`rule` entries; `typed_outline.json` records their hierarchy.
- `typed_audit.json`: candidate/matched/skipped lists, PDF names and SHA-256, page counts and audit evidence.
- `index.sqlite` / `.manifest.json`: combined index with `release=false`.
- `verification.json`: `validate_entry`, index integrity, type counts and retrieval probes.

PDF audit method: `scripts/pdf_text.swift` extracts page text with macOS PDFKit; internal-medicine PDF page = printed page + 31,
diagnostics = printed page + 23. Each typed entry records `pdf_pages`, the matched title/unit/threshold evidence and the extraction
method in `pdf_audit`; `locator` still uses printed/text pages and stores no PDF path.

Refinement rules:

- `term`: chapter/section headings, excluding structural words such as “总论/病因/临床表现/治疗/检查/测定/穿刺” and procedure/lab
  titles; the heading is checked against the PDF page; aliases come only from English parentheticals in the source card and are
  checked on the same page. 326 entries.
- `lab`: the most specific test name under a diagnostics `【参考区间】` card, excluding panels, multi-test groups and ambiguous units;
  units are extracted from the text and checked against the PDF page; `reference_interval` is deliberately null because population,
  specimen and method are not signed off. 118 entries.
- `rule`: only auditable strict `>`/`<` thresholds, 7 entries: serum potassium >5.3, FEV1/FVC <70%, absolute neutrophil count
  <1.5 / <0.5, uric acid >420 (male) / >360 (female), and glucose <2.8. `requires` carries only conditions stated in the source;
  missing conditions are marked “未注明”, so insufficient facts return `insufficient` instead of firing. These are not clinical
  release rules and must not be used for care.

Audit counts: term 326 of 327 candidates matched; lab 118 of 150 matched (24 title/unit misses in the PDF window plus 8 manual
exclusions for panels/ambiguous units); rule 7 of 7 matched. Misses and exclusion reasons remain in `typed_audit.json`.
Every typed entry is still `status=draft`, `license=pending`, `permission_review=not_granted`, `clinical_review=not_signed`;
none is approved. PDF matching proves source location and text only, not clinical validity.
The commands below are for a first build; both `textbook_types.py` and `textbook_kb.py build` refuse to overwrite existing
outputs, so use new paths to rebuild.

```bash
swift /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_text.swift "$HOME/Downloads/02《内科学（第10版）》.pdf" /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/pdf_text_audit/im10.json
swift /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_text.swift "$HOME/Downloads/09《诊断学（第10版）》.pdf" /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/pdf_text_audit/dx10.json
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_types.py --cards /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/entries.jsonl --pdf-audit /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/pdf_text_audit --out /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2 --pdf-manifest /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.manifest.json
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py build --entries /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2/entries.jsonl --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2/index.sqlite
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2/index.sqlite --query '血钾测定' --limit 5
```

`textbook_types.py` only handles the two textbooks mapped in `knowledge/sources.json`; a new textbook needs both a source mapping
and PDF audit text. `textbooks-kb-v2/` remains local research data: it is not in the submission package and is not merged into
`knowledge/entries.jsonl` until review and permission clearance.

## Rebuilding and migration

The first migration and filtering are complete. To rebuild, use new paths; existing corpus and index files are not overwritten:

```bash
# One-time migration: reads only text already extracted into the old index, never PDFs
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py export --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.sqlite --corpus /absolute/new/raw-corpus
# Filter: drop references, index, plates, blank pages, running headers and page numbers
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py filter --corpus /absolute/raw-corpus --out /absolute/filtered-corpus
# Build an index from the filtered plain-text corpus
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py build --db /absolute/new/index.sqlite --corpus /absolute/filtered-corpus
```

`build` verifies the SHA-256 of every text file listed in `corpus.manifest.json`, then creates the `pages`, `chunks` and FTS5 index.
`filter` records removed pages and per-category line counts in the new corpus manifest.

## Coverage and verification

- Internal medicine: 928 of the v1 951 pages kept, ending at page 935; blank page 951 was removed.
- Diagnostics: 587 of the v1 603 pages kept, ending at page 588; blank pages 82 and 601–603 were removed.
- Self-checks cover heart failure, hypoglycaemia, blood glucose, BNP, single-character queries, no-match queries, and noise queries
  such as “推荐阅读”, “中英文名词对照索引” and “本章数字资源”; noise queries return no results and the SQLite integrity check passes.
- All 4493 structured cards pass `validate_entry` with unique IDs; `cards.sqlite` passes the SQLite integrity check and its
  manifest is marked `release=false`.
- The typed store has 4944 entries (4493 card + 326 term + 118 lab + 7 rule), all passing `validate_entry`, with 0 approved;
  `index.sqlite` passes the SQLite integrity check and is marked `release=false`.
- PDF audit counts: term 326/327 matched; lab 118/150 matched (the rest were PDF-window misses or manual exclusions of panels/ambiguous
  units); rule 7/7 matched. Evidence and skip reasons are in `typed_audit.json`.
- Typed retrieval probes: 低血糖症 returns the term; 血钾测定 returns the lab; 高钾血症 5.3 returns the rule; 白细胞计数 参考区间
  returns the “白细胞计数” lab entry; 肺脓肿 治疗 returns the card; “推荐阅读” and “本章数字资源” return nothing.
- Queries on this machine took about 0.2–11 ms for the page index; these are a few query probes, not a comprehensive benchmark.
  The card/typed index has no performance benchmark yet.
- Measured lookups include heart failure printed pages 176/180, hypoglycaemia 748 and blood glucose testing 355, returned directly
  as text page and printed page numbers.
- Filtering is heuristic; when clinical checking needs references, the index or colour plates, consult the retained v1 corpus or a
  lawfully obtained copy of the textbook.
- Structured cards and typed entries remain draft: clinical content, applicability, lab units and cited clauses have not been signed
  off and cannot support diagnosis or treatment; the 7 rules return `insufficient` when conditions are missing and are not clinical
  release rules.

This is a local research corpus of user-provided textbooks; it is not a submission resource with permission for redistribution,
and it does not replace clinical sign-off of knowledge cards.
