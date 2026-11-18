"""Plain-text textbook corpus and BM25 search. Standard library only; build and search never read PDFs."""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from medtrace.knowledge import search_tokens

PAGE_MARKER = re.compile(r'^--- 页 (\d+)(?:（书页 (\d+)，(页眉|推算)）)? ---$')
TITLE_PREFIX = '# 书名：'
BASIS_IN = {'页眉': 'header', '推算': 'offset_inferred'}
BASIS_OUT = {v: k for k, v in BASIS_IN.items()}
NAV_LINES = {'本章数字资源', '本节数字资源', '本章目标测试', '本节目标测试'}
HEADING_RE = re.compile(r'^第[一二三四五六七八九十百]+[篇章节]')


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean_text(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


def book_filename(book):
    if not book or any(c in book for c in '/\\') or book in ('.', '..'):
        raise ValueError(f'unsafe book name: {book!r}')
    return book + '.txt'


def render_book(book, pages):
    """pages: iterable of (page, printed_page, basis, text). Pure text with parseable page markers."""
    lines = [f'{TITLE_PREFIX}{book}',
             '# 说明：纯文本正文库；页序号为文本内顺序，书页为原书页码标签，推算表示页码由起始偏移推断、未经页眉核对。']
    last = 0
    for page, printed, basis, text in pages:
        if page <= last:
            raise ValueError(f'{book}: page numbers must increase: {page}')
        last = page
        marker = f'--- 页 {page}'
        if printed is not None:
            marker += f'（书页 {printed}，{BASIS_OUT[basis]}）'
        marker += ' ---'
        body = clean_text(text).strip('\n')
        if any(PAGE_MARKER.match(line) for line in body.splitlines()):
            raise ValueError(f'{book} page {page}: body collides with page marker')
        lines.append(marker)
        if body:
            lines.append(body)
    return '\n'.join(lines) + '\n'


def parse_book(path):
    book = None
    pages = []
    current = None
    for line in Path(path).read_text('utf-8').splitlines():
        if line.startswith(TITLE_PREFIX) and current is None:
            if book is not None:
                raise ValueError(f'{path}: duplicate book header')
            book = line[len(TITLE_PREFIX):].strip()
            continue
        match = PAGE_MARKER.match(line)
        if match:
            if current:
                pages.append(tuple(current))
            page = int(match.group(1))
            printed = int(match.group(2)) if match.group(2) else None
            basis = BASIS_IN[match.group(3)] if match.group(3) else None
            if printed is not None and basis is None:
                raise ValueError(f'{path}: printed page requires a basis')
            current = [page, printed, basis, []]
            continue
        if current is not None:
            current[3].append(line)
    if current:
        pages.append(tuple(current))
    if not book:
        raise ValueError(f'{path}: missing "{TITLE_PREFIX}" header')
    if not pages:
        raise ValueError(f'{path}: no page markers')
    seen = set()
    for page, _, _, body in pages:
        if page in seen:
            raise ValueError(f'{path}: duplicate page {page}')
        seen.add(page)
        if page < 1:
            raise ValueError(f'{path}: page must be positive')
    return book, [(page, printed, basis, '\n'.join(body).strip('\n')) for page, printed, basis, body in pages]


def export_legacy(db_path, corpus_dir):
    """One-time migration: write the text already stored in the previous index; never reads PDFs."""
    db_path = Path(db_path)
    if not db_path.is_absolute():
        raise ValueError('database path must be absolute')
    dest = Path(corpus_dir)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('use a new absolute corpus directory')
    db = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    try:
        books = [r[0] for r in db.execute('SELECT DISTINCT book FROM pages ORDER BY book')]
        if not books:
            raise ValueError('no pages to export')
        dest.mkdir(parents=True)
        entries = []
        for book in books:
            rows = db.execute('SELECT printed_page,label_basis,text FROM pages WHERE book=? ORDER BY pdf_page',
                              (book,)).fetchall()
            pages = []
            for page, (printed, basis, text) in enumerate(rows, 1):
                if basis not in BASIS_IN.values():
                    raise ValueError(f'{book}: unknown label basis {basis!r}')
                pages.append((page, printed, basis, text))
            target = dest / book_filename(book)
            target.write_text(render_book(book, pages), encoding='utf-8')
            _, written = parse_book(target)
            entries.append({"book": book, "text_file": target.name, "sha256": digest_file(target),
                            "bytes": target.stat().st_size, "chars": sum(len(p[3]) for p in written),
                            "pages": len(written), "empty_pages": [p[0] for p in written if not p[3].strip()],
                            "label_basis": {k: sum(p[2] == k for p in written) for k in BASIS_IN.values()}})
    finally:
        db.close()
    manifest = {"schema": 1, "kind": "textbook-text-corpus", "state": "ready", "books": entries,
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                "provenance": "text exported from the previous local body-text index; no PDF path or page number is retained",
                "redistribution": "not established; local research index"}
    (dest / 'corpus.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({"corpus": str(dest), "books": [b["book"] for b in entries],
                      "pages": sum(b["pages"] for b in entries), "chars": sum(b["chars"] for b in entries)},
                     ensure_ascii=False))


