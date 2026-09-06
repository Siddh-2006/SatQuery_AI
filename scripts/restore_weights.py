#!/usr/bin/env python3
"""Unpack model_weights.zip back into the correct spots in this repo.

Teammates: after cloning the repo, get `model_weights.zip` from bhaskar
(it's too big for git) and drop it in the repo root (next to this
`scripts/` folder), then run:

    python scripts/restore_weights.py

It extracts each weight file to the exact relative path the code expects
(e.g. orchestrator/gemma_models/gemma-4-E2B-it.litertlm) and verifies its
sha256 checksum against the manifest embedded in the zip.

Usage:
    python scripts/restore_weights.py [ZIP_PATH] [--force]

    ZIP_PATH   defaults to <repo_root>/model_weights.zip
    --force    overwrite existing files without asking
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP = REPO_ROOT / "model_weights.zip"
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


def confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip_path", nargs="?", type=Path, default=DEFAULT_ZIP,
                         help=f"Path to model_weights.zip (default: {DEFAULT_ZIP})")
    parser.add_argument("--force", action="store_true", help="overwrite existing files without prompting")
    args = parser.parse_args()

    if not args.zip_path.is_file():
        print(f"ERROR: could not find {args.zip_path}", file=sys.stderr)
        print("Place model_weights.zip in the repo root, or pass its path explicitly.", file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.zip_path) as zf:
        try:
            manifest = json.loads(zf.read(MANIFEST_ARCNAME))["files"]
        except KeyError:
            print(f"ERROR: {args.zip_path} has no {MANIFEST_ARCNAME} — was it built with package_weights.py?",
                  file=sys.stderr)
            return 1

        total_size = sum(entry["size"] for entry in manifest.values())
        print(f"Restoring {len(manifest)} weight file(s), {human(total_size)} total, from {args.zip_path}\n")

        failures = []
        for rel, entry in manifest.items():
            dest = REPO_ROOT / rel
            size = entry["size"]

            if dest.exists() and not args.force:
                if dest.stat().st_size == size:
                    print(f"  = {rel} already present ({human(size)}), skipping")
                    continue
                if not confirm(f"  {rel} already exists with a different size — overwrite?"):
                    print(f"  - skipped {rel}")
                    continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"  + extracting {rel} ({human(size)}) ...", end="", flush=True)
            with zf.open(rel) as src, dest.open("wb") as out:
                while chunk := src.read(CHUNK_SIZE):
                    out.write(chunk)
            print(" verifying ...", end="", flush=True)
            actual = sha256_of(dest)
            if actual != entry["sha256"]:
                print(" CHECKSUM MISMATCH")
                failures.append(rel)
            else:
                print(" ok")

    if failures:
        print("\nFAILED checksum verification for:")
        for rel in failures:
            print(f"  - {rel}")
        print("Re-download model_weights.zip and try again.")
        return 1

    print("\nAll model weights restored successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
