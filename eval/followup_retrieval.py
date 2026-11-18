"""Retrieval experiment with test-only cards and immutable held-out questions."""
import json
import math
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlsplit

from eval.experiment import fingerprint, write_new
from eval.knowledge import evaluate
from medtrace.knowledge import KnowledgeBase, adult_documented, search_tokens

PARAPHRASES = (
    "发热及咳脓痰，右下肺出现新浸润影，局部呼吸音异常",
    "原来一直气流受限，这两日比平时更憋，咳出的痰明显增加",
    "胸前压榨不适伴出汗，连续心电图有缺血演变，心肌标志物上升",
    "睡觉时胸口憋闷需坐起，踝部及两肺有容量负荷征象",
    "血中葡萄糖显著升高，同时出现酮血症并伴酸中毒",
    "打过胰岛素后手抖冒汗，检查显示血糖过低",
    "近两日排尿显著变少，肌酐比已知基线快速上升",
    "复查发现钾偏离参考范围，化验申请单需核对采样条件",
)
OUTSIDE = (
    "右踝扭伤，外踝局部疼痛", "用眼后突然看到黑色漂浮点", "新发牙龈肿胀伴牙痛",
    "颈部包块半年逐渐增大", "晨起手指屈伸卡顿", "下颌关节张口时弹响",
    "腕部腱鞘小肿块", "颈肩痛放射到右手拇指", "冷风诱发流泪",
    "右耳耳痛伴听力减退", "按压肛周肿块有疼痛", "受伤后肘关节无法完全伸直",
    "耳郭出现无痛小结节", "脚趾甲板增厚发黄", "理发后头皮局部皮疹",
    "乳房有可移动无痛包块", "两周来持续耳鸣", "鼻塞及反复流鼻血",
    "左膝上下楼时局限性疼痛", "饭后偶有反流和烧心",
)
RAG_TOPICS = {"SYN001": "K01", "SYN012": "K04", "SYN045": None, "SYN100": "K08"}


def questions():
    rows = [{"id": f"new-semantic-{i}", "query": f"成人，58岁，{text}。",
             "relevant_ids": [f"K0{i}{j}" for j in range(1, 4)]}
            for i, text in enumerate(PARAPHRASES, 1)]
    rows += [{"id": f"new-ood-{i}", "query": f"成人，58岁，{text}。", "relevant_ids": []}
             for i, text in enumerate(OUTSIDE, 1)]
    return rows


def read_json(path):
    return json.loads(path.read_text("utf-8"))


class LexicalIndex(KnowledgeBase):
    def __init__(self, cards):
        self.entries = {e["id"]: e for e in cards}
        self.manifest = {"version": "test-only proxy cards", "sha256": fingerprint(cards)}
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, title, body)")
        self.db.executemany("INSERT INTO search VALUES (?,?,?)", [
            (e["id"], " ".join(search_tokens(e["title"] + " " + " ".join(e["aliases"]))),
             " ".join(search_tokens(e["text"]))) for e in cards
        ])

    @contextmanager
    def connect(self):
        yield self.db


class MixedIndex:
    def __init__(self, lexical, vectors, threshold, topic_filter):
        self.lexical, self.vectors, self.threshold, self.topic_filter = lexical, vectors, threshold, topic_filter
        self.manifest = lexical.manifest

    def normalize(self, text):
        return self.lexical.normalize(text)

    def check_rules(self, ledger):
        return self.lexical.check_rules(ledger)

    def retrieve(self, text):
        hits = self.lexical.retrieve(text)
        if hits or not adult_documented(text):
            return hits
        query = self.vectors.get(text)
        if query is None:
            return hits
        scores = sorted(((key, math.fsum(a * b for a, b in zip(query, self.vectors[key])))
                         for key in self.lexical.entries), key=lambda p: (-p[1], p[0]))
        topic = scores[0][0][:3]
        return [self.lexical.entries[key] for key, score in scores
                if score >= self.threshold and (not self.topic_filter or key.startswith(topic))][:5]


def metrics(index, rows):
    result = evaluate(index, rows)
    positives = [r for r in result["rows"] if r["relevant_ids"]]
    result["cross_topic"] = sum(bool(set(r["retrieved"]) - set(r["relevant_ids"])) for r in positives)
    return result


