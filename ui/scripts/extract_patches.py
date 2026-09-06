#!/usr/bin/env python3
"""
extract_patches.py
===================
Builds `src/mocks/fixtures/real-patches/{kosovo,luxembourg}.json` — the real
patch footprints the mock `GET /api/patches` handler serves (see
`src/mocks/fixtures/patches.ts`) — straight from the delivered BigEarthNet
archives, with NO manual geocoding and no assumed patch size.

WHAT IT DOES
------------
For each region it reads two zip archives — `BigEarthNet-<Region>-S1.zip`
and `BigEarthNet-<Region>-S2.zip` — and, for every unique (UTM tile, row,
col) patch found in either one:

  1. Picks ONE representative band GeoTIFF for that patch (S2's B04, or an
     S1 VH tile if the patch has no S2 coverage) and reads its embedded
     CRS + pixel bounds directly out of the zip (no full extraction to
     disk). Each patch tif is already correctly georeferenced on its own,
     so this is the patch's real, exact footprint — not a fixed-size
     square guessed from a center point.
  2. Reprojects the four corners (and center) from the file's native UTM
     zone to WGS84 with pyproj, so the JSON is plain lon/lat the frontend
     can use directly with `map.project()`.
  3. Records which sensor(s) actually cover that patch (`optical` if it
     has an S2 tile, `sar` if it has an S1 tile) and every real capture
     date found for it across both archives.

One representative tif is read per patch (not per band/per date) — the
S1 and S2 archives share the same reference grid, so a patch's footprint
is identical across every product date that covers it; reading more than
one file per patch would just re-confirm the same bounds.

PREREQUISITES
-------------
    pip install rasterio pyproj

(Both pull prebuilt wheels on Windows/Linux/macOS — no separate GDAL
install needed.)

USAGE
-----
Run from anywhere; it locates the zips relative to `--source-root`
(default: this repo's parent directory, i.e. where the four
`BigEarthNet-*.zip` files were dropped alongside `ui/`):

    cd ui
    python scripts/extract_patches.py

Or point it at a different location (e.g. the zips live somewhere else,
or you're regenerating just one region):

    python scripts/extract_patches.py --source-root D:/some/other/folder
    python scripts/extract_patches.py --region kosovo
    python scripts/extract_patches.py --region luxembourg

Output always goes to `src/mocks/fixtures/real-patches/` next to this
script (that path is fixed — it's exactly what `patches.ts` imports).

WHEN TO RE-RUN
--------------
Only if the source zips change (a new delivery, more dates, a new
region). The app itself never runs this — `patches.ts` statically
imports the JSON this script produces, so re-running it and rebuilding
the frontend is the entire "update the data" step; there's no separate
load step at request time.
"""
import argparse
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import pyproj
import rasterio
from rasterio.io import MemoryFile

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "../src/mocks/fixtures/real-patches"

# Matches e.g. ".../S2A_MSIL2A_20171208T093351_N9999_R136_T34TEN/
#                    S2A_MSIL2A_20171208T093351_N9999_R136_T34TEN_00_41/
#                    S2A_MSIL2A_..._00_41_B04.tif"
S2_PATCH_RE = re.compile(
    r"S2[AB]_MSIL2A_(\d{8})T\d{6}_N\d+_R\d+_T([0-9A-Z]+)_(\d+)_(\d+)/"
    r"[^/]+_B\w+\.tif$"
)
# Matches e.g. ".../S1A_IW_GRDH_1SDV_20171207T162425_34TEN_10_85/
#                    S1A_IW_GRDH_1SDV_..._10_85_VH.tif"
S1_PATCH_RE = re.compile(
    r"S1[AB]_IW_GRDH_1SDV_(\d{8})T\d{6}_([0-9A-Z]+)_(\d+)_(\d+)/"
    r"[^/]+_(?:VH|VV)\.tif$"
)

REGIONS = {
    "kosovo": {"code": "KOS", "s2_zip": "BigEarthNet-Kosovo-S2.zip", "s1_zip": "BigEarthNet-Kosovo-S1.zip"},
    "luxembourg": {"code": "LUX", "s2_zip": "BigEarthNet-Luxembourg-S2.zip", "s1_zip": "BigEarthNet-Luxembourg-S1.zip"},
}


def iso_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def scan_zip(zf: zipfile.ZipFile, pattern: re.Pattern, band_hint: str):
    """One pass over a zip's member names (cheap — no decompression) that
    groups every band/date entry by (tile, row, col) and remembers one
    member path per patch worth actually reading (the first match of
    `band_hint`, e.g. "_B04.tif")."""
    out: dict = defaultdict(lambda: {"dates": set(), "ref_member": None})
    for name in zf.namelist():
        m = pattern.search(name)
        if not m:
            continue
        date, tile, row, col = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        key = (tile, row, col)
        out[key]["dates"].add(iso_date(date))
        if out[key]["ref_member"] is None and band_hint in name:
            out[key]["ref_member"] = name
    return out


