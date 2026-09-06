#!/usr/bin/env python3
"""
build_pair_index.py
====================
Builds `server/static/pairs.json` — every Kosovo/Luxembourg location that
has BOTH a Sentinel-1 (SAR) and a Sentinel-2 (optical) patch, so the tester
UI (static/index.html) can offer a "pick a matching pair" dropdown instead
of making you type/find matching S1 and S2 folder paths + patch IDs by
hand.

WHAT COUNTS AS "MATCHING"
-------------------------
BigEarthNet-S1 and BigEarthNet-S2 cut their patches from the same
reference grid per region (same UTM tile, same row/col numbering), so two
patches with the same (tile, row, col) are the exact same real-world
footprint regardless of which product/date they came from. For each such
location this script pairs the (latest, if more than one) S2 capture with
whichever S1 capture at that same location is closest in time to it —
that's the sensible "same place, same-ish time" pair for cross-modal
testing, since a raw location can have several S1 dates but often just
one S2 date (or vice versa).

This only RECORDS which zip + which member folder each side lives in —
it does not extract anything. Actually pulling files out of the archives
happens lazily, in serve.py's `GET /pairs/resolve`, the first time a
given pair is actually selected in the UI (see that endpoint's docstring)
— building this index is instant; extracting every patch's bands up front
for thousands of pairs nobody may pick would not be.

USAGE
-----
    cd server
    python scripts/build_pair_index.py
    python scripts/build_pair_index.py --source-root D:/elsewhere
    python scripts/build_pair_index.py --region kosovo

Re-run only if the source BigEarthNet-*.zip files change. `serve.py` reads
the resulting static/pairs.json fresh on every `/pairs` request, so no
server restart is needed after regenerating it.
"""
import argparse
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR / "../static/pairs.json"

# Captures the full patch id (used as both the zip folder name and the
# on-disk file prefix, e.g. "..._B04.tif") plus its date/tile/row/col.
S2_RE = re.compile(
    r"(S2[AB]_MSIL2A_(\d{8})T\d{6}_N\d+_R\d+_T([0-9A-Z]+)_(\d+)_(\d+))/[^/]+\.tif$"
)
S1_RE = re.compile(
    r"(S1[AB]_IW_GRDH_1SDV_(\d{8})T\d{6}_([0-9A-Z]+)_(\d+)_(\d+))/[^/]+_(?:VH|VV)\.tif$"
)

REGIONS = {
    "kosovo": {"code": "KOS", "label": "Kosovo", "s2_zip": "BigEarthNet-Kosovo-S2.zip", "s1_zip": "BigEarthNet-Kosovo-S1.zip"},
    "luxembourg": {"code": "LUX", "label": "Luxembourg", "s2_zip": "BigEarthNet-Luxembourg-S2.zip", "s1_zip": "BigEarthNet-Luxembourg-S1.zip"},
}


def iso_date(yyyymmdd: str) -> date:
    return date(int(yyyymmdd[0:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))


def scan(zip_path: Path, pattern: re.Pattern):
    """dict[(tile,row,col)] -> list of {date, patch_id, member_dir}, one
    entry per product/date that covers that location (there can be more
    than one — see the module docstring)."""
    import zipfile

    out: dict = defaultdict(list)
    with zipfile.ZipFile(zip_path) as zf:
        seen_patch_ids = set()
        for name in zf.namelist():
            m = pattern.search(name)
            if not m:
                continue
            patch_id, yyyymmdd, tile, row, col = m.group(1), m.group(2), m.group(3), int(m.group(4)), int(m.group(5))
            if patch_id in seen_patch_ids:
                continue  # one entry per patch, not per band file
            seen_patch_ids.add(patch_id)
            member_dir = name.rsplit("/", 1)[0]
            out[(tile, row, col)].append({"date": iso_date(yyyymmdd), "patch_id": patch_id, "member_dir": member_dir})
    return out


def build_region(name: str, cfg: dict, source_root: Path):
    print(f"=== {cfg['label']} ===", flush=True)
    s2 = scan(source_root / cfg["s2_zip"], S2_RE)
    s1 = scan(source_root / cfg["s1_zip"], S1_RE)
    print(f"  S2 locations: {len(s2)}  S1 locations: {len(s1)}", flush=True)

    pairs = []
    for key in sorted(set(s2.keys()) & set(s1.keys())):
        tile, row, col = key
        # Latest S2 capture at this location (usually there's only one).
        s2_entry = max(s2[key], key=lambda e: e["date"])
        # Whichever S1 capture at this SAME location is closest in time to it.
        s1_entry = min(s1[key], key=lambda e: abs((e["date"] - s2_entry["date"]).days))

        pairs.append({
            "id": f"{cfg['code']}-{tile}-{row:03d}-{col:03d}",
            "region": cfg["label"],
            "tile": tile,
            "row": row,
            "col": col,
            "s2": {
                "zip": cfg["s2_zip"],
                "member_dir": s2_entry["member_dir"],
                "patch_id": s2_entry["patch_id"],
                "date": s2_entry["date"].isoformat(),
            },
            "s1": {
                "zip": cfg["s1_zip"],
                "member_dir": s1_entry["member_dir"],
                "patch_id": s1_entry["patch_id"],
                "date": s1_entry["date"].isoformat(),
            },
            "day_gap": abs((s2_entry["date"] - s1_entry["date"]).days),
        })

    print(f"  built {len(pairs)} matching pairs", flush=True)
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-root", type=Path, default=SCRIPT_DIR.parents[1],
        help="Folder containing the BigEarthNet-*.zip files (default: this repo's root).",
    )
    parser.add_argument("--region", choices=[*REGIONS.keys(), "all"], default="all")
    args = parser.parse_args()

    all_pairs = []
    targets = REGIONS.items() if args.region == "all" else [(args.region, REGIONS[args.region])]
    for name, cfg in targets:
        all_pairs.extend(build_region(name, cfg, args.source_root))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(all_pairs))
    print(f"\nWrote {len(all_pairs)} pairs to {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