def load_history(previous):
    fixture = read_json(previous / "retrieval/fixture.json")
    reports = read_json(previous / "retrieval/reports.json")
    vectors = {}
    for path in sorted((previous / "retrieval/vector_run").glob("vectors_*.json")):
        vectors.update(read_json(path))
    cards = fixture["original_proxy_cards"]
    dev = [q for q in fixture["additional_questions"] if q["split"] == "dev"]
    assert len(cards) == 24 and len(dev) == 16
    assert all(len(vectors[c["id"]]) == 512 for c in cards)
    return cards, dev, vectors, reports["similarity_threshold"]


def prepare(history, queries, case_queries, cfg, budget, directory):
    import time

    cards, dev, old_vectors, old_threshold = history
    index = LexicalIndex(cards)
    old_dev = metrics(MixedIndex(index, old_vectors, old_threshold, False), dev)
    # Freeze the candidate using development items only. Among equally accurate
    # settings prefer fewer irrelevant cards, then the highest threshold.
    ranked = []
    for threshold in sorted({0.54, 0.57, 0.60, old_threshold, 0.62, 0.65}):
        result = metrics(MixedIndex(index, old_vectors, threshold, True), dev)
        ranked.append((threshold, result))
    threshold, chosen = max(ranked, key=lambda pair: (-pair[1]["false_injection_rate"], pair[1]["recall_at_5"],
                                                     -pair[1]["cross_topic"], pair[0]))
    frozen = {"threshold": threshold, "old_threshold": old_threshold, "development": chosen,
              "old_development": old_dev, "heldout_sha256": fingerprint(queries),
              "dev_search": [{"threshold": t, "recall_at_5": row["recall_at_5"],
                              "false_injection_rate": row["false_injection_rate"], "cross_topic": row["cross_topic"]}
                             for t, row in ranked]}
    path = directory / "retrieval_freeze.json"
    if not path.exists():
        write_new(path, frozen)
    else:
        previous_freeze = read_json(path)
        if (previous_freeze["threshold"], previous_freeze["heldout_sha256"]) != (threshold, fingerprint(queries)):
            raise ValueError("retrieval freeze changed")
    texts = list(dict.fromkeys([q["query"] for q in queries] + case_queries))
    assert len(texts) <= 40
    vectors = {k: old_vectors[k] for k in index.entries}
    failures, timings = [], []
    route = urlsplit(cfg.endpoint)._replace(path="/compatible-mode/v1/embeddings").geturl()
    for offset in range(0, len(texts), 10):
        batch = texts[offset:offset + 10]
        path = directory / f"vector_batch_{offset:02d}.json"
        purpose = f"embedding/{offset:02d}"
        if path.exists():
            data = read_json(path)
        else:
            if any(e.get("purpose") == purpose for e in budget.events):
                failures.append({"batch": offset, "error": "reserved_without_result"})
                continue
            started = time.monotonic()
            try:
                status, body = budget.post(route, {"Authorization": f"Bearer {cfg.api_key}",
                                                   "Content-Type": "application/json"},
                                           {"model": "text-embedding-v4", "dimensions": 512,
                                            "encoding_format": "float", "input": batch},
                                           55, purpose=purpose)
                response = json.loads(body)
                if status != 200:
                    data = {"http": status, "error": str(response.get("code", "provider_error")), "vectors": []}
                else:
                    items = sorted(response["data"], key=lambda r: r["index"])
                    if [r["index"] for r in items] != list(range(len(batch))):
                        raise ValueError("embedding result indexes differ from request")
                    normalized = []
                    for row in items:
                        v = row["embedding"]
                        norm = math.sqrt(math.fsum(x * x for x in v))
                        if len(v) != 512 or not math.isfinite(norm) or norm <= 0:
                            raise ValueError("invalid embedding")
                        normalized.append([x / norm for x in v])
                    data = {"http": status, "error": None, "vectors": normalized}
            except (ValueError, ConnectionError, KeyError, TypeError) as exc:
                data = {"http": None, "error": type(exc).__name__, "vectors": []}
            data["seconds"] = round(time.monotonic() - started, 3)
            write_new(path, data)
        timings.append(data["seconds"])
        if data["error"]:
            failures.append({"batch": offset, "error": data["error"], "http": data["http"]})
        vectors.update(zip(batch, data["vectors"]))
    hybrid = MixedIndex(index, vectors, threshold, True)
    reports = {"old": metrics(MixedIndex(index, vectors, old_threshold, False), queries),
               "lexical": metrics(index, queries), "candidate": metrics(hybrid, queries),
               "batch_seconds": timings, "batches_failed": failures,
               "eligible_for_gate": not failures, "threshold": threshold}
    path = directory / "retrieval.json"
    if not path.exists():
        write_new(path, reports)
    return index, hybrid
