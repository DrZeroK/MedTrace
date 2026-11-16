"""Module F - non-interactive batch execution: python main.py

Exit codes (official values to be confirmed): 0 = output.json written and valid;
1 = fatal (input unreadable / output unwritable / no model configured);
2 = only with STRICT_EXIT=1, when at least one case fell back.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, load_config
from .inputs import InputError, load_cases
from .llm import LLMClient, LLMError
from .pipeline import Pipeline, prompt_fingerprint

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
        try:
            os.unlink(tmp)
        except OSError:
            pass
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
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MedTrace: evidence-grounded initial progress note generation")
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--pipeline", help="A0 | A1 | A2 (default, =S1) | S2 | A3 (=S3)")
    args = ap.parse_args(argv)
    cfg = load_config(input_path=args.input, output_path=args.output, pipeline=args.pipeline.upper() if args.pipeline else None)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    run_log = None
    try:
        os.makedirs(cfg.log_dir, exist_ok=True)
        run_log = open(Path(cfg.log_dir) / "run_log.jsonl", "a", encoding="utf-8")
    except OSError as e:
        log.warning("cannot open run log (%s); continuing without it", e)

    def emit(obj):
        if run_log:
            run_log.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
            run_log.flush()

    started = time.monotonic()
    emit({"event": "run_start", "time": datetime.now(timezone.utc).isoformat(), "config": cfg.public(),
          "prompt": prompt_fingerprint(), "git": _git_rev(), "python": sys.version.split()[0]})
    try:
        cases, envelope = load_cases(cfg.input_path, cfg.cutoff_mode)
    except InputError as e:
        log.error("FATAL: %s", e)
        emit({"event": "fatal", "error": str(e)})
        return 1
    try:
        pipe = Pipeline(cfg, LLMClient(cfg))
    except LLMError as e:
        log.error("FATAL: %s", e)
        emit({"event": "fatal", "error": str(e)})
        return 1
    log.info("%d case(s), pipeline=%s, model=%s", len(cases), cfg.pipeline, cfg.model or "<mock>")

    results: list = [None] * len(cases)
    deadline_all = started + cfg.total_timeout if cfg.total_timeout > 0 else None

    def write():
        atomic_write_json(cfg.output_path, wrap([r.record for r in results], envelope, cfg))

    try:
        if cfg.checkpoint and cases:
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
            emit({"event": "case", **r.log})
            log.info("case %s [%d/%d] status=%s calls=%s latency=%ss", c.case_id, c.index + 1, len(cases),
                     r.status, r.log.get("calls"), r.log.get("latency"))
            if cfg.checkpoint:
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
    except OSError as e:
        log.error("FATAL: cannot write output %r: %s", cfg.output_path, e)
        emit({"event": "fatal", "error": str(e)})
        return 1

    n_fb = sum(r.status != "ok" for r in results)
    emit({"event": "run_end", "cases": len(cases), "not_ok": n_fb, "seconds": round(time.monotonic() - started, 2)})
    log.info("wrote %s: %d case(s), %d not ok, %.1fs", cfg.output_path, len(cases), n_fb, time.monotonic() - started)
    if run_log:
        run_log.close()
    return 2 if (cfg.strict_exit and n_fb) else 0


class _Unavailable:
    """Stand-in client that always fails: yields the deterministic extract-only note."""

    def chat(self, *a, **k):
        raise LLMError("pending")
