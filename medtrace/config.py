"""Official configuration is read only from the two-key .env beside main.py.

Development aliases and tunable settings require explicit development mode.
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


class ConfigError(ValueError):
    pass


@lru_cache(maxsize=1)
def prompt_version() -> str:
    """Development helper; official callers pass their fixed Config.prompt_version explicitly."""
    return str(_get("PROMPT_VERSION", default=DEFAULT_PROMPT_VERSION)).strip() or DEFAULT_PROMPT_VERSION


def load_dotenv_files() -> None:
    for p in (Path.cwd() / ".env",):
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


def _tristate(name, warnings):
    """None when unset/empty or invalid (omit the field, server default); otherwise a bool."""
    v = _get(name)
    if v is None:
        return None
    v = str(v).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    warnings.append(f"{name}={v!r} is not true/false; ignored (server default applies)")
    return None


def _opt_int(name, warnings, *, default=None):
    """default when unset/empty; an int otherwise; invalid values warn and fall back to default."""
    v = _get(name)
    if v is None:
        return default
    try:
        return int(str(v).strip())
    except ValueError:
        warnings.append(f"{name}={v!r} is not an integer; ignored (using {default!r})")
        return default


@dataclass
class Config:
    development: bool = False
    context_mode: str = "legacy"
    prompt_candidate_path: str = ""
    prompt_version: str = DEFAULT_PROMPT_VERSION
    kb_path: str = ""
    input_path: str = "input.json"
    output_path: str = "output.json"
    log_dir: str = "logs"
    api_base: str = ""              # legacy: base URL; client appends /chat/completions
    endpoint: str = ""              # official spec: full request URL, used verbatim (MODEL_NAME/ENDPOINT in .env)
    api_key: str = field(default="", repr=False)   # legacy external providers only; official service is keyless
    model: str = ""
    output_protocol: str = "official"  # official (provider spec: status/medical_record/error, default) | legacy (old contract, opt-in)
    timeout: float = 600.0          # seconds per HTTP request (reasoning models need minutes, see .env.example)
    max_retries: int = 2            # HTTP-level retries per model call (transient errors only)
    retry_backoff: float = 2.0
    temperature: float = 0.0
    max_tokens: int = 0             # 0 => omit, use server default
    json_mode: bool = False         # send response_format=json_object if the endpoint supports it
    seed: int | None = 42           # fixed request seed; unsupported services must be documented before changing it
    enable_thinking: bool | None = None   # None => omit (server default, not necessarily off); sent as chat_template_kwargs (Q7)
    extra_body: dict = field(default_factory=dict)   # merged into every request last (provider-specific switches, may override the above)
    pipeline: str = "A2"
    max_calls_per_case: int = 2     # logical model calls (generation, one regeneration on unparseable output, optional repair/review)
    max_requests_per_case: int = 0  # every HTTP attempt incl. retries (Q5); 0 => unlimited until the organiser publishes a limit
    repair_call: bool = True        # A2: targeted repair call on high-severity findings. load_config() defaults it OFF:
                                    # on real qwen4-max output it fired only on verifier false alarms (docs/REPORT.md 2.6)
    case_timeout: float = 0.0       # 0 => unlimited
    total_timeout: float = 0.0      # 0 => unlimited
    time_reserve: float = 2.0       # seconds of headroom; only used when a case/total deadline exists. Below it, optional
                                    # model steps (extract/regenerate/repair/review) are skipped. Our safety margin, not an official limit.
    workers: int = 1
    cutoff_mode: str = "redact"     # redact | flag | off
    output_lang: str = "auto"       # auto | en | zh
    inline_citations: bool = False
    numbered: bool = True
    include_meta: bool = False
    output_envelope: str = "auto"   # auto | list | <key name>
    output_field_map: dict = field(default_factory=dict)
    output_fields: list = field(default_factory=list)   # empty => all
    output_aliases: list = field(default_factory=list)  # extra filenames written beside the primary after every atomic write (Q9)
    on_unresolved: str = "flag"     # flag | drop
    checkpoint: bool = True
    strict_exit: bool = False
    warnings: list = field(default_factory=list)   # ignored/odd configuration values, logged at run start

    @property
    def official(self) -> bool:
        """True when the output must follow the provider's status/medical_record/error protocol."""
        return self.output_protocol == "official"

    def public(self) -> dict:
        d = asdict(self)
        d["api_key"] = "<set>" if self.api_key else "<empty>"
        return d


