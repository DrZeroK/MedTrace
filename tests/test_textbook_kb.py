import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from medtrace.knowledge import validate_entry
from scripts.textbook_kb import build_index, chunk_spans, organize_drafts, search_cards, structure_corpus
from scripts.textbook_search import render_book

BOOK = '内科学第10版'


def make_corpus(root, pages):
    corpus = Path(root) / 'corpus'
    corpus.mkdir()
    path = corpus / f'{BOOK}.txt'
    path.write_text(render_book(BOOK, pages), encoding='utf-8')
    manifest = {'schema': 1, 'kind': 'textbook-text-corpus', 'state': 'ready',
                'books': [{'book': BOOK, 'text_file': path.name,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}
    (corpus / 'corpus.manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return corpus


class TextbookKnowledgeCards(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='medtrace-textbook-kb-'))
        pages = [
            (1, 1, 'header', '第一篇\n绪论\n一、总论\n（一）概述\n本书总论正文。'),
            (2, 2, 'header', '第一篇 绪论\n【临床表现】\n表现正文。\n【治疗】 ' + '长' * 2000),
            (3, 3, 'header', '本章思维导图\n（张三）本章思维导图\n【参考区间】\n3.5～5.3mmol/L。'),
            (4, 4, 'header', '第二篇\n呼吸系统疾病\n第一章 肺炎\n正文C。'),
            (5, 5, 'header', '第二篇 呼吸系统疾病\n第二章 肺炎\n正文D。'),
        ]
        self.corpus = make_corpus(self.root, pages)
        self.out = self.root / 'kb'
        structure_corpus(str(self.corpus), str(self.out))
        self.entries = [json.loads(line) for line in (self.out / 'entries.jsonl').read_text('utf-8').splitlines()]

    def test_cards_follow_entry_schema_and_hierarchy(self):
        self.assertTrue(self.entries)
        for entry in self.entries:
            validate_entry(entry)
            self.assertEqual(entry['type'], 'card')
            self.assertEqual(entry['status'], 'draft')
            self.assertEqual(entry['book'], BOOK)
            self.assertEqual(entry['source_id'], 'PMPH-IM10')
            self.assertEqual(entry['scope'], 'adult')
            self.assertEqual(entry['license'], 'pending')
            self.assertEqual(entry['candidate_source_ids'], ['PMPH-IM10'])
            self.assertLessEqual(len(entry['text']), 1800)
        ids = [entry['id'] for entry in self.entries]
        self.assertEqual(ids[0], 'TB-IM10-0001')
        self.assertEqual(len(ids), len(set(ids)))

    def test_labels_split_and_long_cards_split(self):
        treatment = [entry for entry in self.entries if entry['structure'].get('label') == '【治疗】']
        self.assertEqual(len(treatment), 2)
        self.assertEqual([entry['title'].endswith('：治疗（1/2）') for entry in treatment], [True, False])
        self.assertTrue(any(entry['title'].endswith('：治疗（2/2）') for entry in treatment))
        interval = [entry for entry in self.entries if entry['structure'].get('label') == '【参考区间】']
        self.assertEqual(interval[0]['text'], '3.5～5.3mmol/L。')
        self.assertFalse(any('思维导图' in entry['text'] or '张三' in entry['text'] for entry in self.entries))

    def test_chunk_spans_preserve_text_and_measurements(self):
        prefix = "甲" * 15
        measurement = "3.5～5.3 mmol/L"
        text = f"{prefix}{measurement}。\n后续段落。"
        spans = list(chunk_spans(text, 20))
        self.assertEqual("".join(text[start:end] for start, end, _ in spans), text)
        self.assertTrue(all(end - start <= 20 for start, end, _ in spans))
        self.assertEqual(sum(measurement in text[start:end] for start, end, _ in spans), 1)

    def test_organized_evidence_tracks_actual_page_and_parent_offsets(self):
        corpus = self.root / 'extra-corpus'
        corpus.mkdir()
        make_corpus(corpus, [
            (10, 6, 'header', '第一章 主题\n【实验室检查】\n' + '一' * 500 + '。'),
            (11, 7, 'offset_inferred', '二' * 500 + '。'),
        ])
        structured = self.root / 'two-pages'
        structure_corpus(corpus / 'corpus', structured)
        source = structured / 'entries.jsonl'
        parent = json.loads(source.read_text('utf-8'))
        output = self.root / 'evidence.jsonl'
        stats = organize_drafts(source, output)
        self.assertEqual(stats["over_limit"], 0)
        rows = [json.loads(line) for line in output.read_text('utf-8').splitlines()]
        self.assertEqual([r["page_start"] for r in rows], [10, 11])
        self.assertEqual([r["page_end"] for r in rows], [10, 11])
        self.assertIn("第6页", rows[0]["locator"])
        self.assertIn("第7页", rows[1]["locator"])
        for row in rows:
            self.assertEqual(row["parent_id"], parent["id"])
            self.assertEqual(row["text"],
                             parent["text"][row["parent_char_start"]:row["parent_char_end"]].strip())
            self.assertIn("tests", row["categories"])

    def test_select_one_verified_book_from_larger_manifest(self):
        manifest_path = self.corpus / 'corpus.manifest.json'
        manifest = json.loads(manifest_path.read_text('utf-8'))
        manifest['books'].append({'book': '儿科学第10版', 'text_file': 'missing.txt', 'sha256': 'bad'})
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        selected = self.root / 'selected'
        structure_corpus(self.corpus, selected, selected_books=[BOOK])
        self.assertEqual(json.loads((selected / 'manifest.json').read_text('utf-8'))['counts']['cards'],
                         len(self.entries))
        with self.assertRaisesRegex(ValueError, 'textbooks not in corpus'):
            structure_corpus(self.corpus, self.root / 'unknown', selected_books=['未知书名'])

    def test_outline_and_index(self):
        outline = json.loads((self.out / 'outline.json').read_text('utf-8'))
        self.assertEqual(outline['books'][0]['book'], BOOK)
        parts = [node['label'] for node in outline['books'][0]['children']]
        self.assertIn('第一篇 绪论', parts)
        self.assertIn('第二篇 呼吸系统疾病', parts)
        db = str(self.root / 'cards.sqlite')
        build_index(str(self.out / 'entries.jsonl'), db)
        hits = search_cards(db, '参考区间', 5)
        self.assertTrue(hits)
        self.assertTrue(all(hit['status'] == 'draft' for hit in hits))
        self.assertEqual(search_cards(db, '参考区间', 5, book=BOOK)[0]['book'], BOOK)
        manifest = json.loads((Path(db).with_suffix('.manifest.json')).read_text('utf-8'))
        self.assertFalse(manifest['release'])
        self.assertNotIn(b'Downloads', Path(db).read_bytes())
