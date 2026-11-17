"""Configuration: everything is read from the environment / .env. Nothing is hardcoded.

Several aliases are accepted per setting because the organiser's variable names
are not yet confirmed (see docs/REQUIREMENTS.md).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINES = ("A0", "A1", "A2", "S2", "A3")  # A2 == strategy S1 (default), A3 == strategy S3
DEFAULT_PROMPT_VERSION = "v2"


@lru_cache(maxsize=1)
def prompt_version() -> str:
    """v2 concise (default) | v1 original long-form. Resolved on first use, after .env is read: evaluating this
    at import time silently ignored a PROMPT_VERSION that lives only in .env (modules import before load_config).
    Call .cache_clear() if the environment changes within one process."""
    load_dotenv_files()
    return str(_get("PROMPT_VERSION", default=DEFAULT_PROMPT_VERSION)).strip() or DEFAULT_PROMPT_VERSION


def load_dotenv_files() -> None:
    for p in (Path.cwd() / ".env", ROOT / ".env"):
        if not p.is_file():
            continue
        try:
            from dotenv import load_dotenv
            load_dotenv(p, override=False)
        except ImportError:  # tiny fallback so a missing optional dependency never blocks a run
            for line in p.read_text("utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.split(" #", 1)[0].strip().strip("'\""))


def _get(*names, default=None):
    for n in names:
        v = os.environ.get(n)
        if v is not None and v.strip() != "" and not v.lstrip().startswith("#"):
            return v
    return default


def _num(cast, *names, default):
    try:
        return cast(_get(*names, default=default))
    except (TypeError, ValueError):
        return default


def _flag(*names, default=False):
    return str(_get(*names, default="1" if default else "0")).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    input_path: str = "input.json"
    output_path: str = "output.json"
    log_dir: str = "logs"
    api_base: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout: float = 600.0          # seconds per HTTP request (reasoning models need minutes, see .env.example)
    max_retries: int = 2            # HTTP-level retries per model call (transient errors only)
    retry_backoff: float = 2.0
    temperature: float = 0.0
    max_tokens: int = 0             # 0 => omit, use server default
    json_mode: bool = False         # send response_format=json_object if the endpoint supports it
    extra_body: dict = field(default_factory=dict)   # merged into every request (provider-specific switches)
    pipeline: str = "A2"
    max_calls_per_case: int = 2     # logical model calls (generation, one regeneration on unparseable output, optional repair/review)
    repair_call: bool = True        # A2: targeted repair call on high-severity findings. load_config() defaults it OFF:
                                    # on real qwen4-max output it fired only on verifier false alarms (docs/REPORT.md 2.6)
    case_timeout: float = 0.0       # 0 => unlimited
    total_timeout: float = 0.0      # 0 => unlimited
    workers: int = 1
    cutoff_mode: str = "redact"     # redact | flag | off
    output_lang: str = "auto"       # auto | en | zh
    inline_citations: bool = False
    numbered: bool = True
    include_meta: bool = False
    output_envelope: str = "auto"   # auto | list | <key name>
    output_field_map: dict = field(default_factory=dict)
    output_fields: list = field(default_factory=list)   # empty => all
    on_unresolved: str = "flag"     # flag | drop
    checkpoint: bool = True
    strict_exit: bool = False

    def public(self) -> dict:
        d = asdict(self)
        d["api_key"] = "<set>" if self.api_key else "<empty>"
        return d


def load_config(**overrides) -> Config:
    load_dotenv_files()
    c = Config(
        input_path=_get("INPUT_PATH", default="input.json"),
        output_path=_get("OUTPUT_PATH", default="output.json"),
        log_dir=_get("LOG_DIR", default="logs"),
        api_base=_get("LLM_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL", "API_BASE", "BASE_URL", default=""),
        api_key=_get("LLM_API_KEY", "OPENAI_API_KEY", "API_KEY", default=""),
        model=_get("LLM_MODEL", "MODEL_NAME", "MODEL", default=""),
        timeout=_num(float, "LLM_TIMEOUT", default=600.0),
        max_retries=_num(int, "LLM_MAX_RETRIES", default=2),
        retry_backoff=_num(float, "LLM_RETRY_BACKOFF", default=2.0),
        temperature=_num(float, "LLM_TEMPERATURE", default=0.0),
        max_tokens=_num(int, "LLM_MAX_TOKENS", default=0),
        json_mode=_flag("LLM_JSON_MODE"),
        pipeline=str(_get("PIPELINE", default="A2")).upper(),
        max_calls_per_case=_num(int, "MAX_CALLS_PER_CASE", default=2),
        repair_call=_flag("REPAIR_CALL"),
        case_timeout=_num(float, "CASE_TIMEOUT", default=0.0),
        total_timeout=_num(float, "TOTAL_TIMEOUT", default=0.0),
        workers=max(1, _num(int, "WORKERS", default=1)),
        cutoff_mode=str(_get("CUTOFF_MODE", default="redact")).lower(),
        output_lang=str(_get("OUTPUT_LANG", default="auto")).lower(),
        inline_citations=_flag("INLINE_CITATIONS"),
        numbered=_flag("NUMBERED", default=True),
        include_meta=_flag("INCLUDE_META"),
        output_envelope=_get("OUTPUT_ENVELOPE", default="auto"),
        on_unresolved=str(_get("ON_UNRESOLVED", default="flag")).lower(),
        checkpoint=_flag("CHECKPOINT", default=True),
        strict_exit=_flag("STRICT_EXIT"),
    )
    for attr, var in (("output_field_map", "OUTPUT_FIELD_MAP"), ("extra_body", "LLM_EXTRA_BODY")):
        try:
            val = json.loads(_get(var, default="{}"))
        except ValueError:
            val = {}
        setattr(c, attr, val if isinstance(val, dict) else {})
    c.output_fields = [f.strip() for f in str(_get("OUTPUT_FIELDS", default="")).split(",") if f.strip()]
    for k, v in overrides.items():
        if v is not None:
            setattr(c, k, v)
    if c.pipeline in ("S1",):
        c.pipeline = "A2"
    if c.pipeline in ("S3",):
        c.pipeline = "A3"
    if c.pipeline not in PIPELINES:
        c.pipeline = "A2"
    return c