def load_config(*, development: bool = False, **overrides) -> Config:
    if not development:
        if any(v is not None for v in overrides.values()):
            raise ConfigError("official execution uses fixed paths and parameters; use --development for overrides")
        path = ROOT / ".env"
        try:
            lines = [line.strip() for line in path.read_text("utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
        except (OSError, UnicodeError) as e:
            raise ConfigError("cannot read UTF-8 .env beside main.py") from e
        keys = [line.split("=", 1)[0].strip() for line in lines]
        if len(lines) != 2 or set(keys) != {"MODEL_NAME", "ENDPOINT"} or any("=" not in line for line in lines):
            raise ConfigError(".env must have exactly one MODEL_NAME and one ENDPOINT assignment")
        for line in lines:
            value = line.split("=", 1)[1].strip()
            if value[:1] in ("'", '"') and value.count(value[0]) != 2:
                raise ConfigError(".env contains an unmatched or multiline quoted value")
        try:
            from dotenv import dotenv_values
        except ImportError:
            dotenv_values = None
        try:
            if dotenv_values is not None:
                values = dict(dotenv_values(path, interpolate=False))
            else:
                values = {}
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        raise ConfigError(".env requires KEY=value assignments")
                    k, v = line.split("=", 1)
                    values[k.strip()] = v.split(" #", 1)[0].strip().strip("'\"")
        except OSError as e:
            raise ConfigError("cannot read .env beside main.py") from e
        if set(values) != {"MODEL_NAME", "ENDPOINT"} or not all(isinstance(v, str) and v.strip() for v in values.values()):
            raise ConfigError(".env must contain only non-empty MODEL_NAME and ENDPOINT")
        from urllib.parse import urlsplit
        endpoint = values["ENDPOINT"].strip()
        try:
            url = urlsplit(endpoint)
            valid = url.scheme in ("http", "https") and url.hostname and url.port != 0 and not url.username and not url.password
        except ValueError:
            valid = False
        if not valid or url.fragment or any(c.isspace() for c in endpoint):
            raise ConfigError("ENDPOINT must be a complete HTTP(S) URL without credentials or fragments")
        kb = ROOT / "resources" / "knowledge.sqlite"
        return Config(input_path=str(ROOT / "input.json"), output_path=str(ROOT / "output.json"),
                      log_dir=str(ROOT / "logs"), endpoint=endpoint, model=values["MODEL_NAME"].strip(),
                      kb_path=str(kb) if kb.is_file() else "", repair_call=False)
    load_dotenv_files()
    warnings: list = []
    c = Config(
        warnings=warnings,
        development=True,
        context_mode=str(_get("CONTEXT_MODE", default="legacy")),
        prompt_candidate_path=str(_get("PROMPT_CANDIDATE_PATH", default="")),
        prompt_version=str(_get("PROMPT_VERSION", default=DEFAULT_PROMPT_VERSION)).strip(),
        kb_path=_get("KB_PATH", default=""),
        input_path=_get("INPUT_PATH", default="input.json"),
        output_path=_get("OUTPUT_PATH", default="output.json"),
        log_dir=_get("LOG_DIR", default="logs"),
        api_base=_get("LLM_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL", "API_BASE", "BASE_URL", default=""),
        endpoint=_get("ENDPOINT", default=""),
        api_key=_get("LLM_API_KEY", "OPENAI_API_KEY", "API_KEY", default=""),
        model=_get("MODEL_NAME", "LLM_MODEL", "MODEL", default=""),
        output_protocol=str(_get("OUTPUT_PROTOCOL", default="legacy")).lower(),
        timeout=_num(float, "LLM_TIMEOUT", default=600.0),
        max_retries=_num(int, "LLM_MAX_RETRIES", default=2),
        retry_backoff=_num(float, "LLM_RETRY_BACKOFF", default=2.0),
        temperature=_num(float, "LLM_TEMPERATURE", default=0.0),
        max_tokens=_num(int, "LLM_MAX_TOKENS", default=0),
        json_mode=_flag("LLM_JSON_MODE"),
        seed=_opt_int("LLM_SEED", warnings, default=42),
        enable_thinking=_tristate("LLM_ENABLE_THINKING", warnings),
        pipeline=str(_get("PIPELINE", default="A2")).upper(),
        max_calls_per_case=_num(int, "MAX_CALLS_PER_CASE", default=2),
        max_requests_per_case=max(0, _num(int, "MAX_REQUESTS_PER_CASE", default=0)),
        repair_call=_flag("REPAIR_CALL"),
        case_timeout=_num(float, "CASE_TIMEOUT", default=0.0),
        total_timeout=_num(float, "TOTAL_TIMEOUT", default=0.0),
        time_reserve=_num(float, "TIME_RESERVE_SECONDS", default=2.0),
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
    c.output_aliases = [a.strip() for a in str(_get("OUTPUT_ALIASES", default="")).split(",") if a.strip()]
    for k, v in overrides.items():
        if v is not None:
            setattr(c, k, v)
    if c.pipeline in ("S1",):
        c.pipeline = "A2"
    if c.pipeline in ("S3",):
        c.pipeline = "A3"
    if c.pipeline not in PIPELINES:
        c.pipeline = "A2"
    if c.output_protocol not in ("legacy", "official"):
        c.output_protocol = "official"
    if c.context_mode not in ("legacy", "zh_context_v1"):
        raise ConfigError("CONTEXT_MODE must be legacy or zh_context_v1")
    return c
