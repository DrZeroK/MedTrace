# Local plain-text retrieval library for 21 textbooks

**English** | [简体中文](TEXTBOOK_LIBRARY_21.md)

Status: a filtered 21-textbook plain-text corpus and an SQLite FTS5 database without human parasitology are available as local research data.

- Corpus: `data/reference_indexes/textbooks-text-21-v2/`
- Index: `textbooks.sqlite` and `textbooks.manifest.json`
- Corpus size: 21 books, 7,965 pages, 10,491,035 characters
- Searchable size: 20 books, 7,683 pages, 10,105,699 characters, 15,146 chunks; index about 151 MiB
- Human parasitology keeps its corpus and OCR extraction but is excluded from the database; a book-filtered search returns nothing
- Self-check: `verification.json`; source pages and cutoffs: `corpus.manifest.json`
- The unfiltered 21-book corpus remains in `textbooks-text-21-v1/`

The two-book structured cards and term/lab/rule store remain in `textbooks-kb-v1/` and `textbooks-kb-v2/`;
see [TEXTBOOK_SEARCH.en.md](TEXTBOOK_SEARCH.en.md). This round only extends the pure-text library; the 19 new books
have not been typed into term/lab/rule entries.

## Textbook scope

Internal medicine, diagnostics, medical biology, organic chemistry, pathophysiology, dermatology, surgery, pathology,
physiology, pediatrics, medical genetics, human parasitology, doctor-patient communication, biochemistry and molecular
biology, histology and embryology, pharmacology, medical mathematics, basic chemistry, medical psychology,
anesthesiology and obstetrics and gynecology.

The first two reuse the previously filtered corpus; the other 19 start at a verified body page. Body start, offset and
PDF SHA-256 for each book are recorded in `source_pages.json` (local metadata, not part of retrieval text). Human
parasitology is kept only as corpus/OCR because its OCR quality and page labels are unreliable; the other 20 books are searchable.

## Extraction and OCR

- The 19 PDFs are extracted page by page with `scripts/pdf_text.swift` (macOS PDFKit `page.string`); it only reads a local
  PDF and writes page-level JSON.
- Human parasitology has no PDF text layer, so the existing 323-page Apple Vision OCR cache is used. Its OCR corpus is kept,
  but the book is excluded from the searchable database. Other books use native text layers.
- Page JSON is converted to page-marked plain text by `scripts/pdf_json_corpus.py`; `--copy-corpus` merges the two existing books.
- The retrieval corpus and index store no PDF paths; page JSON, OCR cache and PDFs remain in local ignored directories.

## Filtering rules

`textbooks-text-21-v2` is generated from v1 with `textbook_search.py filter`:

- Drop reference/recommended-reading pages, index pages, blank pages, advertisement/back-cover pages and exercise/answer pages.
- Apply the per-book back-matter cutoff in `data/reference_indexes/textbook_filter_21.json` to remove index, back cover and answer sections.
- Keep body appendices and utility tables, including parasitology/pediatrics appendices, mathematics formula tables,
  chemistry constant tables and the organic-chemistry identification table.
- Drop navigation, “本章目标测试/思维导图”, publisher/back-cover text, author signatures, `JOEE` artifacts, leading page numbers
  and repeated running headers.
- Removed pages leave gaps in numbering; `页 N` is the v1 text page ordinal and `书页 M` is the printed page label.

The 8,247 v1 pages become 7,965 kept pages, removing 282. Typical removals: medical-mathematics answer pages 246–261,
basic-chemistry partial answers 294–307, pathophysiology chapter-test pages, a mid-book histology advertisement, and the
index/back covers at the end of each book. Per-category counts are in `removed_categories` in `corpus.manifest.json`.

## Queries

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '细胞周期' --book 医学生物学第10版 --limit 5
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '阑尾炎' --book 外科学第10版 --limit 5
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '阿托品' --book 药理学第10版 --limit 5
```

Multiple keywords are AND-matched, with Chinese bigrams and whole English words ranked by BM25; a single Chinese character
uses literal matching. Output includes book, text page, printed page, page-number evidence, score and text. Human parasitology
may have `printed_page` null because OCR lacks page labels.

## Rebuilding and adding textbooks

```bash
# 1. Extract a PDF into page-level JSON (once per book)
swift /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_text.swift /absolute/book.pdf /absolute/book.json
# 2. Convert page JSON to a raw plain-text corpus; optionally merge an existing corpus
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_json_corpus.py --metadata /absolute/metadata.json --out /absolute/new/raw-corpus --copy-corpus /absolute/existing-corpus
# 3. Filter with per-book cutoffs
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py filter --corpus /absolute/raw-corpus --out /absolute/filtered-corpus --cutoffs /absolute/cutoffs.json
# 4. Build the FTS5 index
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py build --db /absolute/new/index.sqlite --corpus /absolute/filtered-corpus --exclude-book 人体寄生虫学第10版
```

For a new textbook, first determine body start/offset and inspect the trailing references, index, appendices, answers and back
cover, then add a cutoff. Output directories and database paths must be new absolute paths; existing corpora and indexes are
never overwritten.

## Coverage and verification

- Retrieval probes succeed for all 20 searchable books across medicine, chemistry, mathematics, psychology, communication and genetics.
- Human parasitology is not in the database; a book-filtered query returns 0 results, while its corpus and OCR extraction remain locally.
- Queries for “参考文献”, “中英文名词对照索引”, “推荐阅读” and “本章目标测试” return no results.
- The SQLite integrity check passes; the index contains no `/Users/`, `file://` or `.pdf` path traces.
- This is a local research corpus of user-provided textbooks, not a submission resource with redistribution permission, and it
  does not replace clinical or teaching review.
