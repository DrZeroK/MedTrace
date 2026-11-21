"""Shared offline ranking for approved knowledge and development-only indexes."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping

from . import context, textutil as T

CATEGORIES = {"diagnosis", "differential", "tests", "treatment"}
FIELDS = {"history": 1.0, "symptoms": 1.25, "labs": 1.2, "exams": 1.15, "other": 1.0}
CLAUSE = re.compile(r"[，,。；;！？!?\n]")
GENERIC_ALIASES = {"诊断", "鉴别诊断", "治疗", "检查", "评估", "慢性", "急性", "轻度", "中度", "重度"}
GENERIC_PATTERN = re.compile(r"鉴别诊断|辅助检查|实验室检查|治疗原则|诊断标准|临床表现|评估")
NONPREGNANT = re.compile(r"成年男性|成人男性|非妊娠|未妊娠|未怀孕|未孕")


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
            for span in context.analyze(value):
                if span.value in {"negated", "missing", "family", "hypothetical"}:
                    masked[span.start:span.end] = " " * (span.end - span.start)
            for clause in CLAUSE.split("".join(masked)):
                if clause.strip():
                    clauses.append((clause, FIELDS[field]))
    return clauses, "\n".join(originals)


def case_query(ledger):
    query = {}
    for fact in ledger.facts:
        field = {"complaint": "symptoms", "history": "history", "exam": "exams",
                 "imaging": "exams", "lab": "labs"}.get(fact.category, "other")
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
    if population == "pregnancy":
        return not NONPREGNANT.search(original)
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
                if len(alias.strip()) < 2 or alias in GENERIC_ALIASES or any(alias in term for term in matched):
                    continue
                weight = max((weight for clause, weight in clauses if alias_hit(alias, clause)), default=0)
                if weight:
                    matched.append(alias)
                    score += weight * (1 + min(len(alias), 8) / 8)
            title = text_trigrams(item["title"])
            body = text_trigrams(item["text"])
            context_score = max((weight * (len(grams & title) * 2 + len(grams & body))
                                 for grams, weight in fingerprints), default=0)
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
