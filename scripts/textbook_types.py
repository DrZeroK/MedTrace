"""Derive term/lab/rule entries from the structured cards and audit them against PDF text.

The PDF text is produced separately by scripts/pdf_text.swift (PDFKit page.string).
Only source-matched entries are written; all output remains draft and non-releasable.
"""
import argparse
import copy
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from medtrace.knowledge import validate_entry
from scripts.textbook_kb import outline_for
from scripts.textbook_search import digest_file

PDF_OFFSET = {'内科学第10版': 31, '诊断学第10版': 23}
PDF_AUDIT_FILES = {'内科学第10版': 'im10.json', '诊断学第10版': 'dx10.json'}
NUM_PREFIX = re.compile(r'^第[一二三四五六七八九十百]+[章节]\s*')
SUB_PREFIX = re.compile(r'^（[一二三四五六七八九十]+）\s*')
TOPIC_PREFIX = re.compile(r'^[一二三四五六七八九十]+、\s*')
TERM_EXCLUDE = (
    '总论', '概述', '病因', '发病机制', '病理', '临床表现', '诊断', '鉴别', '治疗', '预防',
    '预后', '并发症', '检查', '实验室', '辅助检查', '评估', '分类', '分型', '原则', '方法',
    '技术', '操作', '护理', '康复', '随访', '监测', '管理', '策略', '流程', '记录', '书写',
    '沟通', '规范', '指南', '进展', '研究', '应用', '健康教育', '防治', '处理', '适应证',
    '禁忌证', '注意事项', '参考区间', '临床意义', '标本来源', '其他', '概要', '的重要性',
    '要求', '内容',
)
TERM_PROCEDURE = re.compile(r'测定|检测|计数|试验|检查法|分析|培养|染色|活检|穿刺|插管|造影|扫描')
LAB_GROUP = (
    '一般性状', '化学检查', '显微镜检查', '病原生物学', '分类计数', '筛查检测', '膜缺陷',
    '酶缺陷', '珠蛋白生成异常', '自身免疫性溶血', '阵发性睡眠性', '抗凝系统', '纤溶活性',
    '血管壁检测', '血小板检测', '凝血因子检测', '平均值的计算', '参考区间', '参考值',
    '临床意义', '标本来源', '尿液检测', '脑脊液检测', '浆膜腔积液检测', '精液检测',
    '溶血性贫血的实验室检测', '生殖系统体液检测', '胆汁酸代谢检查', '乙型肝炎五项检测',
    '有关参数的应用',
)
LAB_EXCLUDE = {
    '梅毒螺旋体抗体测定', 'pH', '免疫球蛋白', '其他免疫检测', '酶类肿瘤标志物检测',
    '激素类肿瘤标志物检测', 'IL-2 及其受体测定', '网织红细胞测定',
}
UNIT_RE = re.compile(
    r'(×10\^\d{1,2}/L|(?:mmol|μmol|umol|nmol|pmol)/(?:L|24h)|'
    r'(?:mg|μg|ug|ng|pg|g)/(?:L|dl|dL|ml)|(?:U|IU|mU|μU|kU)/(?:L|mL|ml)|'
    r'AU/ml|mm/h|ml/min(?:/1\.73m2)?|fl|pg|%|L/L)'
)
ENGLISH_PAREN = re.compile(r'[（(]([A-Za-z][A-Za-z0-9 ,;，、；/\-&\'.]{1,80})[）)]')
RULES = [
    {
        'source_card_id': 'TB-IM10-2158',
        'title': '血清钾＞5.3mmol/L（高钾血症诊断阈值）',
        'analyte': '血清钾', 'unit': 'mmol/L', 'operator': 'above', 'threshold': 5.3,
        'requires': {'population': '有导致血钾增高和/或肾排钾减少的基础疾病', 'specimen': '血清', 'method': '未注明'},
        'text': '有导致血钾增高和/或肾排钾减少的基础疾病，血清钾＞5.3mmol/L 即可确诊。',
        'evidence': '5.3mmol/L', 'keyword': '高钾血症', 'context': '即可确诊',
    },
    {
        'source_card_id': 'TB-IM10-0061',
        'title': 'FEV1/FVC＜70%（持续气流受限）',
        'analyte': 'FEV1/FVC', 'unit': '%', 'operator': 'below', 'threshold': 70,
        'requires': {'population': '有慢阻肺病相关症状和危险因素', 'specimen': '肺功能', 'method': '吸入支气管扩张剂后'},
        'text': '吸入支气管扩张剂后，FEV1/FVC＜70% 可确定为持续气流受限。',
        'evidence': '70%', 'keyword': '持续气流受限', 'context': '支气管扩张剂',
    },
    {
        'source_card_id': 'TB-DX10-0549',
        'title': '中性粒细胞绝对值＜1.5×10^9/L（粒细胞减少症）',
        'analyte': '中性粒细胞绝对值', 'unit': '×10^9/L', 'operator': 'below', 'threshold': 1.5,
        'requires': {'population': '未注明', 'specimen': '外周血', 'method': '未注明'},
        'text': '当中性粒细胞绝对值低于 1.5×10^9/L，称为粒细胞减少症。',
        'evidence': '1.5×10^9/L', 'keyword': '粒细胞减少症', 'context': '粒细胞减少症',
    },
    {
        'source_card_id': 'TB-DX10-0549',
        'title': '中性粒细胞绝对值＜0.5×10^9/L（粒细胞缺乏症）',
        'analyte': '中性粒细胞绝对值', 'unit': '×10^9/L', 'operator': 'below', 'threshold': 0.5,
        'requires': {'population': '未注明', 'specimen': '外周血', 'method': '未注明'},
        'text': '当中性粒细胞绝对值低于 0.5×10^9/L 时称为粒细胞缺乏症。',
        'evidence': '0.5×10^9/L', 'keyword': '粒细胞缺乏症', 'context': '粒细胞缺乏症',
    },
    {
        'source_card_id': 'TB-IM10-1406',
        'title': '血尿酸＞420μmol/L（男性高尿酸血症）',
        'analyte': '血尿酸', 'unit': 'μmol/L', 'operator': 'above', 'threshold': 420,
        'requires': {'population': '男性', 'specimen': '空腹血尿酸', 'method': '非同日两次'},
        'text': '非同日两次空腹血尿酸男性高于 420μmol/L，女性高于 360μmol/L。',
        'evidence': '420μmol/L', 'keyword': '高尿酸血症', 'context': '高尿酸血症',
    },
    {
        'source_card_id': 'TB-IM10-1406',
        'title': '血尿酸＞360μmol/L（女性高尿酸血症）',
        'analyte': '血尿酸', 'unit': 'μmol/L', 'operator': 'above', 'threshold': 360,
        'requires': {'population': '女性', 'specimen': '空腹血尿酸', 'method': '非同日两次'},
        'text': '非同日两次空腹血尿酸男性高于 420μmol/L，女性高于 360μmol/L。',
        'evidence': '360μmol/L', 'keyword': '高尿酸血症', 'context': '高尿酸血症',
    },
    {
        'source_card_id': 'TB-IM10-2086',
        'title': '血糖＜2.8mmol/L（发作时低血糖症）',
        'analyte': '血糖', 'unit': 'mmol/L', 'operator': 'below', 'threshold': 2.8,
        'requires': {'population': '有低血糖症状', 'specimen': '血糖', 'method': '发作时'},
        'text': '低血糖症状发作时血糖低于 2.8mmol/L，补充糖后症状迅速缓解。',
        'evidence': '2.8mmol/L', 'keyword': '低血糖', 'context': '低血糖症状',
    },
]


