"""A small offline document-frequency model for retrieval anchors."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path

from .knowledge import alias_hit
from .textutil import fw
from .retrieval import prepare_query


def fit_anchor_weights(cases, vocabulary):
    """Learn specificity from case-level term frequency using a fixed medical vocabulary."""
    vocab = sorted(set(fw(alias).lower().strip() for alias in vocabulary if len(alias.strip()) >= 2))
    frequencies = Counter()
    count = 0
    for case in cases:
        clauses, _ = prepare_query({"other": [src.content for src in case.sources]})
        positive = " ".join(clause for clause, _ in clauses)
        frequencies.update(alias for alias in vocab if alias_hit(alias, positive))
        count += 1
    if not count:
        raise ValueError("training requires cases")
    largest = math.log1p(count)
    return {term: round(0.75 + 0.25 * math.log((count + 1) / (freq + 1)) / largest, 6)
            for term, freq in sorted(frequencies.items())}


def load_anchor_weights(path):
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or profile.get("format") != "clinical-anchor-idf-v1" or not isinstance(profile.get("anchor_weights"), dict):
        raise ValueError("unsupported anchor weight profile")
    weights = profile["anchor_weights"]
    if any(not isinstance(k, str) or type(v) not in (int, float) or not 0.75 <= v <= 1.0
           for k, v in weights.items()):
        raise ValueError("invalid anchor weight")
    return weights
