"""Compare the same A2 pipeline with retrieval off and on."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from medtrace.config import Config, ConfigError, load_config
from medtrace.inputs import parse_case
from medtrace.knowledge import KnowledgeBase
from medtrace.llm import LLMClient
from medtrace.mock_llm import MockLLM
from medtrace.note import official_schema_errors
from medtrace.pipeline import Pipeline, prompt_fingerprint
from medtrace.runner import atomic_write_json

from .blind_review import export
from .practice_retrieval import load_practice_cases
from .textbook_rag import TextbookIndex, TextbookRagPipeline

ARMS = ("rag_off", "rag_on")


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class RetrievalOnlyKnowledge(KnowledgeBase):
    """Keep rule-triggered review items out of the retrieval-only contrast."""

    def check_rules(self, ledger):
        return []


class AuditedClient(LLMClient):
    """Record hashes and evidence IDs for the first generation prompt, without repeating its text."""

    first_prompt = None

    def chat(self, system, user, stats, deadline=None):
        if self.first_prompt is None:
            base, marker, suffix = user.rpartition("\n<knowledge_context>\n")
            cards_json, end, footer = suffix.partition("\n</knowledge_context>\n")
            ids = []
            if marker and end and footer.startswith("Knowledge context is reference data,"):
                ids = [card["id"] for card in json.loads(cards_json)]
            self.first_prompt = {"base_sha256": digest((system, base if ids else user)), "kb_ids": ids}
        return super().chat(system, user, stats, deadline)


def prepare_cases(records):
    if not isinstance(records, list) or not records:
        raise ValueError("expected a non-empty array of competition case objects")
    cases, seen = [], set()
    for i, raw in enumerate(records):
        case_id = raw.get("case_id") if isinstance(raw, dict) else None
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError(f"case at position {i} needs a unique, non-empty string case_id")
        seen.add(case_id)
        case = parse_case(raw, i, "redact")
        if not case.usable or case.protocol_errors:
            raise ValueError(f"case at position {i} did not pass intake validation")
        cases.append(case)
    return cases


def run(cases, index_path, *, official=False):
    if official:
        cfg = replace(load_config(), kb_path="", pipeline="A2")
        knowledge = RetrievalOnlyKnowledge(Path(index_path).resolve())
        index_meta = {"sha256": knowledge.manifest["sha256"], "version": knowledge.manifest["version"]}
        draft_index = None
    else:
        cfg = Config(api_base="mock://", model="MockLLM", pipeline="A2", repair_call=False)
        draft_index = TextbookIndex(index_path)
        index_meta = {"sha256": draft_index.sha256, "state": draft_index.describe()["state"]}

    outputs = {arm: [] for arm in ARMS}
    reviews = []
    paired = []
    with nullcontext() if official else patch("socket.socket", side_effect=AssertionError("network disabled")):
        for i, case in enumerate(cases):
            visible = {"case_id": case.case_id, "record_cutoff": case.cutoff_raw,
                       "sources": [{"source_id": src.raw_id, "content": src.content} for src in case.sources]}
            reviews.append({"case": visible})
            order = ARMS if i % 2 == 0 else ARMS[::-1]
            row = {"case_id": case.case_id, "visible_input_sha256": digest(visible), "run_order": order}
            for arm in order:
                enabled = arm == "rag_on"
                client = AuditedClient(cfg, mock=None if official else MockLLM(seed=cfg.seed or 0))
                pipeline = (TextbookRagPipeline(cfg, client, draft_index)
                            if enabled and draft_index is not None else Pipeline(cfg, client))
                if enabled and official:
                    pipeline.kb = knowledge
                result = pipeline.run_case(case)
                outputs[arm].append(result.record)
                refs = {src.raw_id for src in case.sources}
                row[arm] = {
                    "status": result.record["status"],
                    "schema_valid": not official_schema_errors(result.record, refs),
                    "calls": result.log["calls"], "attempts": result.log["http_attempts"],
                    "http_attempts": result.log["http_attempts"] if official else 0,
                    "total_tokens": (result.log["total_tokens"] if official and not result.log["usage_missing"]
                                     else None),
                    "verifier_high": result.log["findings_final"]["high"],
                    "retrieval_status": (result.log.get("knowledge") or result.log.get("textbook_rag") or {}).get("status"),
                    "first_prompt": client.first_prompt,
                }
            off, on = (row[arm]["first_prompt"] for arm in ARMS)
            row["same_base_prompt"] = bool(off and on and off["base_sha256"] == on["base_sha256"])
            if off and off["kb_ids"]:
                raise RuntimeError("retrieval context appeared in the off arm")
            if off and on and not row["same_base_prompt"]:
                raise RuntimeError("A/B base prompts differ outside of retrieval")
            paired.append(row)

    successful = {arm: sum(row[arm]["status"] == "success" for row in paired) for arm in ARMS}
    manifest = {"mode": "official" if official else "mock", "case_count": len(cases),
                "successful": successful,
                "paired_successes": sum(all(row[arm]["status"] == "success" for arm in ARMS) for row in paired),
                "same_base_prompt_pairs": sum(row["same_base_prompt"] for row in paired),
                "retrieval_context_pairs": sum(bool((row["rag_on"]["first_prompt"] or {}).get("kb_ids")) for row in paired),
                "identical_output_pairs": sum(off == on for off, on in zip(outputs["rag_off"], outputs["rag_on"])),
                "pipeline": cfg.pipeline, "model": cfg.model, "seed": cfg.seed,
                "temperature": cfg.temperature, "max_calls_per_case": cfg.max_calls_per_case,
                "prompt": prompt_fingerprint(cfg.prompt_version), "index": index_meta, "pairs": paired}
    return manifest, outputs, reviews


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--practice-archive", type=Path, help="local ClinNote practice ZIP")
    source.add_argument("--input", type=Path, help="authorized official-format JSON cases")
    parser.add_argument("--official", action="store_true", help="use the organizer's configured keyless service")
    parser.add_argument("--index", type=Path, required=True, help="draft index for mock; approved release for official")
    parser.add_argument("--output", type=Path, required=True, help="new local run directory")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("use a new output directory")
    try:
        data = (load_practice_cases(args.practice_archive) if args.practice_archive
                else json.loads(args.input.read_text("utf-8")))
        cases = prepare_cases(data)
        report, outputs, review_cases = run(cases, args.index, official=args.official)
    except (ValueError, OSError, ConfigError) as error:
        parser.error(str(error))
    args.output.mkdir(mode=0o700, parents=True)
    atomic_write_json(str(args.output / "summary.json"), report)
    atomic_write_json(str(args.output / "cases_used.json"), review_cases)
    for arm in ARMS:
        atomic_write_json(str(args.output / f"outputs_{arm}.json"), outputs[arm])
    export(args.output, ["R1", "R2"], 0)
    print(json.dumps({key: value for key, value in report.items() if key != "pairs"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