def read_bounds(zf: zipfile.ZipFile, member: str):
    """Reads just one band tif's CRS + pixel bounds — via an in-memory
    GDAL virtual file, never written to disk."""
    data = zf.read(member)
    with MemoryFile(data) as mf, mf.open() as ds:
        return ds.crs, ds.bounds


def build_region(region_code: str, s2_zip_path: Path, s1_zip_path: Path):
    print(f"=== {region_code} ===", flush=True)
    # Kept open for the whole region (re-opening a zip per patch, instead
    # of once, was the difference between ~20s and multiple minutes here —
    # ZipFile.__init__ re-parses the central directory every time).
    with zipfile.ZipFile(s2_zip_path) as zf_s2, zipfile.ZipFile(s1_zip_path) as zf_s1:
        s2 = scan_zip(zf_s2, S2_PATCH_RE, band_hint="_B04.tif")
        s1 = scan_zip(zf_s1, S1_PATCH_RE, band_hint="_VH.tif")
        print(f"  S2 unique patches: {len(s2)}  S1 unique patches: {len(s1)}", flush=True)

        all_keys = sorted(set(s2.keys()) | set(s1.keys()))
        transformer_cache: dict = {}
        records = []
        overall_bbox = [180.0, 90.0, -180.0, -90.0]  # minLon, minLat, maxLon, maxLat

        for i, key in enumerate(all_keys):
            tile, row, col = key
            entry_s2, entry_s1 = s2.get(key), s1.get(key)

            # Prefer the S2 reference tif (10m, tiny file); fall back to S1
            # only for the rare patch with no S2 coverage at all.
            if entry_s2 and entry_s2["ref_member"]:
                ref_zf, ref_member = zf_s2, entry_s2["ref_member"]
            elif entry_s1 and entry_s1["ref_member"]:
                ref_zf, ref_member = zf_s1, entry_s1["ref_member"]
            else:
                continue  # shouldn't happen — every key came from one of the two scans

            crs, bounds = read_bounds(ref_zf, ref_member)
            crs_key = str(crs)
            if crs_key not in transformer_cache:
                transformer_cache[crs_key] = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            tr = transformer_cache[crs_key]

            left, bottom, right, top = bounds.left, bounds.bottom, bounds.right, bounds.top
            corners_utm = [(left, bottom), (right, bottom), (right, top), (left, top)]
            corners_ll = [tr.transform(x, y) for x, y in corners_utm]
            clon, clat = tr.transform((left + right) / 2, (bottom + top) / 2)

            for lon, lat in corners_ll:
                overall_bbox[0] = min(overall_bbox[0], lon)
                overall_bbox[1] = min(overall_bbox[1], lat)
                overall_bbox[2] = max(overall_bbox[2], lon)
                overall_bbox[3] = max(overall_bbox[3], lat)

            modalities = []
            if entry_s2:
                modalities.append("optical")
            if entry_s1:
                modalities.append("sar")
            timestamps = sorted((entry_s2["dates"] if entry_s2 else set()) | (entry_s1["dates"] if entry_s1 else set()))

            records.append({
                "patchId": f"{region_code}-{tile}-{row:03d}-{col:03d}",
                "region": region_code,
                "tile": tile,
                "row": row,
                "col": col,
                "lat": round(clat, 6),
                "lon": round(clon, 6),
                # Closed WGS84 ring — the patch's real, exact footprint.
                "polygon": [[round(lon, 6), round(lat, 6)] for lon, lat in corners_ll + [corners_ll[0]]],
                "modalities": modalities,
                "timestamps": timestamps,
            })

            if (i + 1) % 200 == 0:
                print(f"  ... {i + 1}/{len(all_keys)}", flush=True)

    print(f"  built {len(records)} records; bbox={overall_bbox}", flush=True)
    return records, overall_bbox


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=SCRIPT_DIR / "../..",
        help="Folder containing the BigEarthNet-*.zip files (default: this repo's parent directory).",
    )
    parser.add_argument(
        "--region",
        choices=["kosovo", "luxembourg", "all"],
        default="all",
        help="Which region to (re)build (default: all).",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    region_bboxes = {}
    # Preserve whichever region(s) we're not regenerating this run.
    regions_json_path = OUTPUT_DIR / "regions.json"
    if regions_json_path.exists():
        region_bboxes = json.loads(regions_json_path.read_text())

    targets = REGIONS.keys() if args.region == "all" else [args.region]
    for name in targets:
        cfg = REGIONS[name]
        records, bbox = build_region(
            cfg["code"],
            args.source_root / cfg["s2_zip"],
            args.source_root / cfg["s1_zip"],
        )
        (OUTPUT_DIR / f"{name}.json").write_text(json.dumps(records))
        region_bboxes[cfg["code"]] = bbox

    regions_json_path.write_text(json.dumps(region_bboxes, indent=2))
    print(f"\nWrote {', '.join(targets)} to {OUTPUT_DIR}")
    print("Rebuild/restart the frontend dev server to pick up the new fixture data.")


if __name__ == "__main__":
    main()
