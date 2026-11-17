"""Build a new reviewed offline release; drafts are never published."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from medtrace.knowledge import build_database


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--version", required=True)
    a = p.parse_args()
    entries = [json.loads(line) for line in Path(a.source).read_text("utf-8").splitlines() if line.strip()]
    print(json.dumps(build_database(entries, a.output, a.version), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