def load_corpus(corpus_dir):
    corpus = Path(corpus_dir)
    manifest_path = corpus / 'corpus.manifest.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    if manifest.get('schema') != 1 or manifest.get('kind') != 'textbook-text-corpus':
        raise ValueError('unsupported corpus manifest')
    books = []
    seen_books = set()
    for item in manifest['books']:
        path = corpus / item['text_file']
        if digest_file(path) != item['sha256']:
            raise ValueError(f'text hash mismatch: {path}')
        book, pages = parse_book(path)
        if book != item['book']:
            raise ValueError(f'{path}: book name mismatch')
        if book in seen_books:
            raise ValueError(f'duplicate book: {book}')
        seen_books.add(book)
        books.append((book, pages, item))
    return books, manifest_path


def connect(path):
    if not Path(path).is_absolute():
        raise ValueError('database path must be absolute')
    return sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)


def page_heads(body, count=5):
    return [line.strip() for line in body.splitlines() if line.strip()][:count]


def norm_line(line):
    return re.sub(r'\s+', '', line)


def filter_corpus(corpus_dir, out_dir):
    """Drop non-body pages and navigation noise; keep original page ordinals as gaps."""
    books, manifest_path = load_corpus(corpus_dir)
    dest = Path(out_dir)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('use a new absolute corpus directory')
    dest.mkdir(parents=True)
    entries = []
    for book, pages, _ in books:
        plain_title = re.sub(r'第\d+版$', '', book)
        ref_pages = {page for page, _, _, text in pages if '推荐阅读' in page_heads(text)}
        index_pages = {page for page, _, _, text in pages if '中英文名词对照索引' in page_heads(text)}
        cutoff = max(ref_pages) if ref_pages else (min(index_pages) if index_pages else None)
        removed = set()
        for page, _, _, text in pages:
            if not text.strip():
                removed.add(page)
            elif cutoff is not None and page >= cutoff:
                removed.add(page)
            elif page in ref_pages:
                removed.add(page)
        cleaned, removed_lines = {}, Counter()
        for page, _, _, text in pages:
            if page in removed:
                continue
            lines = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line in NAV_LINES or 'JOEE' in line:
                    removed_lines['navigation_or_artifact'] += 1
                    continue
                lines.append(line)
            cleaned[page] = lines
        for lines in cleaned.values():
            while lines and re.fullmatch(r'\d{1,4}', lines[0]):
                lines.pop(0)
                removed_lines['page_number'] += 1
        first_counts = Counter(norm_line(lines[0]) for lines in cleaned.values() if lines)
        headers = {key for key, count in first_counts.items()
                   if count >= 3 and len(key) <= 60 and
                   (HEADING_RE.match(key) or key in {book, plain_title})}
        seen_headers = set()
        for lines in cleaned.values():
            for _ in range(4):
                if not lines:
                    break
                if re.fullmatch(r'\d{1,4}', lines[0]):
                    lines.pop(0)
                    removed_lines['page_number'] += 1
                    continue
                key = norm_line(lines[0])
                if key in headers and key in seen_headers:
                    lines.pop(0)
                    removed_lines['repeated_header'] += 1
                    continue
                if key in headers:
                    seen_headers.add(key)
                    if len(lines) > 1 and re.fullmatch(r'\d{1,4}', lines[1]):
                        del lines[1]
                        removed_lines['page_number'] += 1
                break
        for page, lines in cleaned.items():
            if not lines:
                removed.add(page)
        kept = [(page, printed, basis, '\n'.join(cleaned[page]))
                for page, printed, basis, _ in pages if page not in removed]
        target = dest / book_filename(book)
        target.write_text(render_book(book, kept), encoding='utf-8')
        _, written = parse_book(target)
        entries.append({"book": book, "text_file": target.name, "sha256": digest_file(target),
                        "bytes": target.stat().st_size, "chars": sum(len(p[3]) for p in written),
                        "pages": len(written), "source_pages": len(pages),
                        "removed_pages": sorted(removed), "removed_lines": dict(removed_lines),
                        "empty_pages": [], "label_basis": {k: sum(p[2] == k for p in written) for k in BASIS_IN.values()}})
    manifest = {"schema": 1, "kind": "textbook-text-corpus", "state": "ready", "books": entries,
                "filter": {"version": 1, "source_corpus_manifest_sha256": digest_file(manifest_path),
                           "rules": ["drop the last 推荐阅读 page and every page after it",
                                     "drop other 推荐阅读 pages and blank pages",
                                     "drop 本章/本节数字资源 and 本章/本节目标测试 lines",
                                     "drop JOEE font-artifact lines",
                                     "drop leading page numbers and repeated running headers, keeping the first heading occurrence"]},
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                "provenance": "filtered from an exported plain-text corpus; no PDF path or page number is retained",
                "redistribution": "not established; local research index"}
    (dest / 'corpus.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({"corpus": str(dest),
                      "books": [{"book": b["book"], "source_pages": b["source_pages"], "pages": b["pages"],
                                 "removed_pages": len(b["removed_pages"]), "chars": b["chars"]} for b in entries]},
                     ensure_ascii=False))


