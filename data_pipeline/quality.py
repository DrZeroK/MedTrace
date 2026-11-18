"""Dataset-agnostic quality control: corruption, PII, duplicates, classification helpers, leakage-safe splits."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata

def reviewed_case_ids(dataset: str, raw_sha256: str) -> set[str]:
    review = json.loads(Path(__file__).with_name("reviewed_inputs_20261118.json").read_text("utf-8"))[dataset]
    if raw_sha256 != review["raw_sha256"]:
        raise ValueError(f"{dataset}: source changed since the admission-input review")
    return set(review["keep"])


# ----------------------------------------------------------------------- PII
_PII_HARD = [  # high-confidence identifiers: always redacted
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[身份证号已去除]"),
    ("mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[电话已去除]"),
    ("record_no", re.compile(r"((?:住院|病案|门诊|床|病历|医保|社保)号)\s*[:：]?\s*[A-Za-z0-9\-]{3,}"), r"\1：[已去除]"),
    ("named_field", re.compile(r"((?:姓名|联系人|家属|住址|地址|工作单位|联系电话)\s*[:：])\s*[^\s，,。；;\n]{2,30}"), r"\1[已去除]"),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[邮箱已去除]"),
]
# a 2-3 character name directly before the sex at the start of a line: "张三，男，25岁"
_NAME_LEAD = re.compile(r"(^|\n)(\s*)([一-鿿]{2,3})(?=[，,]\s*[男女])")
_NOT_NAME = {"病人", "患者", "病儿", "患儿", "男性", "女性", "病员", "产妇", "孕妇", "老人", "伤者", "伤员", "男患", "女患",
             "男病人", "女病人", "男患者", "女患者", "男病儿", "女病儿", "男孩", "女孩", "男童", "女童", "婴儿", "新生儿"}
_MASKED = re.compile(r"[一-鿿][xX某＊*×]{1,2}(?=[，,])")


def scrub_pii(text: str) -> tuple[str, dict]:
    """Redact identifiers. Returns (clean text, {kind: count}). Already-masked names (代xx) are counted, not changed."""
    hits: dict = {}
    for kind, rx, repl in _PII_HARD:
        text, n = rx.subn(repl, text)
        if n:
            hits[kind] = n

    def _name(m):
        if m.group(3) in _NOT_NAME or m.group(3).endswith(("病人", "患者", "男性", "女性")):
            return m.group(0)
        hits["possible_name"] = hits.get("possible_name", 0) + 1
        return f"{m.group(1)}{m.group(2)}患者"

    text = _NAME_LEAD.sub(_name, text)
    n = len(_MASKED.findall(text))
    if n:
        hits["already_masked_name"] = n
    return text, hits


# ---------------------------------------------------------------- corruption
def corruption_issues(text: str, min_chars: int = 60) -> list[str]:
    issues = []
    if not isinstance(text, str) or len(text.strip()) < min_chars:
        return ["too_short"]
    if "�" in text:
        issues.append("replacement_char")
    ctrl = sum(1 for ch in text if unicodedata.category(ch) == "Cc" and ch not in "\n\t\r")
    if ctrl:
        issues.append("control_chars")
    cjk = len(re.findall(r"[一-鿿]", text))
    if cjk / max(1, len(text)) < 0.25:
        issues.append("low_chinese_ratio")
    if re.search(r"(.)\1{14,}", text):
        issues.append("long_char_run")
    return issues


# ----------------------------------------------------------------- duplicates
def norm_text(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", text or "")).lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(norm_text(text).encode("utf-8")).hexdigest()


def shingles(text: str, k: int = 5) -> set:
    t = norm_text(text)
    return {t[i:i + k] for i in range(max(1, len(t) - k + 1))}


def near_duplicate_groups(texts: dict, threshold: float = 0.6) -> list[list]:
    """Union-find clustering on character 5-gram Jaccard similarity. texts: {key: text}. O(n^2): fine for <= ~5k."""
    keys = list(texts)
    sh = {k: shingles(texts[k]) for k in keys}
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            inter = len(sh[a] & sh[b])
            if inter and inter / len(sh[a] | sh[b]) >= threshold:
                parent[find(a)] = find(b)
    groups: dict = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return [g for g in groups.values() if len(g) > 1]


# --------------------------------------------------------------------- splits
def assign_splits(group_of: dict, ratios=(("dev", 0.4), ("validation", 0.2), ("test", 0.4)), salt: str = "medtrace-v1") -> dict:
    """Deterministic, group-wise split: every case sharing a group key (same disease label or near-duplicate
    cluster) lands in the same split, so nothing leaks across splits. Stable under adding new cases."""
    out = {}
    for case_id, group in group_of.items():
        h = int(hashlib.sha256(f"{salt}|{group}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        acc = 0.0
        for name, r in ratios:
            acc += r
            if h <= acc:
                out[case_id] = name
                break
        else:
            out[case_id] = ratios[-1][0]
    return out


# ----------------------------------------------------------------- complexity
def complexity(n_chars: int, n_measurements: int, n_sections: int) -> str:
    score = (n_chars > 450) + (n_chars > 900) + (n_measurements > 6) + (n_measurements > 15) + (n_sections > 3)
    return "high" if score >= 3 else "medium" if score >= 1 else "low"