def audit_norm(text):
    return re.sub(r'[^\w\u4e00-\u9fff]+', '', text or '')


def extract_units(text):
    text = re.sub(r'×\s*10\s*\n?\s*(\d{1,2})\s*\n?\s*/\s*L', r'×10^\1/L', text)
    text = re.sub(r'\s+', ' ', text)
    units = []
    for match in UNIT_RE.finditer(text):
        unit = match.group(1)
        if unit not in units:
            units.append(unit)
    return units


def english_aliases(text):
    values = []
    for match in ENGLISH_PAREN.finditer(text[:800]):
        phrase = match.group(1).strip()
        parts = re.split(r'[,;，；]', phrase)
        if len(parts) == 1:
            parts = [phrase]
        for piece in parts:
            piece = piece.strip()
            if 2 <= len(piece) <= 60 and piece.lower() not in {'and', 'or', 'the'} and piece not in values:
                values.append(piece)
    return values[:8]


def page_window(book, printed, pdf_texts, radius=2):
    if printed is None:
        return []
    center = printed + PDF_OFFSET[book]
    return [(page, pdf_texts[book].get(page, '')) for page in range(center - radius, center + radius + 1)
            if pdf_texts[book].get(page)]


def find_heading(book, printed, title, pdf_texts):
    needle = audit_norm(title)
    for page, text in page_window(book, printed, pdf_texts):
        for line in text.splitlines():
            line_norm = audit_norm(line)
            if needle and needle in line_norm and len(line_norm) <= len(needle) + 20:
                return page, line.strip()
    return None


