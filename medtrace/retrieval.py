"""Shared offline ranking for approved knowledge and development-only indexes."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping

from . import context, textutil as T

CATEGORIES = {"diagnosis", "differential", "tests", "treatment"}
POPULATIONS = {"general", "adult", "pediatric", "pregnancy", "nonpregnant", "nonpregnant_adult"}
FIELDS = {"chief": 1.65, "pathology": 1.65, "history": 1.0, "symptoms": 1.25, "labs": 1.2, "exams": 1.15, "other": 1.0}
CLAUSE = re.compile(r"[，,。；;！？!?\n]")
GENERIC_ALIASES = {"诊断", "鉴别诊断", "治疗", "检查", "评估", "慢性", "急性", "轻度", "中度", "重度", "病史", "一般情况", "知识要点"}
GENERIC_PATTERN = re.compile(r"鉴别诊断|辅助检查|实验室检查|治疗原则|诊断标准|临床表现|评估")
PEDIATRIC = re.compile(r"儿童|患儿|新生儿|婴幼儿|婴儿|(?<![\d.])(?:[1-9]|1[0-7])\s*岁")
PREGNANCY = re.compile(r"怀孕|妊娠(?:期|中|早期|晚期)|孕(?:妇|期|早期|晚期|\s*[0-9]+\s*周)")
NONPREGNANT = re.compile(r"成年男性|成人男性|非妊娠|未妊娠|未怀孕|未孕")
# The patient's own sex; a partner ("男方", "男性伴侣") does not count.
MALE = re.compile(r"性别\s*[：:]\s*男|男(?:性|患|士|[，,、\s\d])(?!伴侣|配偶)")


def prepare_query(query):
    fields = query if isinstance(query, Mapping) else {"other": query}
    clauses, originals = [], []
    for field, values in fields.items():
        if field not in FIELDS:
            raise ValueError(f"unknown evidence query field: {field}")
        values = (values,) if isinstance(values, str) else values
        for value in values:
            value = T.fw(value).lower()
            originals.append(value)
            masked = list(value)
            scopes = context.analyze(value)
            # Resolve overlapping scopes by the context module's precedence: "不能排除哮喘" stays uncertain.
            for i in {i for span in scopes for i in range(span.start, span.end)}:
                state = context.attributes(value, i, i + 1, scopes)
                if (state["assertion"] in {"negated", "missing"} or state["experiencer"] == "family"
                        or state["temporality"] == "hypothetical"):
                    masked[i] = " "
            for clause in CLAUSE.split("".join(masked)):
                if clause.strip():
                    clauses.append((clause, FIELDS[field]))
    return clauses, "\n".join(originals)


# These query-only synonyms describe findings. The fact ledger keeps the original wording.
_FINDING_VARIANTS = (
    (re.compile(r"咳嗽[、伴]咳痰(?:持续|了)?(?:[2-9]|[两二三四五六七八九十])个?月"
                r"|长期干咳|慢性干咳"
                r"|干咳(?:持续|了)?(?:数|几|[2-9]|[二三四五六七八九十](?:[一二三四五六七八九十])?)个?月"),
     "慢性咳嗽"),
    (re.compile(r"气道可逆|气流受限(?:有|具有)?可逆性|用支气管扩张剂后气流明显改善"), "气流受限"),
    (re.compile(r"腹腔(?:的)?(?:少量|中量|大量)?(?:游离液(?:体)?|液性暗区|有积液)"), "腹腔积液"),
)
_SPEECH = re.compile(r"说不出话|说不出完整句子|话说不出来|讲不出话|不能言语|吐字不清|口齿不清")
_LATERAL_NUMBNESS = re.compile(r"(?:左侧|右侧|单侧|一侧|偏侧|半身)(?:肢体|上肢|下肢|手臂)?(?:的)?麻木")
_RELIEVED = re.compile(r"缓解|消退|恢复|每次持续(?:约)?(?:数十|几|[一二三四五]|[1-5])(?:秒|分钟)")
_CHIEF = re.compile(r"^主\s*诉\s*[：:]")
_PATHOLOGY_RESULT = re.compile(r"病理(?:检查)?(?:提示|报告|结果|示|[：:])|活检(?:提示|示|见)")
_ACUTE = re.compile(r"突然|突发|骤然|一下子|一过性")
_RECOVERED_SPEECH = re.compile(r"恢复(?:语言|言语|说话|如常|正常)|重新(?:能)?说话|又能(?:讲|说)话|完全缓解")
_BREATH_LIMITED_SPEECH = re.compile(r"喘得|喘到|气喘|气短|喘不上气|呼吸困难|憋得")


def expand_findings(clauses):
    """Add lower-weight search terms to already scoped patient findings."""
    expansions = {}
    positive = " ".join(clause for clause, _ in clauses)
    chief_numbness = max((weight for clause, weight in clauses
                          if weight == FIELDS["chief"] and _LATERAL_NUMBNESS.search(clause)), default=0.0)
    for position, (clause, weight) in enumerate(clauses):
        for pattern, term in _FINDING_VARIANTS:
            if pattern.search(clause) and term not in positive:
                expansions[term] = max(expansions.get(term, 0.0), 0.8 * weight)
        nearby = " ".join(part for part, _ in clauses[position:position + 3])
        if _LATERAL_NUMBNESS.search(clause) and _ACUTE.search(clause) and _RELIEVED.search(nearby):
            term = "一过性偏侧麻木"
            expansions[term] = max(expansions.get(term, 0.0), 0.8 * max(weight, chief_numbness))
        if (_SPEECH.search(clause) and not _BREATH_LIMITED_SPEECH.search(clause)
                and _ACUTE.search(clause) and _RECOVERED_SPEECH.search(nearby)):
            term = "短暂失语" if not re.search(r"吐字不清|口齿不清", clause) else "短暂言语不清"
            expansions[term] = max(expansions.get(term, 0.0), 0.8 * weight)
    return [*clauses, *expansions.items()]


def case_query(ledger):
    query = {}
    for fact in ledger.facts:
        field = {"history": "history", "exam": "exams",
                 "imaging": "exams", "lab": "labs"}.get(fact.category, "other")
        if fact.category == "complaint" or _CHIEF.match(fact.text):
            field = "chief"
        elif _PATHOLOGY_RESULT.search(fact.text):
            field = "pathology"
        query.setdefault(field, []).append(fact.text)
    return query


def lexical_tokens(clauses, search_tokens):
    tokens = {}
    for clause, weight in clauses:
        for token in search_tokens(clause):
            tokens[token] = max(tokens.get(token, 0), weight)
    # Deprioritize bare numbers when the FTS query budget is exhausted.
    return sorted(tokens, key=lambda term: (-tokens[term], term[0].isdigit(), -len(term), term))[:512]


def candidates(db, tokens, maximum=None):
    if not tokens:
        return []
    statement = ("SELECT entries.body,bm25(search,0,5,1) FROM search JOIN entries "
                 "ON entries.id=search.id WHERE search MATCH ? ORDER BY 2,search.id")
    params = [" OR ".join('"' + term + '"' for term in tokens)]
    if maximum is not None:
        statement += " LIMIT ?"
        params.append(maximum)
    return [(json.loads(body), score) for body, score in db.execute(statement, params)]


def text_trigrams(text):
    return {run[i:i + 3] for run in re.findall(r"[一-鿿]+", GENERIC_PATTERN.sub(" ", text))
            for i in range(len(run) - 2)}


def _scope_matches(item, original, positive, adult_documented):
    if item["scope"] == "adult" and not adult_documented(positive):
        return False
    population = item.get("population")
    if population in {"adult", "nonpregnant_adult"} and PEDIATRIC.search(positive):
        return False
    if population in {"nonpregnant", "nonpregnant_adult"}:
        return bool(NONPREGNANT.search(positive)) or not PREGNANCY.search(positive)
    if population == "pregnancy":
        return not (NONPREGNANT.search(original) or MALE.search(positive))
    if population == "pediatric":
        return not (adult_documented(positive) or re.search(r"成人|成年(?:男|女|人|患者)", positive))
    return True


def select_cards(rows, clauses, original, *, alias_hit, adult_documented, search_tokens,
                 categories=None, limit=5, max_chars=2500, baseline=False, textbook=False):
    """Return complete passages; the original case and entry objects remain intact."""
    wanted = None if categories is None else set(categories)
    if wanted is not None and not wanted <= CATEGORIES:
        raise ValueError("unknown evidence category")
    positive = " ".join(clause for clause, _ in clauses)
    fingerprints = [(text_trigrams(clause), weight) for clause, weight in clauses]
    ranked = []
    for order, (item, lexical) in enumerate(rows):
        if wanted is not None and not wanted.intersection(item.get("categories", ())):
            continue
        if not baseline and not _scope_matches(item, original, positive, adult_documented):
            continue
        matched = []
        score = 0.0
        if not baseline:
            aliases = sorted(set([item["title"], *item.get("aliases", [])]), key=lambda a: (-len(a), a))
            for alias in aliases:
                if (len(alias.strip()) < 2 or alias in GENERIC_ALIASES or T.is_measurement_only(alias)
                        or any(alias in term for term in matched)):
                    continue
                weight = max((weight for clause, weight in clauses if alias_hit(alias, clause)), default=0)
                if weight:
                    matched.append(alias)
                    score += weight * (1 + min(len(alias), 8) / 8)
            title = text_trigrams(item["title"])
            body = text_trigrams(item["text"])
            matches = [(weight, grams & title, grams & body) for grams, weight in fingerprints]
            context_score = max((weight * (len(title_hits) * 2 + len(body_hits))
                                 for weight, title_hits, body_hits in matches), default=0)
            if textbook and item.get("book"):
                # Accept several distinct findings spread across the same query.
                shared = set().union(*(title_hits | body_hits for _, title_hits, body_hits in matches))
                context_score = max(context_score, len(shared))
            if not matched and not (textbook and item.get("book") and context_score >= 5):
                continue
            score = 2.5 * score + 0.35 * min(context_score, 8) + 0.2 * math.log1p(abs(lexical))
        ranked.append((-score, order, item, lexical, matched))

    output, seen, chapters, parents = [], {}, {}, set()
    size = 0
    for score, _, item, lexical, matched in sorted(ranked):
        if size + len(item["text"]) > max_chars:
            continue
        from_book = textbook and item.get("book")
        if from_book:
            structure = item.get("structure") or {}
            chapter = (item.get("source_id", item["source"]), structure.get("part"), structure.get("chapter"))
            parent = item.get("parent_id", item["id"])
            if parent in parents or chapters.get(chapter, 0) >= 2:
                continue
        if not baseline:
            group = item.get("source_id", item["source"]), tuple(item.get("categories", ()))
            signature = set(search_tokens(item["text"]))
            previous = seen.setdefault(group, [])
            if signature and any(len(signature & other) >= 0.82 * len(signature | other) for other in previous):
                continue
            previous.append(signature)
        output.append({**item, "source_id": item.get("source_id", item["source"]),
                       "score": lexical if baseline else round(-score, 6), "matched_terms": matched})
        size += len(item["text"])
        if from_book:
            chapters[chapter] = chapters.get(chapter, 0) + 1
            parents.add(parent)
        if len(output) >= limit:
            break
    return output
