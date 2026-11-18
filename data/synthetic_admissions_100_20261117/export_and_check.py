"""Export the authored synthetic cases and check the input contract without model calls."""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
text = (BASE / '入院资料100例.md').read_text(encoding='utf-8')
blocks = re.split(r'^## (SYN\d{3})｜([^\n]+)\n', text, flags=re.M)
assert len(blocks) == 301, 'Expected exactly 100 case sections'
cases = []
index = []
for i in range(1, len(blocks), 3):
    case_id, title, body = blocks[i:i + 3]
    lines = [line for line in body.splitlines() if line.strip()]
    assert len(lines) == 4, (case_id, 'Expected four sources')
    sources = []
    for j, line in enumerate(lines, 1):
        prefix = f'S{j:02d}：'
        assert line.startswith(prefix), (case_id, prefix)
        content = line[len(prefix):].strip()
        assert content and len(content) >= 20, (case_id, 'Empty or short source')
        sources.append({'source_id': f'S{j:02d}', 'content': content})
    cases.append({'case_id': case_id, 'record_cutoff': 'T0', 'sources': sources})
    index.append({'case_id': case_id, 'topic': title})

assert [case['case_id'] for case in cases] == [f'SYN{i:03d}' for i in range(1, 101)]
assert len({tuple(s['content'] for s in c['sources']) for c in cases}) == 100
assert len({s['content'] for c in cases for s in c['sources']}) == 400
for case in cases:
    assert set(case) == {'case_id', 'record_cutoff', 'sources'}
    assert {s['source_id'] for s in case['sources']} == {'S01', 'S02', 'S03', 'S04'}
    assert all(set(s) == {'source_id', 'content'} for s in case['sources'])

sys.path.insert(0, str(REPO))
from medtrace.inputs import load_cases, parse_case
parsed = [parse_case(case, i) for i, case in enumerate(cases)]
assert all(case.usable and not case.errors and not case.warnings for case in parsed), [
    (c.case_id, c.errors, c.warnings) for c in parsed if c.errors or c.warnings
]
assert all(case.lang == 'zh' and len(case.sources) == 4 for case in parsed)

output = BASE / 'input_100_final.json'
with output.open('x', encoding='utf-8') as f:
    json.dump(cases, f, ensure_ascii=False, indent=2)
    f.write('\n')
loaded, envelope = load_cases(str(output))
assert envelope == 'list' and len(loaded) == 100
assert all(case.usable and not case.errors and not case.warnings for case in loaded)
assert json.loads(output.read_text(encoding='utf-8')) == cases
counts = Counter(item['topic'].split('：')[0] for item in index)
report = {
    'synthetic': True,
    'clinician_reviewed': False,
    'case_count': len(cases),
    'source_count': sum(len(c['sources']) for c in cases),
    'case_ids': 'SYN001-SYN100',
    'record_cutoff': 'T0',
    'schema_check': 'passed',
    'duplicate_case_ids': 0,
    'duplicate_full_cases': 0,
    'duplicate_source_contents': 0,
    'medtrace_load_cases': '100 usable cases, zero errors, zero warnings',
    'medtrace_warning': None,
    'cutoff_note': 'T0 is permitted by the PDF input specification. All supplied facts are authored as available by T0; this dataset does not test automatic date filtering.',
    'model_called': False,
    'topic_counts': dict(counts),
    'input_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
}
with (BASE / 'validation.json').open('x', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
    f.write('\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