def find_lab(book, printed, title, units, probe_text, pdf_texts):
    title_needle = audit_norm(title)
    pages = page_window(book, printed, pdf_texts, radius=3)
    title_pages = [page for page, text in pages if title_needle and title_needle in audit_norm(text)]
    unit_pages = defaultdict(list)
    for unit in units:
        needle = audit_norm(unit)
        for page, text in pages:
            if needle and needle in audit_norm(text):
                unit_pages[unit].append(page)
    if not title_pages or len(unit_pages) != len(units):
        return None
    probe = audit_norm(probe_text)[:60]
    evidence_page, evidence = None, ''
    for page, text in pages:
        for line in text.splitlines():
            if probe and probe in audit_norm(line):
                evidence_page, evidence = page, line.strip()
                break
        if evidence:
            break
    if not evidence:
        evidence_page = title_pages[0]
        for page in title_pages:
            if any(page in unit_pages[unit] for unit in units):
                evidence_page = page
                break
        for line in dict(pages).get(evidence_page, '').splitlines():
            if any(audit_norm(unit) in audit_norm(line) for unit in units):
                evidence = line.strip()
                break
        if not evidence:
            evidence = dict(pages).get(evidence_page, '').strip()[:160]
    return evidence_page, sorted({page for unit in units for page in unit_pages[unit]}), evidence


def find_rule(book, printed, evidence, keyword, context, pdf_texts):
    pages = page_window(book, printed, pdf_texts)
    for page, text in pages:
        for line in text.splitlines():
            if audit_norm(evidence) in audit_norm(line) and audit_norm(context) in audit_norm(line):
                return page, line.strip()
    for page, text in pages:
        if audit_norm(evidence) in audit_norm(text) and audit_norm(context) in audit_norm(text):
            for line in text.splitlines():
                if audit_norm(evidence) in audit_norm(line):
                    return page, line.strip()
    return None


def page_locator(book, pdf_page, fallback):
    printed = pdf_page - PDF_OFFSET[book]
    if printed < 1:
        return fallback
    return f'第{printed}页（文本页 {printed}；页码依据：页眉）'


def base_entry(card, kind, note, audit):
    entry = {
        'source': card['source'],
        'version': card['version'],
        'license': 'pending',
        'status': 'draft',
        'scope': card['scope'],
        'reviewer': '',
        'reviewed_at': '',
        'permission_review': copy.deepcopy(card['permission_review']),
        'clinical_review': {
            'status': 'not_signed', 'reviewer': '', 'reviewed_at': '', 'evidence': [],
            'pre_review_by': 'Codex AI (not a clinician signature)',
            'pre_reviewed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'pre_review_status': 'textbook_structure_pdf_checked_only',
            'notes': note,
        },
        'candidate_source_ids': list(card['candidate_source_ids']),
        'source_id': card['source_id'],
        'book': card['book'],
        'source_note': card['source_note'],
        'structure': dict(card['structure']),
        'derived_from': [card['id']],
        'pdf_audit': {
            'status': 'matched',
            'method': 'PDFKit page.string',
            'checked_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            **audit,
        },
    }
    return entry


def term_entries(cards, pdf_texts):
    candidates = {}
    for card in cards:
        for key in ('chapter', 'section'):
            raw = card['structure'].get(key)
            if not raw:
                continue
            title = NUM_PREFIX.sub('', raw).strip()
            if not 2 <= len(title) <= 30:
                continue
            if any(word in title for word in TERM_EXCLUDE) or TERM_PROCEDURE.search(title):
                continue
            key_norm = audit_norm(title)
            if key_norm and key_norm not in candidates:
                candidates[key_norm] = (title, card)
    entries, skipped = [], []
    for title, card in candidates.values():
        found = find_heading(card['book'], card.get('printed_page_start'), title, pdf_texts)
        if not found:
            skipped.append({'title': title, 'card_id': card['id'], 'reason': 'heading not found in PDF window'})
            continue
        page, evidence = found
        page_text = pdf_texts[card['book']].get(page, '')
        aliases = []
        for alias in english_aliases(card['text']):
            if audit_norm(alias) in audit_norm(page_text) and alias not in aliases:
                aliases.append(alias)
        entry = base_entry(card, 'term', '结构提取与 PDF 标题核对；未做术语或临床签审。', {
            'pdf_pages': [page], 'evidence': evidence[:200],
        })
        entry.update({
            'type': 'term', 'title': title, 'text': title, 'aliases': aliases[:6],
            'locator': page_locator(card['book'], page, card['locator']),
            'page_start': page - PDF_OFFSET[card['book']],
            'page_end': page - PDF_OFFSET[card['book']],
            'printed_page_start': page - PDF_OFFSET[card['book']],
            'printed_page_end': page - PDF_OFFSET[card['book']],
            'page_basis': ['header'],
        })
        entries.append(entry)
    return entries, skipped


