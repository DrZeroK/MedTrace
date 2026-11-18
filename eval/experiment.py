"""Persistent experiment identity and a single-process, pre-dispatch HTTP budget.

All artifacts are retained. A reservation is charged even if a process dies before
the response is recorded; resuming never restores that request allowance.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
from pathlib import Path
from datetime import datetime, timezone

from medtrace import llm
from medtrace.llm import BudgetExceeded


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_new(path: Path, value) -> None:
    """Immutable artifacts make interrupted runs auditable instead of replacing earlier results."""
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


class RequestBudget:
    LIMITS = {"development": 120, "confirmation": 180}

    def __init__(self, directory: Path, identity: dict):
        if not directory.is_absolute():
            raise ValueError("experiment directory must be absolute")
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = (directory / "experiment.lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ValueError("another process owns this experiment directory")
        self.stage = "development"
        self.mutex = threading.Lock()
        self.purpose = "generation"
        self.path = directory / "requests.jsonl"
        self.manifest = {"schema_version": 1, "identity": identity, "limits": self.LIMITS}
        try:
            manifest_path = directory / "experiment.json"
            if manifest_path.exists():
                if json.loads(manifest_path.read_text("utf-8")) != self.manifest:
                    raise ValueError("experiment identity changed; use a new directory")
            else:
                if self.path.exists():
                    raise ValueError("request journal exists without experiment identity")
                write_new(manifest_path, self.manifest)
            self.events = []
            if self.path.exists():
                for line in self.path.read_text("utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        self.events.append(json.loads(line))
                    except ValueError as e:
                        raise ValueError("incomplete request journal; retain it for manual recovery") from e
            reservations = [e for e in self.events if e.get("event") == "reserved"]
            if [e.get("id") for e in reservations] != list(range(1, len(reservations) + 1)):
                raise ValueError("request journal reservation sequence is invalid")
            if any(e.get("stage") not in self.LIMITS for e in reservations):
                raise ValueError("request journal contains an unknown stage")
        except BaseException:
            self.close()
            raise

    def close(self):
        self.lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def used(self, stage=None) -> int:
        return sum(e.get("event") == "reserved" and (stage is None or e["stage"] == stage) for e in self.events)

    def append(self, event):
        event = {**event, "time": datetime.now(timezone.utc).isoformat()}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.events.append(event)

    def post(self, url, headers, payload, timeout):
        with self.mutex:
            return self._post(url, headers, payload, timeout)

    def _post(self, url, headers, payload, timeout):
        if self.stage not in self.LIMITS:
            raise ValueError("unknown request stage")
        if self.used() >= 300 or self.used(self.stage) >= self.LIMITS[self.stage]:
            raise BudgetExceeded(f"{self.stage} HTTP request allowance exhausted")
        number = self.used() + 1
        self.append({"event": "reserved", "id": number, "stage": self.stage, "purpose": self.purpose,
                     "request_sha256": fingerprint({"url": url, "body": payload}), "model": payload.get("model")})
        try:
            status, body = llm._post(url, headers, payload, timeout)
        except BaseException as e:
            self.append({"event": "finished", "id": number, "error_type": type(e).__name__})
            raise
        try:
            usage = json.loads(body).get("usage", {})
        except (ValueError, AttributeError):
            usage = {}
        usage = {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                 and isinstance(v, int) and not isinstance(v, bool) and v >= 0} if isinstance(usage, dict) else {}
        self.append({"event": "finished", "id": number, "status_code": status, "usage": usage})
        return status, body

    def summary(self):
        return {"http_requests": self.used(), "by_stage": {s: self.used(s) for s in self.LIMITS},
                "usage": {k: sum(e.get("usage", {}).get(k, 0) for e in self.events)
                          for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
                "cost": "unknown: no verified provider unit price configured"}
