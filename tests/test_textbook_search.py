import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.textbook_search import build, filter_corpus, parse_book, render_book, search


def make_corpus(root):
    corpus = Path(root) / 'corpus'
    corpus.mkdir()
    bodies = {'A': '测试血钾 BNP ' * 120, 'B': '测试血钾 BNP'}
    books = []
    for book, body in bodies.items():
        path = corpus / f'{book}.txt'
        path.write_text(f'# 书名：{book}\n--- 页 1（书页 1，页眉） ---\n{body}\n', encoding='utf-8')
        books.append({'book': book, 'text_file': path.name,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (corpus / 'corpus.manifest.json').write_text(json.dumps(
        {'schema': 1, 'kind': 'textbook-text-corpus', 'state': 'ready', 'books': books}), encoding='utf-8')
    return corpus


def make_paged_corpus(root, books):
    corpus = Path(root) / 'corpus'
    corpus.mkdir()
    entries = []
    for book, pages in books.items():
        path = corpus / f'{book}.txt'
        path.write_text(render_book(book, pages), encoding='utf-8')
        entries.append({'book': book, 'text_file': path.name,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (corpus / 'corpus.manifest.json').write_text(json.dumps(
        {'schema': 1, 'kind': 'textbook-text-corpus', 'state': 'ready', 'books': entries}), encoding='utf-8')
    return corpus


class TextbookSearch(unittest.TestCase):
    def setUp(self):
        # Preserve artifacts under the project's no-permanent-deletion policy.
        root = Path(tempfile.mkdtemp(prefix='medtrace-textbook-test-'))
        self.db = str(root / 'fixture.sqlite')
        build(self.db, str(make_corpus(root)))

    def test_search_boundary_book_and_page_deduplication(self):
        self.assertEqual(len(search(self.db, 'BNP')), 2)
        self.assertEqual(len(search(self.db, '血钾', book='A')), 1)
        self.assertEqual(search(self.db, 'BNP', book="A' OR 1=1--"), [])
        self.assertEqual(len(search(self.db, '钾')), 2)
        self.assertEqual(search(self.db, 'xyzmissing'), [])
        self.assertTrue(search(self.db, 'BNP', full=True)[0]['text'].startswith('测试血钾 BNP'))
        self.assertEqual(search(self.db, 'BNP')[0]['printed_page_basis'], 'header')
        with self.assertRaises(ValueError):
            search(self.db, 'BNP', limit=0)
        with self.assertRaises(ValueError):
            search(self.db, '')

    def test_parse_rejects_incomplete_page_labels(self):
        bad = Path(tempfile.mkdtemp(prefix='medtrace-textbook-bad-')) / 'bad.txt'
        bad.write_text('# 书名：Bad\n--- 页 1（书页 1） ---\n文本\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            parse_book(bad)

    def test_filter_removes_back_matter_navigation_and_headers(self):
        root = Path(tempfile.mkdtemp(prefix='medtrace-textbook-filter-'))
        pages = [
            (1, 1, 'header', '1\n第一章 总论\n本章数字资源\n钾 3.5'),
            (2, 2, 'header', '第一章 总论\n2\nJOEE\n钾 3.6'),
            (3, 3, 'header', '3\n第一章 总论\n钠 140'),
            (4, 4, 'header', '推荐阅读\n[1] 某参考书'),
            (5, 5, 'header', '第二章 低血糖\n血糖 3.9'),
            (6, 6, 'header', '6\n第二章 低血糖\n血糖 3.8'),
            (7, 7, 'header', '7\n第二章 低血糖\n血糖 3.7'),
            (8, 8, 'header', '推荐阅读\n[1] 另参考书'),
            (9, 9, 'header', '9\n中英文名词对照索引\n条目 123'),
            (10, 10, 'header', ''),
        ]
        corpus = make_paged_corpus(root, {'A': pages})
        filtered = root / 'filtered'
        filter_corpus(str(corpus), str(filtered))
        _, kept = parse_book(filtered / 'A.txt')
        self.assertEqual([p[0] for p in kept], [1, 2, 3, 5, 6, 7])
        self.assertEqual(kept[0][3].splitlines(), ['第一章 总论', '钾 3.5'])
        self.assertEqual(kept[1][3], '钾 3.6')
        self.assertEqual(kept[4][3], '血糖 3.8')
        manifest = json.loads((filtered / 'corpus.manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['books'][0]['removed_pages'], [4, 8, 9, 10])
        db = str(root / 'filtered.sqlite')
        build(db, str(filtered))
        self.assertEqual(len(search(db, '血糖')), 3)
        self.assertEqual(len(search(db, '低血糖')), 1)
        self.assertEqual(search(db, '推荐阅读'), [])
        self.assertEqual(search(db, 'JOEE'), [])
        self.assertEqual(search(db, '本章数字资源'), [])

    def test_filter_config_cutoff_ranges_and_exercise_pages(self):
        root = Path(tempfile.mkdtemp(prefix='medtrace-textbook-cutoff-'))
        pages = [
            (1, 1, 'header', '第一章 总论\n正文1'),
            (2, 2, 'header', '参考文献\n［1］某书'),
            (3, 3, 'header', '中英文名词对照索引\n条目 1'),
            (4, 4, 'header', '人卫官网\n定价：10元\n策划编辑 某人'),
            (5, 5, 'header', '思考题解题思路 本章目标测试 本章思维导图\n思考题 1'),
            (6, 6, 'header', '第二章 低血糖\n正文2'),
            (7, 7, 'header', '练习题与复习题参考答案\n1. 2'),
            (8, 8, 'header', '附录\n公式'),
            (9, 9, 'header', '第10版\n封底'),
        ]
        corpus = make_paged_corpus(root, {'A': pages})
        config = root / 'cutoffs.json'
        config.write_text(json.dumps({'A': {'cut_page': 9, 'drop_ranges': [[7, 7]]}}), encoding='utf-8')
        filtered = root / 'filtered'
        filter_corpus(str(corpus), str(filtered), str(config))
        _, kept = parse_book(filtered / 'A.txt')
        self.assertEqual([p[0] for p in kept], [1, 6, 8])
        manifest = json.loads((filtered / 'corpus.manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['books'][0]['cutoff'], 9)
        categories = manifest['books'][0]['removed_categories']
        self.assertEqual(categories['reference'], 1)
        self.assertEqual(categories['index'], 1)
        self.assertEqual(categories['advertisement'], 1)
        self.assertEqual(categories['exercise'], 1)
        self.assertEqual(categories['exercise_or_answer'], 1)
        self.assertEqual(categories['cutoff'], 1)

    def test_build_can_exclude_book(self):
        root = Path(tempfile.mkdtemp(prefix='medtrace-textbook-exclude-'))
        corpus = make_corpus(root)
        db = str(root / 'excluded.sqlite')
        build(db, str(corpus), exclude_books=['A'])
        self.assertEqual(search(db, 'BNP', book='A'), [])
        self.assertTrue(search(db, 'BNP', book='B'))
        manifest = json.loads(Path(db).with_suffix('.manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['excluded_books'], ['A'])
        self.assertEqual([item['book'] for item in manifest['books']], ['B'])

