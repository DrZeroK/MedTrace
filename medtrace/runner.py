"""Module F - non-interactive batch execution: python main.py

Exit codes. In official mode (OUTPUT_PROTOCOL=official) they follow the provider spec:
  0 = all cases processed and a protocol-valid output.json written (per-record failures allowed);
  1 = task-level runtime error (output could not be completed / unwritable);
  2 = necessary configuration missing or input violates the basic protocol.
Legacy mode keeps the previous behaviour: 0 ok; 1 fatal; 2 only with STRICT_EXIT=1 on a fallback.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, ConfigError, load_config
from .inputs import InputError, load_cases
from .llm import LLMClient, LLMError
from .pipeline import Pipeline, prompt_fingerprint
from .knowledge import KnowledgeError, digest_file, write_audit
from .note import official_schema_errors

log = logging.getLogger("medtrace")


def atomic_write_json(path: str, obj) -> None:
    """Write to a temp file in the same directory, fsync, then rename: readers never see a partial file."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        log.error("write failed; retained recoverable temporary file: %s", tmp)
        raise


def wrap(records: list, envelope: str, cfg):
    env = cfg.output_envelope if cfg.output_envelope != "auto" else envelope
    if env == "list":
        return records
    if env == "single":
        return records[0] if len(records) == 1 else records
    return {env: records}


