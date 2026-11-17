"""Mock of the designated model, for offline development and fault injection.

The mock is deliberately dumb: it copies record sentences into the note and adds
template reasoning. It exists to exercise the software (protocol, parsing, budgets,
verification, repair, failure isolation) - NOT to estimate clinical quality.

MOCK_FAULTS="wrong_number:0.3,bad_json:0.1" injects known error types with the given
probabilities; every injected error is recorded in `fault_log` so the evaluation
harness can measure whether the verifier caught it.
"""
from __future__ import annotations

import json
import os
import random
import re
import zlib
from datetime import timedelta

from .textutil import all_number_values, detect_lang, extract_numbers, parse_cutoff, split_sentences

FAULTS = ("wrong_number", "unit_swap", "negation_flip", "fabricate", "undoc_negative", "invalid_ref",
          "post_cutoff", "done_plan", "bad_json", "bad_patch")
_SRC = re.compile(r'<source id="([^"]*)">\n(.*?)\n</source>', re.S)
_UNIT_SWAPS = [("mmol/L", "mg/dL"), ("mg/dL", "mmol/L"), ("mmHg", "kPa"), ("g/dL", "g/L"), ("g/L", "g/dL"), ("ng/mL", "ng/L")]
_NEG_SWAPS = [(r"\b[Dd]enies ", "Reports "), (r"\bNo ", "Marked "), (r"\bno ", "marked "), ("否认", "自诉有"),
              ("未见", "可见"), ("无", "有")]