def lab_entries(cards, pdf_texts):
    candidates = {}
    for card in cards:
        if card['book'] != '诊断学第10版' or card['structure'].get('label') not in ('【参考区间】', '【参考值】'):
            continue
        title = None
        for key, prefix in (('subtopic', SUB_PREFIX), ('topic', TOPIC_PREFIX)):
            raw = card['structure'].get(key)
            if not raw:
                continue
            value = prefix.sub('', raw).strip()
            if 2 <= len(value) <= 40 and not any(word in value for word in LAB_GROUP):
                title = value
                break
        if not title or '和' in title or '与' in title or '、' in title:
            continue
        units = extract_units(card['text'])
        if not units:
            continue
        key_norm = audit_norm(title)
        if key_norm and key_norm not in candidates:
            candidates[key_norm] = (title, units, card)
    entries, skipped = [], []
    for title, units, card in candidates.values():
        if title in LAB_EXCLUDE:
            skipped.append({'title': title, 'card_id': card['id'],
                            'reason': 'manual exclusion: ambiguous/group unit'})
            continue
        found = find_lab(card['book'], card.get('printed_page_start'), title, units, card['text'], pdf_texts)
        if not found:
            skipped.append({'title': title, 'card_id': card['id'], 'reason': 'title/units not found in PDF window'})
            continue
        page, pages, evidence = found
        page_text = ' '.join(pdf_texts[card['book']].get(item, '') for item in pages)
        aliases = []
        for alias in english_aliases(card['text']):
            if audit_norm(alias) in audit_norm(page_text) and alias not in aliases:
                aliases.append(alias)
        entry = base_entry(card, 'lab', '结构提取、PDF 参考区间文本核对；单位、标本、方法和适用人群未签审。', {
            'pdf_pages': pages,
            'matched_title': True,
            'matched_units': units,
            'evidence': evidence[:200],
        })
        entry.update({
            'type': 'lab', 'title': title, 'text': card['text'], 'aliases': aliases[:6],
            'units': units, 'reference_interval': None,
            'locator': page_locator(card['book'], page, card['locator']),
            'page_start': page - PDF_OFFSET[card['book']],
            'page_end': page - PDF_OFFSET[card['book']],
            'printed_page_start': page - PDF_OFFSET[card['book']],
            'printed_page_end': page - PDF_OFFSET[card['book']],
            'page_basis': ['header'],
        })
        entry['text'] = '参考区间：' + entry['text']
        entry['aliases'] = ['参考区间', '参考值'] + entry['aliases']
        entries.append(entry)
    return entries, skipped


def rule_entries(cards_by_id, pdf_texts):
    entries, skipped = [], []
    for spec in RULES:
        card = cards_by_id.get(spec['source_card_id'])
        if not card:
            skipped.append({'title': spec['title'], 'reason': 'source card missing'})
            continue
        found = find_rule(card['book'], card.get('printed_page_start'), spec['evidence'], spec['keyword'], spec['context'], pdf_texts)
        if not found:
            skipped.append({'title': spec['title'], 'card_id': card['id'], 'reason': 'threshold not found in PDF window'})
            continue
        page, evidence = found
        entry = base_entry(card, 'rule', '结构提取与 PDF 阈值核对；阈值、适用人群、标本和方法未签审；不得用于临床。', {
            'pdf_pages': [page], 'evidence': evidence[:200],
        })
        entry.update({
            'type': 'rule', 'title': spec['title'], 'text': spec['text'], 'aliases': [],
            'analyte': spec['analyte'], 'unit': spec['unit'], 'operator': spec['operator'],
            'threshold': spec['threshold'], 'requires': dict(spec['requires']),
            'locator': page_locator(card['book'], page, card['locator']),
            'page_start': page - PDF_OFFSET[card['book']],
            'page_end': page - PDF_OFFSET[card['book']],
            'printed_page_start': page - PDF_OFFSET[card['book']],
            'printed_page_end': page - PDF_OFFSET[card['book']],
            'page_basis': ['header'],
        })
        entries.append(entry)
    return entries, skipped