def _git_rev() -> str:
    try:
        manifest = ROOT / "submission.manifest.json"
        if manifest.is_file():
            return json.loads(manifest.read_text("utf-8"))["git_commit"]
        git = shutil.which("git")
        return subprocess.run([git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip() if git else ""
    except Exception:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MedTrace: evidence-grounded initial progress note generation")
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--development", action="store_true", help="explicitly enable development env settings and path overrides")
    ap.add_argument("--pipeline", help="A0 | A1 | A2 (default, =S1) | S2 | A3 (=S3)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = load_config(development=args.development, input_path=args.input, output_path=args.output,
                          pipeline=args.pipeline.upper() if args.pipeline else None)
    except ConfigError as e:
        log.error("FATAL: %s", e)
        return 2
    run_log = None
    try:
        os.makedirs(cfg.log_dir, exist_ok=True)
        run_log = open(Path(cfg.log_dir) / "run_log.jsonl", "a", encoding="utf-8")
    except OSError as e:
        log.error("FATAL: cannot open run log (%s)", e)
        return 1

    audit_run_id = str(uuid.uuid4())
    events = []
    def emit(obj):
        obj = {**obj, "run_id": audit_run_id, "time": datetime.now(timezone.utc).isoformat()}
        events.append(obj)
        if run_log:
            run_log.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
            run_log.flush()

    started = time.monotonic()
    for w in cfg.warnings:
        log.warning("config: %s", w)
    emit({"event": "run_start", "time": datetime.now(timezone.utc).isoformat(), "config": cfg.public(),
          "prompt": prompt_fingerprint(cfg.prompt_version), "git": _git_rev(), "python": sys.version.split()[0]})
    try:
        cases, envelope = load_cases(cfg.input_path, cfg.cutoff_mode)
        if cfg.official:
            _validate_official_input(cases, envelope)
    except InputError as e:
        log.error("FATAL: %s", e)
        emit({"event": "fatal", "error": str(e)})
        if run_log:
            run_log.close()
        return 2 if cfg.official else 1
    try:
        pipe = Pipeline(cfg, LLMClient(cfg))
    except (LLMError, ConfigError) as e:
        log.error("FATAL: %s", e)
        emit({"event": "fatal", "error": str(e)})
        if run_log:
            run_log.close()
        return 2 if cfg.official else 1
    except KnowledgeError as e:
        log.error("FATAL: %s", e)
        emit({"event": "fatal", "error": str(e)})
        if run_log:
            run_log.close()
        return 1
    log.info("%d case(s), pipeline=%s, model=%s", len(cases), cfg.pipeline, cfg.model or "<mock>")

    results: list = [None] * len(cases)
    totals = {k: 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens", "usage_missing", "calls", "http_attempts", "retries")}
    latencies: list = []
    deadline_all = started + cfg.total_timeout if cfg.total_timeout > 0 else None

    def write():
        obj = [r.record for r in results] if cfg.official else wrap([r.record for r in results], envelope, cfg)
        if cfg.official:
            for case, record in zip(cases, obj):
                errors = official_schema_errors(record, {s.raw_id for s in case.sources})
                if record.get("case_id") != case.case_id or errors:
                    raise ValueError("invalid final output: " + "; ".join(errors))
        atomic_write_json(cfg.output_path, obj)
        if pipe.kb:
            write_audit(cfg.output_path, results, pipe.kb, digest_file(cfg.input_path), audit_run_id)
        out_dir = os.path.dirname(os.path.abspath(cfg.output_path))
        seen = {os.path.basename(cfg.output_path)}
        for alias in cfg.output_aliases:
            name = os.path.basename(alias)
            if not name or name in seen:
                continue
            seen.add(name)
            atomic_write_json(os.path.join(out_dir, name), obj)

    try:
        if pipe.kb:
            write_audit(cfg.output_path, [], pipe.kb, digest_file(cfg.input_path), audit_run_id)
        if cfg.checkpoint and not cfg.official and cases:
            # Seed the output with conservative extract-only notes so that a valid, complete file exists
            # from the first second, whatever happens to the model service or the process later.
            offline = Pipeline(cfg, _Unavailable())
            for c in cases:
                results[c.index] = offline.run_case(c)
            write()

        def work(c):
            now = time.monotonic()
            if deadline_all is not None and now >= deadline_all - 1:
                return None
            dls = [d for d in (deadline_all, now + cfg.case_timeout if cfg.case_timeout > 0 else None) if d]
            return pipe.run_case(c, deadline=min(dls) if dls else None)

        def done(c, r):
            if r is None:
                r = results[c.index] or Pipeline(cfg, _Unavailable()).run_case(c)
                r.log["error"] = "skipped: total time budget exhausted"
            results[c.index] = r
            for k in totals:
                totals[k] += r.log.get(k, 0)
            latencies.append(r.log.get("latency", 0.0))
            emit({"event": "case", **r.log})
            log.info("case %s [%d/%d] status=%s calls=%s latency=%ss", c.case_id, c.index + 1, len(cases),
                     r.status, r.log.get("calls"), r.log.get("latency"))
            if cfg.checkpoint and not cfg.official:
                write()

        if cfg.workers > 1:
            with ThreadPoolExecutor(cfg.workers) as ex:
                futs = [(c, ex.submit(work, c)) for c in cases]
                for c, f in futs:
                    done(c, f.result())
        else:
            for c in cases:
                done(c, work(c))
        write()
    except (OSError, ValueError) as e:
        log.error("FATAL: cannot write output %r: %s", cfg.output_path, e)
        emit({"event": "fatal", "error": str(e)})
        if run_log:
            run_log.close()
        return 1
    except BaseException:
        if run_log:
            run_log.close()
        raise

    n_fb = sum(r.status != "ok" for r in results)
    emit({"event": "run_end", "cases": len(cases), "not_ok": n_fb, "seconds": round(time.monotonic() - started, 2),
          "input_sha256": digest_file(cfg.input_path), "output_sha256": digest_file(cfg.output_path),
          "latency_p50": round(statistics.median(latencies), 3) if latencies else 0.0,
          "latency_max": round(max(latencies), 3) if latencies else 0.0, **totals})
    log.info("wrote %s: %d case(s), %d not ok, %.1fs", cfg.output_path, len(cases), n_fb, time.monotonic() - started)
    if run_log:
        run_log.close()
    try:
        atomic_write_json(str(Path(cfg.output_path).with_name("run_log.json")), events)
    except OSError as e:
        log.error("FATAL: cannot export run_log.json: %s", e)
        return 1
    if cfg.official:
        return 0
    return 2 if (cfg.strict_exit and n_fb) else 0


def _validate_official_input(cases, envelope):
    """Official protocol: top level must be a JSON array; case_id non-empty and unique.
    Malformed per-case sources are still isolated (recorded as failed) rather than aborting the batch.
    """
    if envelope != "list":
        raise InputError("official protocol requires a top-level JSON array of cases")
    seen = set()
    for c in cases:
        key = json.dumps(c.case_id, ensure_ascii=False, sort_keys=True, default=str)
        if not isinstance(c.case_id, str) or not c.case_id.strip():
            raise InputError(f"case at index {c.index} must have a non-empty string case_id")
        if key in seen:
            raise InputError(f"duplicate case_id: {c.case_id}")
        seen.add(key)


class _Unavailable:
    """Stand-in client that always fails: yields the deterministic extract-only note."""

    def chat(self, *a, **k):
        raise LLMError("pending")