class MockLLM:
    def __init__(self, faults: dict | None = None, seed: int = 0):
        self.faults = faults or {}
        self.seed = seed
        self.calls = 0
        self.task_calls: dict = {}
        self.fault_log: list[dict] = []

    @classmethod
    def from_env(cls):
        faults = {}
        for part in os.environ.get("MOCK_FAULTS", "").split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                try:
                    faults[k.strip()] = float(v)
                except ValueError:
                    pass
        return cls(faults, int(os.environ.get("MOCK_SEED", "0") or 0))

    # ------------------------------------------------------------------
    def complete(self, messages) -> str:
        self.calls += 1
        user = messages[-1]["content"]
        m = re.search(r"\[task:(\w+)/", user)
        task = m.group(1) if m else "a1"
        sources = _SRC.findall(user)
        self.task_calls[task] = self.task_calls.get(task, 0) + 1
        key = "".join(c for _, c in sources) + ("gen" if task in ("a0", "a1") else task)
        rng = random.Random(self.seed * 1000003 + zlib.crc32(key.encode("utf-8")) + self.task_calls[task])
        zh = detect_lang(" ".join(c for _, c in sources)) == "zh"
        if task in ("repair", "review"):
            return self._patches(user, sources, rng, zh)
        if task == "extract":
            sid, content = sources[0]
            sent = split_sentences(content)[0]
            return json.dumps({"problems": [{"problem": sent[:80], "urgency": "urgent",
                                             "evidence": [{"source": sid, "quote": sent, "polarity": "positive"}]}]}, ensure_ascii=False)
        return self._generate(task, user, sources, rng, zh)

    def _fire(self, name, rng) -> bool:
        return rng.random() < self.faults.get(name, 0.0)

    def _log(self, fault, needle, item=None):
        """`item` is the statement dict the fault lives in; its final text becomes the needle (see _resolve)."""
        self.fault_log.append({"fault": fault, "needle": needle, "_item": item})

    def _resolve(self):
        # A later fault may mutate a statement an earlier fault already changed; the logged needle must be the
        # text that is actually emitted, otherwise the earlier fault is wrongly scored as "removed".
        for e in self.fault_log:
            item = e.pop("_item", None)
            if item is not None:
                e["needle"] = item["text"]

    def _generate(self, task, user, sources, rng, zh) -> str:
        first = sources[0][0]
        feats = [{"text": s, "sources": [sid]} for sid, content in sources for s in split_sentences(content)[:10]]
        if zh:
            disc = [{"kind": "assessment", "basis": "record", "text": "根据上述记录所见可提出初步诊断方向，但尚不能明确，需由医生结合病情判断。", "sources": [first]},
                    {"kind": "uncertainty", "basis": "record", "text": "现有资料不足以进一步缩小鉴别诊断范围。", "sources": [first]}]
            plan = [{"kind": "investigation", "basis": "record", "text": "建议完善与记录所见相关的检查。", "sources": [first]},
                    {"kind": "monitoring", "basis": "record", "text": "建议监测生命体征，待结果回报后再评估。", "sources": [first]}]
            review = [{"type": "verify", "text": "模拟模型输出：临床内容需医生审核。"}]
        else:
            disc = [{"kind": "assessment", "basis": "record", "text": "The recorded findings suggest a working diagnosis that is not yet established and requires clinician assessment.", "sources": [first]},
                    {"kind": "uncertainty", "basis": "record", "text": "The differential diagnosis cannot be narrowed further from the available records.", "sources": [first]}]
            plan = [{"kind": "investigation", "basis": "record", "text": "Recommend completing the investigations indicated by the recorded findings.", "sources": [first]},
                    {"kind": "monitoring", "basis": "record", "text": "Recommend monitoring of vital signs and reassessment once results are available.", "sources": [first]}]
            review = [{"type": "verify", "text": "Mock model output: clinical content requires clinician review."}]

        src_nums = all_number_values(" ".join(c for _, c in sources))
        if self._fire("wrong_number", rng):
            for f in feats:
                nums = [n for n in extract_numbers(f["text"]) if n[1] or "." in n[2]]
                if nums:
                    val, _, raw = nums[0]
                    new = round(val * 1.5 + 1.3, 1)
                    while new in src_nums:
                        new = round(new + 0.7, 1)
                    numtxt = re.match(r"[\d.]+", raw).group()
                    f["text"] = f["text"].replace(numtxt, f"{new:g}", 1)
                    self._log("wrong_number", f["text"], f)
                    break
        if self._fire("unit_swap", rng):
            for f in feats:
                hit = next(((a, b) for a, b in _UNIT_SWAPS if a in f["text"]), None)
                if hit:
                    f["text"] = f["text"].replace(hit[0], hit[1], 1)
                    self._log("unit_swap", f["text"], f)
                    break
        if self._fire("negation_flip", rng):
            for f in feats:
                hit = next(((a, b) for a, b in _NEG_SWAPS if re.search(a, f["text"])), None)
                if hit:
                    f["text"] = re.sub(hit[0], hit[1], f["text"], count=1)
                    self._log("negation_flip", f["text"], f)
                    break
        if self._fire("fabricate", rng):
            t = "既往慢性肾脏病4期，因机械瓣置换长期服用华法林。" if zh else "Long-standing chronic kidney disease stage 4, on warfarin for a mechanical mitral valve."
            feats.append({"text": t, "sources": [first]})
            self._log("fabricate", t)
        if self._fire("undoc_negative", rng):
            t = "否认痛风、癫痫病史。" if zh else "No history of gout or seizures."
            feats.append({"text": t, "sources": [first]})
            self._log("undoc_negative", t)
        if self._fire("post_cutoff", rng):
            m = re.search(r"(?:Record cutoff|资料截止时间)[:：]\s*([^\n(（]+)", user)
            dt, ok = parse_cutoff(m.group(1).strip().rstrip(".。")) if m else (None, False)
            if ok and dt:
                d = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
                t = f"{d}复查示病情好转。" if zh else f"Repeat assessment on {d} showed clinical improvement."
                feats.append({"text": t, "sources": [first]})
                self._log("post_cutoff", t)
        if self._fire("invalid_ref", rng):
            feats[0]["sources"] = feats[0]["sources"] + ["SRC_DOES_NOT_EXIST"]
            self._log("invalid_ref", "SRC_DOES_NOT_EXIST")
        if self._fire("done_plan", rng):
            t = "已行冠状动脉造影并置入药物洗脱支架。" if zh else "Coronary angiography was performed and a drug-eluting stent was placed."
            plan.append({"kind": "treatment", "text": t, "sources": [first]})
            self._log("done_plan", t)

        self._resolve()
        if task == "a0":
            join = lambda items: ("" if zh else " ").join(i["text"] for i in items)
            out = {"case_features": join(feats), "diagnostic_discussion": join(disc), "treatment_plan": join(plan),
                   "evidence": [{"statement": f["text"], "source_ids": f["sources"]} for f in feats[:3]], "review_items": review}
        else:
            out = {"case_features": feats, "diagnostic_discussion": disc, "treatment_plan": plan, "review_items": review}
        text = json.dumps(out, ensure_ascii=False)
        if self._fire("bad_json", rng):
            self._log("bad_json", "")
            return "Here is the note:\n" + text[: len(text) // 2]
        return text

    def _patches(self, user, sources, rng, zh) -> str:
        m = re.search(r"<findings>(.*?)</findings>", user, re.S)
        block = m.group(1) if m else ""
        i, j = block.find("["), block.rfind("]")
        try:
            findings = json.loads(block[i:j + 1]) if 0 <= i < j else []
        except ValueError:
            findings = []
        seen, patches = set(), []
        for f in findings:
            key = (f.get("section"), f.get("index"))
            if key not in seen:
                seen.add(key)
                patches.append({"section": key[0], "index": key[1], "action": "delete", "reason": "unsupported"})
        if self._fire("bad_patch", rng):
            t = "入院时血钾9.9 mmol/L。" if zh else "Serum potassium was 9.9 mmol/L on arrival."
            patches.append({"section": "case_features", "action": "add", "text": t, "sources": [sources[0][0]], "severity": "high"})
            self._log("bad_patch", t)
        self._resolve()
        return json.dumps({"patches": patches, "review_items": []}, ensure_ascii=False)