def typed_store(cards_path, pdf_audit_dir, out_dir, pdf_manifest=None):
    cards_path = Path(cards_path)
    if not cards_path.is_absolute():
        raise ValueError('cards path must be absolute')
    out = Path(out_dir)
    if not out.is_absolute() or out.exists():
        raise ValueError('use a new absolute output directory')
    cards = [json.loads(line) for line in cards_path.read_text('utf-8').splitlines() if line.strip()]
    cards_by_id = {card['id']: card for card in cards}
    pdf_texts = {}
    audit_dir = Path(pdf_audit_dir)
    for book, filename in PDF_AUDIT_FILES.items():
        raw = json.loads((audit_dir / filename).read_text('utf-8'))
        pdf_texts[book] = {page['pdf_page']: page['text'] for page in raw}
    terms, term_skipped = term_entries(cards, pdf_texts)
    labs, lab_skipped = lab_entries(cards, pdf_texts)
    rules, rule_skipped = rule_entries(cards_by_id, pdf_texts)
    typed = terms + labs + rules
    for prefix, items in (('T', terms), ('L', labs), ('R', rules)):
        counters = Counter(item['source_id'] for item in items)
        seen = Counter()
        for item in items:
            source = item['source_id'].split('-')[-1]
            seen[source] += 1
            item['id'] = f'TB-{prefix}-{source}-{seen[source]:04d}'
    for entry in typed:
        validate_entry(entry)
    typed_ids = {entry['id'] for entry in typed}
    if len(typed_ids) != len(typed):
        raise ValueError('duplicate typed entry id')
    out.mkdir(parents=True)
    typed_path = out / 'typed.jsonl'
    typed_path.write_text(''.join(json.dumps(entry, ensure_ascii=False) + '\n' for entry in typed), encoding='utf-8')
    (out / 'entries.jsonl').write_text(
        ''.join(json.dumps(entry, ensure_ascii=False) + '\n' for entry in cards + typed), encoding='utf-8')
    source_outline = cards_path.with_name('outline.json')
    if source_outline.exists():
        (out / 'outline.json').write_text(source_outline.read_text('utf-8'), encoding='utf-8')
    typed_books = []
    for book in sorted({entry['book'] for entry in typed}):
        book_entries = [entry for entry in typed if entry['book'] == book]
        typed_books.append(outline_for(book, book_entries[0]['source_id'], book_entries))
    (out / 'typed_outline.json').write_text(json.dumps(
        {'schema': 1, 'kind': 'textbook-typed-outline', 'books': typed_books}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    pdf_sources = []
    if pdf_manifest and Path(pdf_manifest).exists():
        manifest = json.loads(Path(pdf_manifest).read_text('utf-8'))
        for item in manifest.get('sources', []):
            pdf_sources.append({'book': item['book'], 'pdf_name': Path(item['path']).name,
                                'pdf_sha256': item['sha256'], 'pdf_pages': item['pdf_pages']})
    audit = {
        'pdf_extractor': 'scripts/pdf_text.swift (PDFKit page.string)',
        'pdf_audit_files': [{'book': book, 'file': filename, 'sha256': digest_file(audit_dir / filename),
                             'pages': len(pdf_texts[book])} for book, filename in PDF_AUDIT_FILES.items()],
        'pdf_sources': pdf_sources,
        'terms': {'candidates': len(terms) + len(term_skipped), 'matched': len(terms), 'skipped': term_skipped},
        'labs': {'candidates': len(labs) + len(lab_skipped), 'matched': len(labs), 'skipped': lab_skipped},
        'rules': {'candidates': len(rules) + len(rule_skipped), 'matched': len(rules), 'skipped': rule_skipped},
    }
    (out / 'typed_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    counts = Counter(entry['type'] for entry in typed)
    manifest = {
        'schema': 1, 'kind': 'textbook-typed-knowledge-store', 'state': 'draft',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'source_cards_sha256': digest_file(cards_path),
        'typed_sha256': digest_file(typed_path),
        'counts': {'cards': len(cards), 'term': counts['term'], 'lab': counts['lab'], 'rule': counts['rule'],
                   'typed_total': len(typed), 'total': len(cards) + len(typed)},
        'by_book': dict(Counter(entry['book'] for entry in typed)),
        'validation': {'validate_entry': 'passed', 'duplicate_ids': 0, 'approved': 0, 'draft': len(cards) + len(typed)},
        'typed_audit_sha256': digest_file(out / 'typed_audit.json'),
        'rights': 'not granted; drafts only; local research, not a release',
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'typed': str(typed_path), 'counts': manifest['counts']}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cards', required=True)
    parser.add_argument('--pdf-audit', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--pdf-manifest')
    args = parser.parse_args()
    typed_store(args.cards, args.pdf_audit, args.out, args.pdf_manifest)


if __name__ == '__main__':
    main()
