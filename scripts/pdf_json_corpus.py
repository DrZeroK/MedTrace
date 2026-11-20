"""Build a plain-text corpus from page-level PDF/OCR JSON without storing PDF paths."""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.textbook_search import book_filename, digest_file, parse_book, render_book

PAGE_NUMBER = re.compile(r'\d{1,4}')


def clean_text(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\ufffc', '').replace('\u200b', '')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text


def page_label(text, pdf_page, offset):
    for line in [line.strip() for line in text.splitlines() if line.strip()][:4]:
        if PAGE_NUMBER.fullmatch(line):
            return int(line), 'header'
    return pdf_page - offset, 'offset_inferred'


def convert_entry(entry, pages_json):
    raw = json.loads(Path(pages_json).read_text('utf-8'))
    start = int(entry['start'])
    offset = int(entry['offset'])
    pages = []
    for record in raw:
        pdf_page = int(record['pdf_page'])
        if pdf_page < start:
            continue
        text = clean_text(record.get('text', ''))
        label, basis = page_label(text, pdf_page, offset)
        pages.append((pdf_page - start + 1, label, basis, text))
    if not pages:
        raise ValueError(f'no pages after start for {entry["book"]}')
    return pages


def corpus_entry(book, target, text_method):
    _, pages = parse_book(target)
    return {
        'book': book,
        'text_file': target.name,
        'sha256': digest_file(target),
        'bytes': target.stat().st_size,
        'chars': sum(len(page[3]) for page in pages),
        'pages': len(pages),
        'empty_pages': [page[0] for page in pages if not page[3].strip()],
        'label_basis': {basis: sum(page[2] == basis for page in pages)
                        for basis in ('header', 'offset_inferred')},
        'text_method': text_method,
    }


def build(metadata_path, out_dir, copy_corpus=None):
    meta = json.loads(Path(metadata_path).read_text('utf-8'))
    dest = Path(out_dir)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('use a new absolute corpus directory')
    dest.mkdir(parents=True)
    entries = []
    seen = set()
    if copy_corpus:
        source = Path(copy_corpus)
        source_manifest = json.loads((source / 'corpus.manifest.json').read_text('utf-8'))
        for item in source_manifest['books']:
            book = item['book']
            if book in seen:
                raise ValueError(f'duplicate book: {book}')
            seen.add(book)
            text_file = item['text_file']
            target = dest / text_file
            target.write_bytes((source / text_file).read_bytes())
            entries.append(corpus_entry(book, target, item.get('text_method', 'pdf_text_legacy')))
    for item in meta['books']:
        book = item['book']
        if book in seen:
            raise ValueError(f'duplicate book: {book}')
        seen.add(book)
        pages = convert_entry(item, item['json'])
        target = dest / book_filename(book)
        target.write_text(render_book(book, pages), encoding='utf-8')
        entries.append(corpus_entry(book, target, item.get('method', 'pdf_text')))
    manifest = {
        'schema': 1, 'kind': 'textbook-text-corpus', 'state': 'ready', 'books': entries,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'provenance': 'PDF text extracted with PDFKit; 人体寄生虫学第10版 from Apple Vision OCR cache; no PDF path retained',
        'redistribution': 'not established; local research index',
    }
    (dest / 'corpus.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
    print(json.dumps({'corpus': str(dest), 'books': len(entries),
                      'pages': sum(item['pages'] for item in entries),
                      'chars': sum(item['chars'] for item in entries)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--copy-corpus')
    args = parser.parse_args()
    build(args.metadata, args.out, args.copy_corpus)


if __name__ == '__main__':
    main()