def build(db_path, corpus_dir):
    dest = Path(db_path)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('use a new absolute database path; existing indexes are preserved')
    books, manifest_path = load_corpus(corpus_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(dest)
    try:
        db.execute('PRAGMA journal_mode=MEMORY')
        db.execute('CREATE TABLE meta(body TEXT)')
        db.execute('CREATE TABLE pages(book TEXT,page INTEGER,printed_page INTEGER,label_basis TEXT,text TEXT,PRIMARY KEY(book,page))')
        db.execute('CREATE TABLE chunks(id INTEGER PRIMARY KEY,book TEXT,page INTEGER,start INTEGER,text TEXT)')
        db.execute('CREATE VIRTUAL TABLE search USING fts5(tokens)')
        metadata = []
        for book, pages, item in books:
            chunks = 0
            for page, printed, basis, text in pages:
                db.execute('INSERT INTO pages VALUES(?,?,?,?,?)', (book, page, printed, basis, text))
                for pos in range(0, len(text), 880):
                    chunk = text[pos:pos + 1000]
                    rid = db.execute('INSERT INTO chunks(book,page,start,text) VALUES(?,?,?,?)',
                                     (book, page, pos, chunk)).lastrowid
                    db.execute('INSERT INTO search(rowid,tokens) VALUES(?,?)',
                               (rid, ' '.join(search_tokens(chunk))))
                    chunks += 1
            metadata.append({"book": book, "text_file": item['text_file'], "text_sha256": item['sha256'],
                             "pages": len(pages), "chunks": chunks, "chars": sum(len(p[3]) for p in pages)})
        manifest = {"schema": 1, "state": "ready", "books": metadata,
                    "corpus_manifest_sha256": digest_file(manifest_path),
                    "created_at": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                    "dependencies": ["Python >=3.10", "SQLite FTS5"],
                    "redistribution": "not established; local research index"}
        db.execute('INSERT INTO meta VALUES(?)', (json.dumps(manifest, ensure_ascii=False),))
        db.commit()
    finally:
        db.close()
    dest.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({"database": str(dest), "pages": sum(b["pages"] for b in metadata),
                      "chunks": sum(b["chunks"] for b in metadata)}, ensure_ascii=False))


def search(path, query, limit=5, book=None, full=False):
    if not query.strip() or not 1 <= limit <= 50:
        raise ValueError('query required; limit must be 1–50')
    db = connect(path)
    try:
        meta = json.loads(db.execute('SELECT body FROM meta').fetchone()[0])
        tokens = sorted(set(search_tokens(query)))[:100]
        params = []
        if tokens:
            sql = 'SELECT c.book,c.page,c.start,c.text,bm25(search) AS score FROM search JOIN chunks c ON c.id=search.rowid WHERE search MATCH ?'
            params.append(' AND '.join('"' + t + '"' for t in tokens))
        else:
            sql = 'SELECT c.book,c.page,c.start,c.text,0 AS score FROM chunks c WHERE instr(c.text,?)>0'
            params.append(query)
        if book:
            sql += ' AND c.book=?'
            params.append(book)
        rows = db.execute(sql + ' ORDER BY score,c.id', params).fetchall()
        out, seen = [], set()
        for title, page, pos, text, score in rows:
            if (title, page) in seen:
                continue
            seen.add((title, page))
            printed, basis, body = db.execute('SELECT printed_page,label_basis,text FROM pages WHERE book=? AND page=?',
                                              (title, page)).fetchone()
            out.append(dict(book=title, page=page, printed_page=printed, printed_page_basis=basis,
                            score=score, text=body if full else text))
            if len(out) == limit:
                break
        return out
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    e = sub.add_parser('export', help='one-time migration from the previous text-bearing index')
    e.add_argument('--db', required=True)
    e.add_argument('--corpus', required=True)
    f = sub.add_parser('filter', help='drop back matter and navigation noise into a new corpus')
    f.add_argument('--corpus', required=True)
    f.add_argument('--out', required=True)
    b = sub.add_parser('build')
    b.add_argument('--db', required=True)
    b.add_argument('--corpus', required=True)
    s = sub.add_parser('search')
    s.add_argument('--db', required=True)
    s.add_argument('--query', required=True)
    s.add_argument('--limit', type=int, default=5)
    s.add_argument('--book')
    s.add_argument('--full-page', action='store_true')
    a = p.parse_args()
    if a.command == 'export':
        export_legacy(a.db, a.corpus)
    elif a.command == 'filter':
        filter_corpus(a.corpus, a.out)
    elif a.command == 'build':
        build(a.db, a.corpus)
    else:
        print(json.dumps(search(a.db, a.query, a.limit, a.book, a.full_page), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
