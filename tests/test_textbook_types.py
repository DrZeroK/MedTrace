import unittest

from medtrace.knowledge import validate_entry
from scripts.textbook_types import lab_entries, rule_entries, term_entries


def card(card_id, book, source_id, structure, text, page=5, locator=None):
    return {
        'id': card_id, 'type': 'card', 'book': book, 'source_id': source_id,
        'source': 'https://example.invalid/source', 'version': '第10版',
        'license': 'pending', 'status': 'draft', 'scope': 'adult',
        'reviewer': '', 'reviewed_at': '',
        'permission_review': {'status': 'not_granted', 'reviewer': '', 'reviewed_at': '', 'evidence': [],
                              'requested_uses': ['offline_index'], 'request_status': 'not_sent'},
        'clinical_review': {'status': 'not_signed', 'reviewer': '', 'reviewed_at': '', 'evidence': []},
        'candidate_source_ids': [source_id], 'source_note': 'test',
        'structure': structure, 'text': text,
        'locator': locator or f'第{page}页（文本页 {page}；页码依据：页眉）',
        'page_start': page, 'page_end': page, 'printed_page_start': page, 'printed_page_end': page,
        'page_basis': ['header'],
    }


PDF = {
    '内科学第10版': {
        36: '第一章 肺炎\n肺炎（pneumonia）是终末气道、肺泡和肺间质的炎症。',
        806: '【诊断与鉴别诊断】 有导致血钾增高和/或肾排钾减少的基础疾病，血清钾＞5.3mmol/L 即可确诊。',
    },
    '诊断学第10版': {
        260: '白细胞计数\n成人（3.5～9.5）×109/L。',
    },
}


class TextbookTypedEntries(unittest.TestCase):
    def test_term_requires_pdf_heading_and_keeps_alias(self):
        source = card('C1', '内科学第10版', 'PMPH-IM10', {'chapter': '第一章 肺炎'},
                      '肺炎（pneumonia）是终末气道、肺泡和肺间质的炎症。')
        entries, skipped = term_entries([source], PDF)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        entry['id'] = 'TB-T-TEST-0001'
        validate_entry(entry)
        self.assertEqual(entry['type'], 'term')
        self.assertEqual(entry['title'], '肺炎')
        self.assertEqual(entry['aliases'], ['pneumonia'])
        self.assertEqual(entry['pdf_audit']['pdf_pages'], [36])
        self.assertEqual(skipped, [])

    def test_missing_pdf_heading_is_skipped(self):
        source = card('C1', '内科学第10版', 'PMPH-IM10', {'chapter': '第一章 哮喘'}, '无关正文')
        entries, skipped = term_entries([source], PDF)
        self.assertEqual(entries, [])
        self.assertEqual(skipped[0]['reason'], 'heading not found in PDF window')

    def test_lab_extracts_verified_units(self):
        source = card('C2', '诊断学第10版', 'PMPH-DX10',
                      {'section': '第一节 血液一般检测', 'topic': '二、白细胞的检测',
                       'subtopic': '（一）白细胞计数', 'label': '【参考区间】'},
                      '参考区间：成人（3.5～9.5）× 10\n9\n/L。', page=237, locator='第237页（文本页 237；页码依据：页眉）')
        entries, skipped = lab_entries([source], PDF)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        entry['id'] = 'TB-L-TEST-0001'
        validate_entry(entry)
        self.assertEqual(entry['type'], 'lab')
        self.assertEqual(entry['title'], '白细胞计数')
        self.assertEqual(entry['units'], ['×10^9/L'])
        self.assertIsNone(entry['reference_interval'])
        self.assertTrue(entry['text'].startswith('参考区间：'))
        self.assertEqual(entry['pdf_audit']['pdf_pages'], [260])
        self.assertEqual(skipped, [])

    def test_lab_without_units_is_skipped(self):
        source = card('C3', '诊断学第10版', 'PMPH-DX10',
                      {'section': '第一节 血液一般检测', 'subtopic': '（一）白细胞计数', 'label': '【参考区间】'},
                      '阴性。', page=237)
        entries, skipped = lab_entries([source], PDF)
        self.assertEqual(entries, [])

    def test_rule_keeps_threshold_and_evidence(self):
        source = card('TB-IM10-2158', '内科学第10版', 'PMPH-IM10',
                      {'part': '第七篇 内分泌和代谢性疾病', 'chapter': '第十二章 水、电解质代谢和酸碱平衡失常',
                       'section': '第二节 钾代谢失常', 'label': '【诊断与鉴别诊断】'},
                      '有导致血钾增高和/或肾排钾减少的基础疾病，血清钾＞5.3mmol/L 即可确诊。',
                      page=775, locator='第775页（文本页 775；页码依据：页眉）')
        entries, skipped = rule_entries({'TB-IM10-2158': source}, PDF)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        entry['id'] = 'TB-R-TEST-0001'
        validate_entry(entry)
        self.assertEqual(entry['type'], 'rule')
        self.assertEqual(entry['operator'], 'above')
        self.assertEqual(entry['threshold'], 5.3)
        self.assertEqual(entry['unit'], 'mmol/L')
        self.assertTrue(entry['requires'])
        self.assertEqual(entry['pdf_audit']['pdf_pages'], [806])
        self.assertTrue(entry['pdf_audit']['evidence'].startswith('【诊断与鉴别诊断】'))
