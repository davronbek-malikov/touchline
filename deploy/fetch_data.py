"""Download the built warehouse and passages from the GitHub data release and verify them.

    python deploy/fetch_data.py            # into warehouse/ and deploy/seed/

Used by Dockerfile.render: hosts that build from git (Render) don't have these
generated files, which are kept out of the repository.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {"touchline.duckdb": ROOT / "warehouse" / "touchline.duckdb",
           "passages.jsonl": ROOT / "deploy" / "seed" / "passages.jsonl"}


def main() -> None:
    manifest = json.loads((ROOT / "deploy" / "data_manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        dest = TARGETS[name]
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"{manifest['base_url']}/{name}"
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != info["sha256"]:
            sys.exit(f"{name}: checksum mismatch (got {digest}, expected {info['sha256']})")
        dest.write_bytes(data)
        print(f"{name}: {len(data):,} bytes, sha256 ok")


if __name__ == "__main__":
    main()
