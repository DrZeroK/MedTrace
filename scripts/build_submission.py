"""Build the offline submission ZIP from a strict whitelist (stdlib only; never imports eval/).

    python scripts/build_submission.py [--output dist/submission.zip]

Only runtime material ships: main.py, medtrace/ (prompts included), the dependency files,
README.md, the resource registration and the demo input. The packaged .env.example is
generated to contain ONLY MODEL_NAME and ENDPOINT (tech spec 附件3 §1); the repo's rich
.env.example is a development template and is deliberately not shipped. No .env, data/,
eval/, data_pipeline/ or tests/ ever enters the archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# .env.example is NOT copied from the repo; build_zip writes the minimal template below instead.
WHITELIST_FILES = ["main.py", "requirements.txt", "requires.txt", "README.md",
                   "docs/RESOURCE_REGISTRATION.md", "input.example.json"]
WHITELIST_FILES += ["README.zh-CN.md", "docs/KNOWLEDGE_BASE.md", "docs/REQUIREMENTS.md",
                    "docs/PROJECT_DESCRIPTION.md", "docs/DECLARATIONS.md"]
WHITELIST_DIRS = ["medtrace"]
_EXCLUDE_NAMES = {"__pycache__", ".DS_Store"}

# Tech spec 附件3 §1/§3: the submission .env.example carries only these two keys. The organiser
# injects the real values at run time; the program must not require a key and must not read paths from .env.
SUBMISSION_ENV_EXAMPLE = (
    "MODEL_NAME=qwen3.8-27b\n"
    "ENDPOINT=http://127.0.0.1:8000/v1/chat/completions\n"
)


def collect_files(root: Path) -> list[str]:
    missing = [f for f in WHITELIST_FILES if not (root / f).is_file()]
    if missing:
        raise ValueError("missing required package files: " + ", ".join(missing))
    if any((root / f).is_symlink() for f in WHITELIST_FILES):
        raise ValueError("package files must not be symlinks")
    names = list(WHITELIST_FILES)
    for d in WHITELIST_DIRS:
        base = root / d
        if not base.is_dir():
            raise ValueError(f"missing runtime directory: {d}")
        if base.is_symlink():
            raise ValueError(f"runtime directory must not be a symlink: {d}")
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(part in _EXCLUDE_NAMES for part in rel.parts) or p.suffix == ".pyc":
                continue
            if p.is_symlink() or p.suffix not in (".py", ".txt"):
                raise ValueError(f"unexpected runtime resource: {rel}")
            names.append(rel.as_posix())
    return sorted(set(names))


def build_zip(root: Path, dest: Path, knowledge_path: Path | None = None) -> tuple[list[str], int]:
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite existing archive: {dest}")
    names = collect_files(root)
    resources = []
    if knowledge_path is not None:
        import sys
        sys.path.insert(0, str(root))
        from medtrace.knowledge import KnowledgeBase
        kb = KnowledgeBase(str(knowledge_path))
        resources = [(kb.path, "resources/knowledge.sqlite"),
                     (kb.path.with_suffix(".manifest.json"), "resources/knowledge.manifest.json")]
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(dest, "x", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            src = root / name
            zf.write(src, name)
            total += src.stat().st_size
        zf.writestr(".env.example", SUBMISSION_ENV_EXAMPLE)   # minimal, spec-compliant template
        names.append(".env.example")
        total += len(SUBMISSION_ENV_EXAMPLE.encode("utf-8"))
        for src, name in resources:
            zf.write(src, name)
            names.append(name)
            total += src.stat().st_size
        manifest = {"git_commit": _git_rev(), "files": {n: hashlib.sha256(zf.read(n)).hexdigest() for n in names}}
        prompt_hash = hashlib.sha256()
        for name in sorted(n for n in names if n.startswith("medtrace/prompts/v2/") and n.endswith(".txt")):
            prompt_hash.update(zf.read(name))
        manifest["prompt"] = "v2:" + prompt_hash.hexdigest()[:12]
        body = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        zf.writestr("submission.manifest.json", body)
        names.append("submission.manifest.json")
        total += len(body.encode("utf-8"))
    return names, total


def _git_rev() -> str:
    try:
        git = shutil.which("git")
        if not git:
            return ""
        return subprocess.run([git, "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def build_results(run_dir: Path, dest: Path) -> list[str]:
    """Package only a completed, internally consistent official-protocol run; retain originals."""
    import sys
    sys.path.insert(0, str(ROOT))
    from medtrace.inputs import load_cases
    from medtrace.note import official_schema_errors
    from medtrace.runner import _validate_official_input
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite existing archive: {dest}")
    cases, envelope = load_cases(str(run_dir / "input.json"))
    _validate_official_input(cases, envelope)
    records = json.loads((run_dir / "output.json").read_text("utf-8"))
    events = json.loads((run_dir / "run_log.json").read_text("utf-8"))
    if not isinstance(records, list) or len(records) != len(cases):
        raise ValueError("output count does not match input")
    for case, record in zip(cases, records):
        if official_schema_errors(record, {s.raw_id for s in case.sources}) or record["case_id"] != case.case_id:
            raise ValueError("invalid or mismatched output record")
    if not isinstance(events, list) or len(events) < 2 or events[0].get("event") != "run_start" or events[-1].get("event") != "run_end":
        raise ValueError("run_log.json must describe a completed run")
    run_id = events[0].get("run_id")
    if not run_id or any(e.get("run_id") != run_id or not e.get("time") for e in events):
        raise ValueError("run log identity or timestamps are missing")
    streamed = [json.loads(line) for line in (run_dir / "logs" / "run_log.jsonl").read_text("utf-8").splitlines()]
    if not streamed or streamed[-1] != events[-1]:
        raise ValueError("exported log does not match the latest run")
    end = events[-1]
    for filename, key in (("input.json", "input_sha256"), ("output.json", "output_sha256")):
        if hashlib.sha256((run_dir / filename).read_bytes()).hexdigest() != end.get(key):
            raise ValueError(f"{filename} no longer matches the completed run")
    case_events = [e for e in events if e.get("event") == "case"]
    if [e.get("case_id") for e in case_events] != [c.case_id for c in cases] or [e.get("index") for e in case_events] != list(range(len(cases))):
        raise ValueError("case log mapping does not match input")
    if end.get("cases") != len(cases) or end.get("not_ok") != sum(r["status"] != "success" for r in records):
        raise ValueError("run summary does not match results")
    for key in ("calls", "http_attempts", "retries", "prompt_tokens", "completion_tokens", "total_tokens"):
        if end.get(key) != sum(e.get(key, 0) for e in case_events):
            raise ValueError(f"run summary {key} does not match case logs")
    names = ["output.json", "run_log.json", "submission.manifest.json"]
    if not (run_dir / "submission.manifest.json").is_file():
        raise ValueError("result packaging requires a run from an extracted algorithm package")
    manifest = json.loads((run_dir / "submission.manifest.json").read_text("utf-8"))
    if events[0].get("git") != manifest.get("git_commit") or events[0].get("prompt") != manifest.get("prompt"):
        raise ValueError("run does not match the algorithm manifest")
    for name, digest in manifest["files"].items():
        path = run_dir / name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink() or not path.resolve().is_relative_to(run_dir.resolve()):
            raise ValueError("invalid path in algorithm manifest")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"algorithm resource changed after packaging: {name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "x", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.write(run_dir / name, name)
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the MedTrace submission ZIP (whitelist only).")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--knowledge", type=Path, help="absolute path to a reviewed release; includes manifest and sources")
    ap.add_argument("--results-from", type=Path, help="package output.json and run_log.json from a completed extracted test package")
    a = ap.parse_args(argv)
    dest = a.output or ROOT / "dist" / ("results.zip" if a.results_from else "submission.zip")
    if a.results_from:
        if a.knowledge:
            ap.error("--knowledge cannot be combined with --results-from")
        names = build_results(a.results_from, dest)
        print(f"results ZIP: {dest}")
        print("\n".join(names))
        return 0
    names, total = build_zip(ROOT, dest, a.knowledge)
    print(f"submission ZIP: {dest}")
    print(f"git commit: {_git_rev() or '(not a git checkout)'}")
    with zipfile.ZipFile(dest) as z:
        print(f"prompt: {json.loads(z.read('submission.manifest.json'))['prompt']}")
    for n in names:
        print(" ", n)
    print(f"files: {len(names)} | uncompressed: {total / 1024:.1f} KiB | zip: {dest.stat().st_size / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
