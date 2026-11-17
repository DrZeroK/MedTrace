"""Build the offline submission ZIP from a strict whitelist (stdlib only; never imports eval/).

    python scripts/build_submission.py [--output dist/submission.zip]

Only runtime material ships: main.py, medtrace/ (prompts included), the dependency files,
.env.example, README.md, the resource registration and the demo input. No .env, data/, eval/,
data_pipeline/ or tests/ ever enters the archive.
"""
from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHITELIST_FILES = ["main.py", "requirements.txt", "requires.txt", ".env.example", "README.md",
                   "docs/RESOURCE_REGISTRATION.md", "input.example.json"]
WHITELIST_FILES.append("docs/KNOWLEDGE_BASE.md")
WHITELIST_DIRS = ["medtrace"]
_EXCLUDE_NAMES = {"__pycache__", ".DS_Store"}


def collect_files(root: Path) -> list[str]:
    names = [f for f in WHITELIST_FILES if (root / f).is_file()]
    for d in WHITELIST_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(part in _EXCLUDE_NAMES for part in rel.parts) or p.suffix == ".pyc":
                continue
            names.append(rel.as_posix())
    return sorted(set(names))


def build_zip(root: Path, dest: Path, knowledge_path: Path | None = None) -> tuple[list[str], int]:
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
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            src = root / name
            zf.write(src, name)
            total += src.stat().st_size
        for src, name in resources:
            zf.write(src, name)
            names.append(name)
            total += src.stat().st_size
    return names, total


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the MedTrace submission ZIP (whitelist only).")
    ap.add_argument("--output", default=str(ROOT / "dist" / "submission.zip"))
    ap.add_argument("--knowledge", type=Path, help="absolute path to a reviewed release; includes manifest and sources")
    a = ap.parse_args(argv)
    dest = Path(a.output)
    names, total = build_zip(ROOT, dest, a.knowledge)
    print(f"submission ZIP: {dest}")
    print(f"git commit: {_git_rev() or '(not a git checkout)'}")
    for n in names:
        print(" ", n)
    print(f"files: {len(names)} | uncompressed: {total / 1024:.1f} KiB | zip: {dest.stat().st_size / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
