"""Capped external development experiment. Run only on the fixed reviewed synthetic input."""
import argparse
import copy
import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from eval.experiment import RequestBudget, fingerprint, write_new
from eval.followup_fixtures import CHECKS, CONTEXT, NORMAL, PRESSURE, RAG, cases_from, check_anchors
from eval.followup_retrieval import RAG_TOPICS, load_history, prepare, questions, read_json
from eval.response_metrics import observe_response
from medtrace.config import load_config
from medtrace.inputs import parse_case
from medtrace.knowledge import digest_file
from medtrace.llm import LLMClient
from medtrace.note import official_schema_errors
from medtrace.pipeline import Pipeline, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]


class FollowupBudget(RequestBudget):
    LIMITS = {"development": 52, "recovery": 8}


def config():
    cfg = load_config(development=True)
    parts = urlsplit(LLMClient(cfg).url)
    if (parts.scheme != "https" or not (parts.hostname or "").endswith(".cn-beijing.maas.aliyuncs.com")
            or parts.path != "/compatible-mode/v1/chat/completions" or parts.username or parts.password
            or parts.query or parts.fragment or not cfg.api_key or cfg.model != "qwen3.5-27b"):
        raise ValueError("expected the configured Beijing Model Studio qwen3.5-27b development route")
    cfg.endpoint, cfg.api_base = parts.geturl(), ""
    cfg.output_protocol, cfg.pipeline, cfg.prompt_version = "official", "A2", "v2"
    cfg.context_mode, cfg.kb_path, cfg.prompt_candidate_path = "legacy", "", ""
    cfg.temperature, cfg.seed, cfg.max_tokens, cfg.enable_thinking = 0, 42, 0, None
    cfg.timeout, cfg.max_calls_per_case, cfg.max_requests_per_case = 65, 2, 2
    cfg.max_retries, cfg.retry_backoff = 1, 2
    cfg.repair_call, cfg.extra_body, cfg.output_lang, cfg.cutoff_mode = False, {}, "zh", "redact"
    return cfg


def planned_jobs():
    for i, key in enumerate((*NORMAL, *PRESSURE)):
        arms = ("plain", "json") if i % 2 == 0 else ("json", "plain")
        yield [(key, arm, 1) for arm in arms]
    for i, key in enumerate(CONTEXT):
        arms = ("legacy", "context") if i % 2 == 0 else ("context", "legacy")
        yield [(key, arm, repeat) for repeat in (1, 2) for arm in arms]
    for i, key in enumerate(RAG):
        arms = ("no_kb", "lexical", "mixed") if i % 2 == 0 else ("mixed", "lexical", "no_kb")
        yield [(key, arm, 1) for arm in arms]


def run_case(raw, arm, repeat, cfg, directory, budget, kb):
    case = parse_case(raw, 0, cfg.cutoff_mode)
    if not case.usable or case.protocol_errors:
        raise ValueError(f"invalid frozen synthetic case {case.case_id}")
    name = f"{case.case_id}/{arm}/{repeat}"
    path = directory / "cases" / f"{name.replace('/', '_')}.json"
    if path.exists():
        return
    if any(e.get("purpose") == name for e in budget.events):
        write_new(path, {"case_id": case.case_id, "arm": arm, "repeat": repeat, "valid": False,
                         "incomplete": "interrupted prior reservation; no resend"})
        return
    cfg = copy.copy(cfg)
    cfg.json_mode = arm != "plain"
    cfg.context_mode = "zh_context_v1" if arm == "context" else "legacy"
    transport_cfg = copy.copy(cfg)
    transport_cfg.output_protocol = "legacy"
    attempts, responses = 0, []

    def transport(url, headers, payload, timeout):
        nonlocal attempts
        stage = "recovery" if attempts else "development"
        attempts += 1
        status, body = budget.post(url, headers, payload, timeout, purpose=name, stage=stage)
        responses.append(observe_response(status, body))
        return status, body

    pipe = Pipeline(cfg, LLMClient(transport_cfg, transport=transport))
    pipe.kb = kb
    result = pipe.run_case(case, deadline=time.monotonic() + 135)
    valid = result.status == "ok" and not official_schema_errors(result.record, {s.raw_id for s in case.sources})
    sections = {name: [{"text": s.text, "source_ids": [case.raw_id(i) for i in s.sources],
                        "basis": s.basis, "knowledge_ids": s.knowledge_ids} for s in statements]
                for name, statements in result.note.sections.items()} if valid else {}
    claims = [{"section": name, **s} for name, statements in sections.items() for s in statements
              if s["basis"] == "knowledge" or s["knowledge_ids"]]
    log = {k: result.log[k] for k in ("status", "latency", "http_attempts", "prompt_tokens",
                                       "completion_tokens", "total_tokens", "usage_missing", "findings_final")}
    log["parse_errors"] = result.log.get("parse_errors", [])
    kb_log = result.log.get("knowledge", {})
    cards = [{"id": e["id"], "title": e["title"], "text": e["text"]} for e in kb_log.get("retrieved", [])]
    write_new(path, {"case_id": case.case_id, "arm": arm, "repeat": repeat, "valid": valid,
                     "responses": responses, "log": log, "record": result.record if valid else None,
                     "sections": sections, "anchors": check_anchors(case.case_id, sections),
                     "findings": [f.as_dict() for f in result.final_findings],
                     "knowledge_status": kb_log.get("status", "not_used"), "injected_cards": cards,
                     "knowledge_claims": claims, "accepted_id_citations": sum(
                         c["valid_ids"] for c in kb_log.get("citations", []))})
    print(name, "valid", valid, "responses", [row["status"] for row in responses], flush=True)


