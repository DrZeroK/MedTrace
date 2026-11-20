"""Development-only textbook RAG for evaluation runs.

The index is a local research artifact: entries are draft, licenses are pending
and no clinical review has signed off. Retrieved passages are injected as prompt
context only; this is not a knowledge release and must not be distributed.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from medtrace.knowledge import KnowledgeError, adult_documented, search_tokens
from medtrace.pipeline import Pipeline

# Procedural/normal-finding pages crowd out disease knowledge in BM25 rankings.
_SKIP_TITLE = ("体格检查", "病历书写", "问诊", "检查方法", "基本项目", "绪论")


class TextbookIndex:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise KnowledgeError(f"textbook index not found: {self.path}")
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        manifest_path = self.path.with_name("index.manifest.json")
        self.manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.is_file() else {}
        with self.connect() as db:
            db.execute("SELECT count(*) FROM search").fetchone()

    def connect(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def describe(self):
        return {"path": str(self.path), "sha256": self.sha256,
                "state": self.manifest.get("state", "unknown"), "release": self.manifest.get("release", False),
                "counts": self.manifest.get("counts", {}),
                "redistribution": self.manifest.get("redistribution", "unknown")}

    def retrieve(self, text, limit=5, max_chars=2500, max_card_chars=800):
        tokens = sorted(set(search_tokens(text)))[:512]
        if not tokens:
            return []
        expression = " OR ".join('"' + t + '"' for t in tokens)
        with self.connect() as db:
            rows = db.execute(
                "SELECT search.id, bm25(search,0,5,1), entries.body FROM search "
                "JOIN entries ON entries.id = search.id WHERE search MATCH ? "
                "ORDER BY 2, search.id LIMIT 60", (expression,)).fetchall()
        out, size, per_chapter = [], 0, {}
        for kid, score, body in rows:
            try:
                e = json.loads(body)
            except ValueError:
                continue
            if e.get("type") != "card" or not e.get("text"):
                continue
            if any(s in e.get("title", "") for s in _SKIP_TITLE):
                continue
            if e.get("scope") == "adult" and not adult_documented(text):
                continue
            chapter = (e.get("book", ""), (e.get("structure") or {}).get("chapter", ""))
            if per_chapter.get(chapter, 0) >= 2:
                continue
            body_text = e["text"]
            if len(body_text) > max_card_chars:
                body_text = body_text[:max_card_chars]
            if size + len(body_text) > max_chars:
                continue
            out.append({"id": kid, "type": "card", "title": e.get("title", kid), "text": body_text,
                        "scope": e.get("scope", "general"), "book": e.get("book", ""),
                        "locator": e.get("locator", ""), "score": score})
            size += len(body_text)
            per_chapter[chapter] = per_chapter.get(chapter, 0) + 1
            if len(out) == limit:
                break
        return out


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
                cards = self.textbook.retrieve(case.text)
                L.knowledge_cards = {c["id"]: c for c in cards}
                audit["status"] = "ok" if cards else "no_hits"
                audit["retrieved"] = [{"id": c["id"], "title": c["title"], "book": c["book"],
                                       "locator": c["locator"], "score": c["score"]} for c in cards]
            except Exception as e:
                L.knowledge_cards = {}
                audit.update(status="degraded", error=str(e))
        return super()._generate_and_verify(case, L, variant, lang, stats, deadline, changes, log)