"""Reproducible dataset acquisition. Downloads only what is openly licensed and directly accessible.

    python -m data_pipeline.acquire cmb_clin          # -> data/raw/cmb_clin/CMB-Clin-qa.json (+ LICENSE, provenance.json)
    python -m data_pipeline.acquire --list

Gated, account-only or unlicensed datasets are never fetched automatically: the script prints what a
team member has to do by hand and why. Raw downloads live under data/raw/ (git-ignored).
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
REGISTRY = json.loads((Path(__file__).parent / "registry.json").read_text("utf-8"))

AUTO = {
    "cmb_clin": {
        "files": {"CMB.zip": "https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/data/CMB.zip",
                  "LICENSE": "https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/LICENSE"},
        "extract": {"CMB.zip": {"CMB/CMB-Clin/CMB-Clin-qa.json": "CMB-Clin-qa.json"}},
        "expect_license": "Apache License",
        # pinned content hash of the extracted file (audit date in registry.json); a mismatch means upstream changed
        "sha256": {"CMB-Clin-qa.json": "fc4d8d2dbfe7f647e257ceefddc9ab467576e2c4c2978fecba70f38d3c27c07e"},
    },
}


def _get(url: str, tries: int = 4) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dataset-fetch"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:   # noqa: BLE001 - retried, then reported
            last = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"download failed: {url}: {last}")


def acquire(dataset: str) -> Path:
    if dataset not in AUTO:
        entry = next((d for d in REGISTRY["datasets"] if d["id"] == dataset), None)
        if entry is None:
            raise SystemExit(f"unknown dataset {dataset!r}")
        raise SystemExit(f"{entry['name']} is not downloaded automatically.\n  status : {entry['status']}\n  licence: {entry['license']}\n"
                         f"  access : {entry['access']}\n  url    : {entry['url']}\nPlace manually obtained files under data/raw/{dataset}/ "
                         f"only after the licence and the competition's data rules have been confirmed.")
    spec = AUTO[dataset]
    out = RAW / dataset
    out.mkdir(parents=True, exist_ok=True)
    prov = {"dataset": dataset, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": {}}
    blobs = {name: _get(url) for name, url in spec["files"].items()}
    if spec["expect_license"] not in blobs["LICENSE"].decode("utf-8", "replace")[:400]:
        raise SystemExit("licence file no longer matches the audited licence - stop and re-audit before using this dataset")
    (out / "LICENSE").write_bytes(blobs["LICENSE"])
    for archive, members in spec["extract"].items():
        with zipfile.ZipFile(io.BytesIO(blobs[archive])) as z:
            for member, target in members.items():
                data = z.read(member)
                digest = hashlib.sha256(data).hexdigest()
                pinned = spec["sha256"].get(target)
                if pinned and not pinned.startswith("PINNED") and pinned != digest:
                    raise SystemExit(f"{target}: sha256 {digest} differs from the pinned {pinned}; upstream changed - re-audit")
                (out / target).write_bytes(data)
                prov["files"][target] = {"source": spec["files"][archive], "member": member, "sha256": digest, "bytes": len(data)}
    (out / "provenance.json").write_text(json.dumps(prov, indent=1), "utf-8")
    print(f"{dataset}: {', '.join(prov['files'])} -> {out}")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        for d in REGISTRY["datasets"]:
            print(f"{d['rank']}. {d['id']:<24} auto={'yes' if d['id'] in AUTO else 'no '}  {d['status']}")
    else:
        acquire(sys.argv[1])
