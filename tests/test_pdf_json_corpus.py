import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.pdf_json_corpus import build
from scripts.textbook_search import parse_book, render_book


class PdfJsonCorpus(unittest.TestCase):
    def test_conversion_uses_body_start_and_page_labels(self):
        root = Path(tempfile.mkdtemp(prefix='medtrace-pdf-json-'))
        pages = [
            {'pdf_page': 1, 'text': 'front matter'},
            {'pdf_page': 3, 'text': '1\n第一章 总论\n正文 A'},
            {'pdf_page': 4, 'text': '\ufffc第二章\n正文 B'},
        ]
        source = root / 'book.json'
        source.write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
        metadata = root / 'metadata.json'
        metadata.write_text(json.dumps({'books': [
            {'book': '测试教材第10版', 'json': str(source), 'start': 3, 'offset': 2, 'method': 'pdf_text'}
        ]}, ensure_ascii=False), encoding='utf-8')
        out = root / 'corpus'
        build(str(metadata), str(out))
        book, parsed = parse_book(out / '测试教材第10版.txt')
        self.assertEqual(book, '测试教材第10版')
        self.assertEqual([p[0] for p in parsed], [1, 2])
        self.assertEqual(parsed[0][1:3], (1, 'header'))
        self.assertEqual(parsed[1][1:3], (2, 'offset_inferred'))
        self.assertEqual(parsed[1][3], '第二章\n正文 B')
        manifest = json.loads((out / 'corpus.manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['books'][0]['pages'], 2)
        self.assertEqual(manifest['books'][0]['text_method'], 'pdf_text')
        self.assertNotIn('.pdf', json.dumps(manifest))
        self.assertNotIn('/Users/', json.dumps(manifest))

    def test_copy_existing_corpus_and_merge_manifest(self):
        root = Path(tempfile.mkdtemp(prefix='medtrace-pdf-json-merge-'))
        old = root / 'old'
        old.mkdir()
        target = old / '旧教材.txt'
        target.write_text(render_book('旧教材', [(1, 1, 'header', '旧正文')]), encoding='utf-8')
        (old / 'corpus.manifest.json').write_text(json.dumps({
            'schema': 1, 'kind': 'textbook-text-corpus', 'state': 'ready',
            'books': [{'book': '旧教材', 'text_file': target.name,
                       'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}],
        }, ensure_ascii=False), encoding='utf-8')
        source = root / 'new.json'
        source.write_text(json.dumps([{'pdf_page': 2, 'text': '1\n新正文'}], ensure_ascii=False), encoding='utf-8')
        metadata = root / 'metadata.json'
        metadata.write_text(json.dumps({'books': [
            {'book': '新教材', 'json': str(source), 'start': 2, 'offset': 1, 'method': 'ocr'}
        ]}, ensure_ascii=False), encoding='utf-8')
        out = root / 'merged'
        build(str(metadata), str(out), str(old))
        manifest = json.loads((out / 'corpus.manifest.json').read_text('utf-8'))
        self.assertEqual([b['book'] for b in manifest['books']], ['旧教材', '新教材'])
        self.assertEqual(manifest['books'][1]['text_method'], 'ocr')
        self.assertTrue((out / '旧教材.txt').is_file())
        self.assertTrue((out / '新教材.txt').is_file())
