"""Development-only textbook RAG for evaluation runs.

The index is a local research artifact: entries are draft, licenses are pending
and no clinical review has signed off. Retrieved passages are injected as prompt
context only; this is not a knowledge release and must not be distributed.
"""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path

from medtrace.knowledge import KnowledgeError, adult_documented, alias_hit, digest_file, search_tokens
from medtrace.retrieval import candidates, case_query, expand_findings, lexical_tokens, prepare_query, select_cards
from medtrace.pipeline import Pipeline
from medtrace.ranking_profile import load_anchor_weights

# Procedural/normal-finding pages crowd out disease knowledge in BM25 rankings.
_SKIP_TITLE = ("体格检查", "病历书写", "问诊", "检查方法", "基本项目", "绪论")


class TextbookIndex:
    def __init__(self, path, profile=None):
        self.path = Path(path).resolve()
        self.anchor_weights = load_anchor_weights(profile) if profile else None
        self.profile_sha256 = digest_file(profile) if profile else None
        if not self.path.is_file():
            raise KnowledgeError(f"textbook index not found: {self.path}")
        self.sha256 = digest_file(self.path)
        manifest_path = self.path.with_suffix(".manifest.json")
        if not manifest_path.is_file():
            manifest_path = self.path.with_name("index.manifest.json")
        self.manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.is_file() else {}
        with closing(self.connect()) as db:
            db.execute("SELECT count(*) FROM search").fetchone()
            guide_rows = db.execute("SELECT body FROM entries WHERE book = '' ORDER BY id")
            self.guidelines = [json.loads(body) for body, in guide_rows]

    def connect(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def describe(self):
        return {"path": str(self.path), "sha256": self.sha256, "profile_sha256": self.profile_sha256,
                "state": self.manifest.get("state", "unknown"), "release": self.manifest.get("release", False),
                "counts": self.manifest.get("counts", {}),
                "redistribution": self.manifest.get("redistribution", "unknown")}

    def retrieve(self, query, limit=5, max_chars=2500, max_card_chars=800, *, categories=None):
        clauses, original = prepare_query(query)
        clauses = expand_findings(clauses)
        tokens = lexical_tokens(clauses, search_tokens)
        with closing(self.connect()) as db:
            rows = candidates(db, tokens, maximum=max(160, limit * 12))
            priority = [(clause, weight) for clause, weight in clauses if weight >= 1.3]
            by_id = {entry["id"]: (entry, score) for entry, score in rows}
            for entry, score in candidates(db, lexical_tokens(priority, search_tokens), maximum=60):
                by_id.setdefault(entry["id"], (entry, score))
            # A long note can exhaust the FTS token and candidate budgets before a specific
            # guideline is considered. Exact anchors still have to pass shared reranking.
            for entry in self.guidelines:
                by_id.setdefault(entry["id"], (entry, 0.0))
            rows = list(by_id.values())
        eligible = [(e, score) for e, score in rows
                    if e["type"] == "card" and len(e["text"]) <= max_card_chars
                    and not any(s in e["title"] for s in _SKIP_TITLE)]
        return select_cards(eligible, clauses, original, alias_hit=alias_hit, adult_documented=adult_documented,
                            search_tokens=search_tokens, categories=categories, limit=limit,
                            max_chars=max_chars, textbook=True, anchor_weights=self.anchor_weights)


class TextbookRagPipeline(Pipeline):
    """A1/A2/S2/A3 with unapproved textbook passages injected as knowledge context."""

    def __init__(self, cfg, client, index):
        super().__init__(cfg, client)
        self.textbook = index

    def _generate_and_verify(self, case, L, variant, lang, stats, deadline, changes, log):
        if variant != "A0":
            audit = {"status": "ok", "index": self.textbook.describe(), "retrieved": []}
            log["textbook_rag"] = audit
            try:
                cards = self.textbook.retrieve(case_query(L))
                L.knowledge_cards = {c["id"]: c for c in cards}
                audit["status"] = "ok" if cards else "no_hits"
                audit["retrieved"] = [{"id": c["id"], "title": c["title"], "book": c.get("book"),
                                       "locator": c["locator"], "source_id": c.get("source_id"),
                                       "version": c["version"], "categories": c.get("categories", []),
                                       "score": c["score"]} for c in cards]
            except Exception as e:
                L.knowledge_cards = {}
                audit.update(status="degraded", error=str(e))
        return super()._generate_and_verify(case, L, variant, lang, stats, deadline, changes, log)