def summarize(directory):
    groups = {}
    missing = []
    for jobs in planned_jobs():
        for key, arm, repeat in jobs:
            path = directory / "cases" / f"{key}_{arm}_{repeat}.json"
            category = "common" if key in NORMAL and arm in ("plain", "json") else (
                "pressure" if key in PRESSURE else "context" if key in CONTEXT else "rag")
            if not path.exists():
                missing.append(path.stem)
                continue
            groups.setdefault(f"{category}/{arm}", []).append(read_json(path))
    events = [json.loads(l) for l in (directory / "requests.jsonl").read_text("utf-8").splitlines()]
    reservations = {e["id"]: e for e in events if e["event"] == "reserved"}
    finished = {e["id"]: e for e in events if e["event"] == "finished"}
    assert len(reservations) <= 60 and finished.keys() <= reservations.keys()
    groups_summary = {}
    for k, rows in groups.items():
        times = sorted(r["log"]["latency"] for r in rows if "log" in r)
        purposes = {f'{r["case_id"]}/{r["arm"]}/{r["repeat"]}' for r in rows}
        used = {i for i, r in reservations.items() if r["purpose"] in purposes}
        usage_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        groups_summary[k] = {"n": len(rows), "first_three_sections": sum(
            bool(r.get("responses") and r["responses"][0]["three_sections"]) for r in rows),
            "valid": sum(r["valid"] for r in rows), "failed": [r["case_id"] for r in rows if not r["valid"]],
            "requests": len(used), "total_tokens": sum(finished.get(i, {}).get("usage", {}).get("total_tokens", 0) for i in used),
            "tokens": {key: sum(finished.get(i, {}).get("usage", {}).get(key, 0) for i in used) for key in usage_keys},
            "median_s": statistics.median(times) if times else None,
            "p95_s": times[math.ceil(.95 * len(times)) - 1] if times else None,
            "injected_cards": sum(len(r.get("injected_cards", [])) for r in rows),
            "knowledge_claims": sum(len(r.get("knowledge_claims", [])) for r in rows),
            "valid_card_id_refs": sum(r.get("accepted_id_citations", 0) for r in rows)}
    return {"groups": groups_summary, "planned": 52, "missing": missing, "http_requests": len(reservations),
            "unreturned": sorted(reservations.keys() - finished.keys()),
            "embedding": sum(r["purpose"].startswith("embedding/") for r in reservations.values()),
            "recovery": sum(r["stage"] == "recovery" for r in reservations.values()),
            "http": {str(status): sum(e.get("status_code") == status for e in finished.values())
                     for status in sorted({e["status_code"] for e in finished.values() if "status_code" in e})},
            "transport_failures": sum("error_type" in e for e in finished.values()),
            "total_tokens": sum(e.get("usage", {}).get("total_tokens", 0) for e in finished.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    directory = args.directory
    if args.report:
        print(json.dumps(summarize(directory), ensure_ascii=False, indent=2))
        return
    if not directory.is_absolute() or not args.source or not args.source.is_absolute() or not args.previous or not args.previous.is_absolute():
        parser.error("absolute experiment, reviewed synthetic source and prior experiment paths are required")
    source_bytes = args.source.read_bytes()
    cases = cases_from(json.loads(source_bytes))
    queries = questions()
    history = load_history(args.previous)
    cfg = config()
    public_cfg = cfg.public()
    for key in ("api_key", "input_path", "output_path", "log_dir", "endpoint"):
        public_cfg.pop(key, None)
    program = [*ROOT.glob("medtrace/*.py"), *ROOT.glob("eval/followup*.py"),
               ROOT / "eval/experiment.py", ROOT / "eval/knowledge.py", ROOT / "eval/response_metrics.py"]
    identity = {"source_sha256": digest_file(args.source), "inputs": fingerprint(cases), "checks": fingerprint(CHECKS),
                "previous_vectors_sha256": fingerprint(history), "new_questions": fingerprint(queries),
                "config": public_cfg, "route_sha256": fingerprint(cfg.endpoint), "prompt": prompt_fingerprint("v2"),
                "code": {str(p.relative_to(ROOT)): digest_file(p) for p in sorted(program)},
                "embedding": "text-embedding-v4/512", "workers": 3}
    queue = list(planned_jobs())
    with FollowupBudget(directory, identity) as budget:
        (directory / "cases").mkdir(exist_ok=True)
        freeze = directory / "inputs_and_labels.json"
        if not freeze.exists():
            write_new(freeze, {"cases": cases, "checks": CHECKS, "questions": queries,
                               "jobs": queue, "rag_topics": RAG_TOPICS})
        def process_jobs(jobs, engines):
            for key, arm, repeat in jobs:
                run_case(cases[key], arm, repeat, cfg, directory, budget, engines.get(arm))
        with ThreadPoolExecutor(max_workers=3) as pool:
            for _ in pool.map(lambda jobs: process_jobs(jobs, {}), queue[:15]):
                pass
            case_queries = [parse_case(cases[k], 0).text for k in RAG]
            lexical, hybrid = prepare(history, queries, case_queries, cfg, budget, directory)
            for _ in pool.map(lambda jobs: process_jobs(jobs, {"mixed": hybrid, "lexical": lexical}), queue[15:]):
                pass
        report = summarize(directory)
        path = directory / f"summary_{budget.used():02d}.json"
        if not path.exists():
            write_new(path, report)
        print("completed", budget.used(), report["missing"], flush=True)


if __name__ == "__main__":
    main()
