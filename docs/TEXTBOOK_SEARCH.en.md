# Local body-text search across two textbooks

**English** | [简体中文](TEXTBOOK_SEARCH.md)

An offline full-text index is complete: 1554 PDF pages within the body/appendix scope, 3379 overlapping chunks.
The database is about 32.3 MiB, at `data/reference_indexes/textbooks-v1/textbooks.sqlite`, and is excluded from Git and the submission package.
Both original PDFs remain in the user-provided Downloads path; they have not been moved or modified.

## Queries

Search uses only the Python standard library; it needs no model, network or extra installation. Multiple keywords are matched with AND, and Chinese bigrams and complete English words are ranked with BM25;
a single Chinese character uses literal matching. At most one chunk is returned per page. Book-title filtering is supported, and `--full-page` returns all extractable text from that PDF page.

```bash
/opt/homebrew/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.sqlite --query '心力衰竭' --limit 5
/opt/homebrew/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.sqlite --query '低血糖' --book 内科学第10版 --full-page
```

Output includes the book title, PDF page number, printed page number, page-number evidence, absolute path of the original file, ranking score and source text.
`printed_page_basis=header` means the page number was taken from the start of the page; `offset_inferred` means it was inferred from a verified starting offset and must be confirmed by checking the page.
The PDF page number always points to the actual file position. Because body-text parsing preserves line breaks, words split across lines may be missed; split them into shorter keywords.
Search performs no medical synonym inference and does not automatically convert textbook content into clinical rules.

## Coverage and verification

- Internal medicine: from PDF page 32, covering the introduction, body and subsequent appendix/index; the first 31 pages are not indexed.
- Diagnostics: from PDF page 24; the first 23 pages are not indexed.
- Pages with no extractable text are listed in the manifest: internal medicine PDF 982; diagnostics PDF 105, 624–626.
  Such pages and text inside figures were not OCRed, so figures and tables should be checked against the original PDF; PDF text parsing does not guarantee correct table row and column relationships.
- Self-checks cover heart failure, hypoglycaemia, blood glucose, BNP, single-character queries and no-match queries, and pass the SQLite integrity check.
  The first heart-failure query on this machine took about 365 ms, and subsequent examples about 2–97 ms; these are a few query probes, not a comprehensive performance benchmark.
- Measured lookups include heart failure printed page 176, hypoglycaemia 748 and blood glucose testing 355, corresponding to PDF 207, 779 and 378.

The `.manifest.json` beside the database stores the original PDF paths, SHA-256, page counts and ranges; `.verification.json` stores this round's self-check results.
Rebuilding requires a Python with pypdf and a new database path; the existing index is not overwritten:

```bash
/Users/zerok/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py build --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v2/textbooks.sqlite --source 内科学第10版 '/Users/zerok/Downloads/02《内科学（第10版）》.pdf' 32 31 --source 诊断学第10版 '/Users/zerok/Downloads/09《诊断学（第10版）》.pdf' 24 23
```

This is a local research index of user-provided textbooks; it is not a submission resource with permission for redistribution, and it does not replace clinical sign-off of knowledge cards.
