"""Structure filtered textbook text into draft knowledge cards and build a local card index.

Cards follow the same entry schema as knowledge/entries.jsonl; nothing is approved or releasable.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from medtrace import textutil as T
from medtrace.knowledge import index_card, search_tokens, validate_entry
from scripts.textbook_search import digest_file, load_corpus

PART = re.compile(r'^(第[一二三四五六七八九十百]+篇)[\s　]*(.*)$')
CHAP = re.compile(r'^(第[一二三四五六七八九十百]+章)[\s　]*(.*)$')
SECT = re.compile(r'^(第[一二三四五六七八九十百]+节)[\s　|｜]*(.*)$')
SUBS = re.compile(r'^【(.{1,30})】$')
TOPIC = re.compile(r'^([一二三四五六七八九十]+)、[\s　]*(.*)$')
SUBTOPIC = re.compile(r'^（\s*([一二三四五六七八九十]+)\s*）[\s　]*(.*)$')
STRUCT_LINES = {'本篇思维导图', '本章思维导图', '本节思维导图'}
AUTHOR_LINE = re.compile(r'^（[\u4e00-\u9fff·\s]{1,20}）$')
NUMBERED_HEADING = re.compile(r'^\d+[.．、][\s　]+\S{1,30}$')
GENERIC = {
    '病因', '病因与发病机制', '病因和发病机制', '临床表现', '诊断', '诊断与鉴别诊断',
    '鉴别诊断', '治疗', '治疗原则', '预防', '预后', '并发症', '检查', '实验室检查',
    '实验室和其他检查', '实验室和其他辅助检查', '辅助检查', '概述', '总论', '护理',
    '康复', '随访', '随诊', '处理', '方法', '适应证', '禁忌证', '注意事项', '操作前准备',
    '发生机制', '病理', '病理生理', '分类', '分型', '诊断标准', '病情评估', '评估',
    '监测', '健康教育', '参考区间', '临床意义', '标本来源', '参考值',
}
LAB_LABELS = {'参考区间', '临床意义', '标本来源', '参考值', '质量控制', '方法学评价'}
CROSS_REF = re.compile(r'(参见|参照|详见|见)(本篇|本章|本节|第[一二三四五六七八九十百]+[章节]|表)')
SOURCE_MAP = {
    '内科学第10版': {'id': 'PMPH-IM10', 'scope': 'adult'},
    '诊断学第10版': {'id': 'PMPH-DX10', 'scope': 'general'},
    '儿科学第10版': {'id': 'PMPH-PED10', 'scope': 'general', 'population': 'pediatric'},
    '妇产科学第10版': {'id': 'PMPH-OBG10', 'scope': 'general'},
    '外科学第10版': {'id': 'PMPH-SUR10', 'scope': 'general'},
}
REQUESTED_USES = ['offline_index', 'rag_context', 'derived_cards', 'competition_distribution']
MAX_CARD_CHARS = 1800


def norm(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'(?<=[一-鿿])\s+(?=[一-鿿])', '', text)
    text = re.sub(r'\s*([：:｜|])\s*', r'\1', text)
    return text.strip()


def bad_title(text, limit, allow_empty=False):
    if not text:
        return not allow_empty
    return len(text) > limit or bool(re.search(r'[。；！？，]', text)) or text.startswith(('。', '，', '、', '；', '：'))


def heading(line):
    line = line.strip()
    for level, pattern, limit in (('part', PART, 70), ('chapter', CHAP, 70), ('section', SECT, 70)):
        match = pattern.match(line)
        if match:
            title = norm(match.group(2))
            if bad_title(title, limit, allow_empty=True):
                continue
            return level, norm(match.group(1)), title
    match = SUBS.match(line)
    if match:
        return 'label', '', norm(match.group(1))
    match = TOPIC.match(line)
    if match:
        title = norm(match.group(2))
        if not bad_title(title, 24):
            return 'topic', norm(match.group(1)), title
    match = SUBTOPIC.match(line)
    if match:
        title = norm(match.group(2))
        if not bad_title(title, 30):
            return 'subtopic', norm(match.group(1)), title
    return None


def expand_labels(text):
    text = re.sub(r'^(\s*)(【[^】]{1,30}】)\s*(?=\S)', r'\2\n', text, flags=re.M)
    return re.sub(r'(?<=[。；！？])\s*(【[^】]{1,30}】)\s*', r'\n\1\n', text)


def split_entries(entries):
    chunks, current, size = [], [], 0
    for entry in entries:
        line = entry[0]
        if len(line) > MAX_CARD_CHARS:
            if current:
                chunks.append(current)
                current, size = [], 0
            for start in range(0, len(line), MAX_CARD_CHARS):
                chunks.append([(line[start:start + MAX_CARD_CHARS], entry[1], entry[2], entry[3])])
            continue
        if size and size + len(line) + 1 > MAX_CARD_CHARS:
            chunks.append(current)
            current, size = [], 0
        current.append(entry)
        size += len(line) + 1
    if current:
        chunks.append(current)
    return chunks


def clean_lines(entries, path_titles):
    titles = [re.sub(r'\s+', '', title) for title in path_titles if title]
    lines = []
    for line, page, printed, basis in entries:
        line = re.sub(r'(本篇|本章|本节)思维导图\s*$', '', line).strip()
        if not line or line in STRUCT_LINES or AUTHOR_LINE.fullmatch(line):
            continue
        if len(line) < 40 and any(re.sub(r'\s+', '', line) == title for title in titles):
            continue
        lines.append((line, page, printed, basis))
    while lines and len(lines[0][0]) < 40 and any(re.sub(r'\s+', '', lines[0][0]) in title for title in titles):
        lines.pop(0)
    while lines and len(lines[-1][0]) < 40 and any(re.sub(r'\s+', '', lines[-1][0]) in title for title in titles):
        lines.pop()
    return lines


def should_skip(lines, path_titles):
    if not lines:
        return True
    flats = [re.sub(r'\s+', '', line[0]) for line in lines]
    titles = [re.sub(r'\s+', '', title) for title in path_titles if title]
    if len(''.join(flats)) < 60 and all(any(flat in title for title in titles) for flat in flats):
        return True
    if len(lines) == 1:
        text = lines[0][0]
        if heading(text) or NUMBERED_HEADING.fullmatch(text):
            return True
    text = '\n'.join(line[0] for line in lines)
    if len(text) < 40 and CROSS_REF.search(text):
        return True
    return False


def aliases_for(book, part_title, chapter_title, section_title, topic_title, subtopic_title, text):
    values = []
    for value in (part_title, chapter_title, section_title, topic_title, subtopic_title):
        if value and value not in GENERIC and len(value) >= 2:
            values.append(value)
    for match in re.finditer(r'[（(]([A-Za-z][A-Za-z0-9 ,;/\-&\'.]{1,80})[）)]', text[:600]):
        phrase = match.group(1).strip()
        if 2 <= len(phrase) <= 80:
            values.append(phrase)
        for piece in re.split(r'[,;，；]', phrase):
            piece = piece.strip()
            if 2 <= len(piece) <= 60:
                values.append(piece)
    short = re.sub(r'第\d+版$', '', book)
    out = []
    for value in values:
        if value in (book, short) or value in GENERIC or value in out:
            continue
        out.append(value)
    return out[:8]


def parse_structure(book, pages, source, version, scope, source_id):
    expanded = [(page, printed, basis, expand_labels(text)) for page, printed, basis, text in pages]
    part_titles, chapter_titles, section_titles = {}, {}, {}
    part = chapter = section = None
    for _, _, _, text in expanded:
        for line in text.splitlines():
            item = heading(line)
            if not item:
                continue
            level, number, title = item
            if level == 'part':
                part, chapter, section = number, None, None
                if title:
                    part_titles[number] = max(part_titles.get(number, ''), title, key=len)
            elif level == 'chapter':
                chapter, section = number, None
                key = (part, number)
                if title:
                    chapter_titles[key] = max(chapter_titles.get(key, ''), title, key=len)
            elif level == 'section':
                section = number
                key = (part, chapter, number)
                if title:
                    section_titles[key] = max(section_titles.get(key, ''), title, key=len)

    short = re.sub(r'第\d+版$', '', book)
    cards = []
    part = chapter = section = label = None
    topic = topic_number = subtopic = subtopic_number = None
    buffer = []

    def labels():
        part_title = part_titles.get(part, '')
        chapter_title = chapter_titles.get((part, chapter), '')
        section_title = section_titles.get((part, chapter, section), '')
        return part_title, chapter_title, section_title

    def structure():
        part_title, chapter_title, section_title = labels()
        data = {}
        if part:
            data['part'] = f'{part} {part_title}'.strip()
        if chapter:
            data['chapter'] = f'{chapter} {chapter_title}'.strip()
        if section:
            data['section'] = f'{section} {section_title}'.strip()
        if topic:
            data['topic'] = f'{topic_number}、{topic}'
        if subtopic:
            data['subtopic'] = f'（{subtopic_number}）{subtopic}'
        if label:
            data['label'] = f'【{label}】'
        return data

    def title():
        part_title, chapter_title, section_title = labels()
        sequence = [short]
        for value in (part_title, chapter_title, section_title, topic, subtopic):
            if value and value not in sequence:
                sequence.append(value)
        if len(sequence) == 1:
            sequence.append('概述')
        text = '·'.join(sequence)
        if label:
            text += f'：{label}'
        return norm(text)

    def flush():
        nonlocal buffer
        if not buffer:
            return
        part_title, chapter_title, section_title = labels()
        path = [part_title, chapter_title, section_title, topic, subtopic, label]
        lines = clean_lines(buffer, path)
        buffer = []
        if should_skip(lines, path):
            return
        chunks = split_entries(lines)
        base = title()
        for index, chunk in enumerate(chunks, 1):
            text = '\n'.join(entry[0] for entry in chunk).strip()
            if not text:
                continue
            card_title = base if len(chunks) == 1 else f'{base}（{index}/{len(chunks)}）'
            cards.append({
                'text': text,
                'title': card_title,
                'structure': structure(),
                'aliases': aliases_for(book, part_title, chapter_title, section_title, topic, subtopic, text),
                'page_start': chunk[0][1],
                'page_end': chunk[-1][1],
                'printed_page_start': chunk[0][2],
                'printed_page_end': chunk[-1][2],
                'page_basis': sorted({entry[3] for entry in chunk}),
            })

    for page, printed, basis, text in expanded:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = heading(line)
            if item:
                level, number, item_title = item
                if level == 'part':
                    if number != part:
                        flush()
                        part, chapter, section = number, None, None
                        label = topic = topic_number = subtopic = subtopic_number = None
                elif level == 'chapter':
                    if number != chapter:
                        flush()
                        chapter, section = number, None
                        label = topic = topic_number = subtopic = subtopic_number = None
                elif level == 'section':
                    if number != section:
                        flush()
                        section = number
                        label = topic = topic_number = subtopic = subtopic_number = None
                elif level == 'label':
                    if item_title != label:
                        flush()
                        label = item_title
                        if item_title not in LAB_LABELS:
                            topic = topic_number = subtopic = subtopic_number = None
                elif level == 'topic':
                    if number != topic_number:
                        flush()
                        topic_number, topic = number, item_title
                        if label in LAB_LABELS:
                            label = None
                        subtopic = subtopic_number = None
                else:
                    if number != subtopic_number:
                        flush()
                        subtopic_number, subtopic = number, item_title
                        if label in LAB_LABELS:
                            label = None
                continue
            buffer.append((line, page, printed, basis))
    flush()

    for index, card in enumerate(cards, 1):
        card['id'] = f'TB-{source_id.split("-")[-1]}-{index:04d}'
        card.update({
            'type': 'card',
            'book': book,
            'source': source,
            'version': version,
            'locator': locator(card),
            'license': 'pending',
            'status': 'draft',
            'scope': scope,
            'reviewer': '',
            'reviewed_at': '',
            'permission_review': {
                'status': 'not_granted', 'reviewer': '', 'reviewed_at': '', 'evidence': [],
                'requested_uses': REQUESTED_USES, 'request_status': 'not_sent',
            },
            'clinical_review': {
                'status': 'not_signed', 'reviewer': '', 'reviewed_at': '', 'evidence': [],
                'pre_review_by': 'Codex AI (not a clinician signature)',
                'pre_reviewed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'pre_review_status': 'textbook_structure_extracted_only',
                'notes': '仅按教材标题层级和正文切分为结构化草稿卡；未做临床内容复核、未核对指南差异，不能用于发布。',
            },
            'candidate_source_ids': [source_id],
            'source_id': source_id,
            'source_note': '官方目录元数据；正文来自用户提供的第10版电子版，未取得再分发许可。',
            'clinical_scope_notes': '教材内容范围待临床审核；scope 为初步设定。',
        })
    return cards


def locator(card):
    start = card['printed_page_start']
    end = card['printed_page_end']
    page_start = card['page_start']
    page_end = card['page_end']
    basis = '/'.join('页眉' if value == 'header' else '推算' for value in card['page_basis'])
    text_pages = f'文本页 {page_start}' if page_start == page_end else f'文本页 {page_start}–{page_end}'
    if start is None or end is None:
        return text_pages
    page_label = f'第{start}页' if start == end else f'第{start}–{end}页'
    return f'{page_label}（{text_pages}；页码依据：{basis}）'


def outline_for(book, source_id, cards):
    root = {'book': book, 'source_id': source_id, 'cards': [], 'children': []}
    levels = ('part', 'chapter', 'section', 'topic', 'subtopic', 'label')
    for card in cards:
        node = root
        for level in levels:
            label = card['structure'].get(level)
            if not label:
                continue
            child = next((item for item in node['children'] if item['level'] == level and item['label'] == label), None)
            if child is None:
                child = {'level': level, 'label': label, 'cards': [], 'children': []}
                node['children'].append(child)
            node = child
        node['cards'].append(card['id'])
    return root


def structure_corpus(corpus_dir, out_dir, *, selected_books=None):
    books, manifest_path = load_corpus(corpus_dir, selected_books=selected_books)
    sources = {item['id']: item for item in json.loads((ROOT / 'knowledge' / 'sources.json').read_text('utf-8'))}
    dest = Path(out_dir)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('use a new absolute output directory')
    dest.mkdir(parents=True)
    all_cards, outline_books = [], []
    source_entries = []
    for book, pages, item in books:
        mapping = SOURCE_MAP.get(book)
        if not mapping:
            raise ValueError(f'no source mapping for {book}')
        source_info = sources.get(mapping['id'])
        if not source_info:
            raise ValueError(f'missing source metadata: {mapping["id"]}')
        cards = parse_structure(book, pages, source_info['source'], source_info.get('version_candidate', ''),
                                mapping['scope'], mapping['id'])
        for card in cards:
            card['source_url'] = source_info['source']
            card['isbn'] = source_info.get('isbn')
            if 'population' in mapping:
                card['population'] = mapping['population']
        all_cards.extend(cards)
        outline_books.append(outline_for(book, mapping['id'], cards))
        source_entries.append({'source_id': mapping['id'], 'book': book, 'text_file': item['text_file'],
                               'text_sha256': item['sha256'], 'pages': len(pages), 'cards': len(cards)})
    seen = set()
    for card in all_cards:
        validate_entry(card)
        if card['id'] in seen:
            raise ValueError(f'duplicate card id: {card["id"]}')
        seen.add(card['id'])
        if len(card['text']) > MAX_CARD_CHARS:
            raise ValueError(f'card too long: {card["id"]}')
    entries_path = dest / 'entries.jsonl'
    entries_path.write_text(''.join(json.dumps(card, ensure_ascii=False) + '\n' for card in all_cards),
                            encoding='utf-8')
    outline = {'schema': 1, 'kind': 'textbook-knowledge-outline', 'books': outline_books,
               'counts': {item['book']: item['cards'] for item in source_entries}}
    (dest / 'outline.json').write_text(json.dumps(outline, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {
        'schema': 1, 'kind': 'textbook-knowledge-cards', 'state': 'draft',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'source_corpus_manifest_sha256': digest_file(manifest_path),
        'entries_sha256': digest_file(entries_path), 'entries_bytes': entries_path.stat().st_size,
        'sources': source_entries,
        'counts': {'cards': len(all_cards), 'by_book': {item['book']: item['cards'] for item in source_entries},
                   'approved': 0, 'draft': len(all_cards)},
        'validation': {'validate_entry': 'passed', 'duplicate_ids': 0},
        'rights': 'not granted; drafts only; local research, not a release',
        'structure': {
            'levels': ['part', 'chapter', 'section', 'topic', 'subtopic', 'label'],
            'max_card_chars': MAX_CARD_CHARS,
            'split_suffix': '（1/N）…（N/N）',
        },
    }
    (dest / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'entries': str(entries_path), 'cards': len(all_cards),
                      'by_book': manifest['counts']['by_book']}, ensure_ascii=False))


def clinical_categories(card):
    structure = card.get("structure") or {}
    label = " ".join(structure.get(key, "") for key in ("label", "subtopic"))
    tags = []
    if "鉴别" in label:
        tags.append("differential")
    if "诊断" in label and ("鉴别" not in label or re.search(r"诊断[与和及]鉴别", label)):
        tags.append("diagnosis")
    if re.search(r"检查|参考区间|临床意义|标本|心电图特征", label):
        tags.append("tests")
    if re.search(r"治疗|管理|防治|用药|随访", label):
        tags.append("treatment")
    return tags


def pack_sentences(text, max_chars=760):
    """Do not cut decimals, units or OCR lines without a usable sentence boundary."""
    group = []
    size = 0
    for sentence in T.split_sentences(text):
        if group and size + 1 + len(sentence) > max_chars:
            yield "\n".join(group)
            group, size = [], 0
        size += len(sentence) + bool(group)
        group.append(sentence)
    if group:
        yield "\n".join(group)


def organize_drafts(entries_path, output):
    """Derive a local-only, page-traceable index input from existing textbook cards."""
    if output.exists():
        raise ValueError("use a new output path")
    rows, ids = [], set()
    with entries_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            card = json.loads(line)
            validate_entry(card)
            if card["status"] != "draft":
                raise ValueError("expected textbook drafts")
            if card["type"] != "card":
                continue
            categories = clinical_categories(card)
            for text in pack_sentences(card["text"]):
                digest = hashlib.sha256(text.encode()).hexdigest()[:12]
                evidence_id = f"{card['id']}-{digest}"
                if evidence_id in ids:
                    continue
                ids.add(evidence_id)
                rows.append({**card, "id": evidence_id, "parent_id": card["id"], "categories": categories,
                             "text": text})
    if not rows:
        raise ValueError("no textbook cards")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "chunks": len(rows), "parent_cards": len({row["parent_id"] for row in rows}),
        "categories": dict(sorted(Counter(category for row in rows for category in row["categories"]).items())),
        "unclassified": sum(not row["categories"] for row in rows),
        "status": "draft", "entries_sha256": digest_file(output),
    }


def build_index(entries_path, db_path, supplements=()):
    entries_path = Path(entries_path)
    if not entries_path.is_absolute():
        raise ValueError('entries path must be absolute')
    dest = Path(db_path)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('use a new absolute database path')
    sources = [entries_path, *map(Path, supplements)]
    entries = [json.loads(line) for source in sources
               for line in source.read_text('utf-8').splitlines() if line.strip()]
    seen = set()
    for entry in entries:
        validate_entry(entry)
        if entry['status'] != 'draft':
            raise ValueError(f'card index only accepts drafts: {entry["id"]}')
        if entry['id'] in seen:
            raise ValueError(f'duplicate entry id: {entry["id"]}')
        seen.add(entry['id'])
    dest.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(dest)
    try:
        db.execute('PRAGMA journal_mode=MEMORY')
        db.execute('CREATE TABLE meta(body TEXT)')
        db.execute('CREATE TABLE entries(id TEXT PRIMARY KEY,book TEXT,source_id TEXT,body TEXT NOT NULL)')
        db.execute('CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,title,body)')
        for entry in entries:
            db.execute('INSERT INTO entries VALUES(?,?,?,?)',
                       (entry['id'], entry.get('book', ''), entry.get('source_id', ''),
                        json.dumps(entry, ensure_ascii=False)))
            index_card(db, entry)
        manifest = {
            'schema': 1, 'kind': 'textbook-knowledge-index', 'state': 'draft', 'release': False,
            'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'entries_sha256': digest_file(entries_path), 'entries_bytes': entries_path.stat().st_size,
            'supplements': [{'name': source.name, 'sha256': digest_file(source), 'bytes': source.stat().st_size}
                            for source in sources[1:]],
            'counts': dict(Counter(entry.get('book', 'unknown') for entry in entries)),
            'by_type': dict(Counter(entry['type'] for entry in entries)),
            'dependencies': ['Python >=3.10', 'SQLite FTS5'],
            'redistribution': 'not established; local research index; drafts only',
        }
        db.execute('INSERT INTO meta VALUES(?)', (json.dumps(manifest, ensure_ascii=False),))
        db.commit()
    finally:
        db.close()
    dest.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                                  encoding='utf-8')
    print(json.dumps({'database': str(dest), 'entries': len(entries), 'release': False}, ensure_ascii=False))


def search_cards(db_path, query, limit=5, book=None):
    if not query.strip() or not 1 <= limit <= 50:
        raise ValueError('query required; limit must be 1–50')
    db = sqlite3.connect(Path(db_path).as_uri() + '?mode=ro', uri=True)
    try:
        tokens = sorted(set(search_tokens(query)))[:100]
        params = []
        if tokens:
            sql = ('SELECT e.body,bm25(search,0,5,1) AS score FROM search JOIN entries e ON e.id=search.id '
                   'WHERE search MATCH ?')
            params.append(' AND '.join('"' + token + '"' for token in tokens))
        else:
            sql = 'SELECT e.body,0 AS score FROM entries e WHERE instr(e.body,?)>0'
            params.append(query)
        if book:
            sql += ' AND e.book=?'
            params.append(book)
        rows = db.execute(sql + ' ORDER BY score,e.id', params).fetchall()
        token_set = set(tokens)
        ranked = []
        for body, score in rows[:max(limit * 5, 20)]:
            item = json.loads(body)
            item['score'] = score
            title_tokens = set(search_tokens(item['title'] + ' ' + ' '.join(item.get('aliases', []))))
            type_rank = 0 if item['type'] in ('term', 'lab', 'rule') else 1
            ranked.append((-len(token_set & title_tokens), type_rank, len(item['title']), score, item['id'], item))
        ranked.sort(key=lambda row: row[:5])
        return [row[5] for row in ranked[:limit]]
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    organize = sub.add_parser('organize', help='rechunk and tag existing local textbook drafts')
    organize.add_argument('--entries', type=Path, required=True)
    organize.add_argument('--output', type=Path, required=True)
    s = sub.add_parser('structure', help='convert filtered plain text into draft knowledge cards')
    s.add_argument('--corpus', required=True)
    s.add_argument('--book', action='append', help='only structure named books from this corpus')
    s.add_argument('--out', required=True)
    b = sub.add_parser('build', help='build a local draft knowledge index')
    b.add_argument('--supplement', type=Path, action='append', default=[])
    b.add_argument('--entries', required=True)
    b.add_argument('--db', required=True)
    q = sub.add_parser('search')
    q.add_argument('--db', required=True)
    q.add_argument('--query', required=True)
    q.add_argument('--limit', type=int, default=5)
    q.add_argument('--book')
    args = parser.parse_args()
    if args.command == 'organize':
        print(json.dumps(organize_drafts(args.entries, args.output), ensure_ascii=False))
        return
    if args.command == 'structure':
        structure_corpus(args.corpus, args.out, selected_books=args.book)
    elif args.command == 'build':
        build_index(args.entries, args.db, args.supplement)
    else:
        print(json.dumps(search_cards(args.db, args.query, args.limit, args.book), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
