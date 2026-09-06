#!/usr/bin/env python3
"""Bundle the project's model weights into a single zip at the repo root.

Run this whenever the weight files listed in weights_manifest.json change.
It produces `model_weights.zip` in the repo root (already covered by
.gitignore's `*.zip` rule, so it will never be committed). Share that zip
with teammates out-of-band (drive, USB, etc.) alongside this repo; they
drop it in the repo root and run `scripts/restore_weights.py` to unpack it
back into the exact locations the code expects.

Usage:
    python scripts/package_weights.py [-o OUTPUT_ZIP]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "weights_manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "model_weights.zip"
MANIFEST_ARCNAME = "WEIGHTS_MANIFEST.json"
CHUNK_SIZE = 1024 * 1024 * 8  # 8 MB


def human(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest_files() -> list[str]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data["files"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output zip path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    relative_paths = load_manifest_files()

    missing = []
    resolved: list[Path] = []
    for rel in relative_paths:
        p = REPO_ROOT / rel
        if not p.is_file():
            missing.append(rel)
        else:
            resolved.append(p)

    if missing:
        print("ERROR: the following manifest entries are missing on disk:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1

    total_size = sum(p.stat().st_size for p in resolved)
    print(f"Packaging {len(resolved)} weight file(s), {human(total_size)} total, into {args.output}")
    print("(store-only, no compression: these files are already binary/incompressible)\n")

    manifest_entries: dict[str, dict] = {}
    started = time.time()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # allowZip64 defaults to True in modern Python, but be explicit since
    # the combined payload is well over the 4GB zip32 limit.
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for rel, p in zip(relative_paths, resolved):
            size = p.stat().st_size
            print(f"  + {rel} ({human(size)}) ... hashing", end="", flush=True)
            digest = sha256_of(p)
            print(" -> writing", end="", flush=True)
            zf.write(p, arcname=rel)
            print(" done")
            manifest_entries[rel] = {"sha256": digest, "size": size}

        zf.writestr(MANIFEST_ARCNAME, json.dumps({"files": manifest_entries}, indent=2))

    elapsed = time.time() - started
    zip_size = args.output.stat().st_size
    print(f"\nWrote {args.output} ({human(zip_size)}) in {elapsed:.0f}s")
    print("Give this file to teammates and have them run scripts/restore_weights.py "
          "after placing it in the repo root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
