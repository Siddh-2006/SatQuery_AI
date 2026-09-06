"""
data/patch_index.py
=====================
The orchestrator's patch footprint index. Two jobs:

1. Serve `GET /api/patches` (+ `/preview`, `/timeseries`) straight from the
   SAME real fixture files the UI's mock backend already uses --
   `ui/src/mocks/fixtures/real-patches/{kosovo,luxembourg}.json`, built by
   `ui/scripts/extract_patches.py`. This file's `load_footprints()` /
   `patches_geojson()` are a direct Python port of
   `ui/src/mocks/fixtures/patches.ts` -- same fields, same `label` format
   -- so the real backend and the mock agree on every patch's identity.

2. Resolve a `patchId` (e.g. "KOS-34TEN-000-041") to the actual
   `BigEarthNet-*.zip` member directory + full BigEarthNet patch id that
   holds its pixels, so `geotiff_utils.extract_patch_bands` knows exactly
   what to pull out and where it goes. This mirrors
   `server/scripts/build_pair_index.py`'s regex-scan approach (matching
   (tile, row, col) in each zip's member names -- cheap, no decompression)
   but as a general patchId -> zip-member lookup, not limited to
   S1+S2-both-present pairs the way that script's "matching pairs" list is.

Everything here is read-only and cached in memory after first use (the
fixtures and the zip archives don't change while the server is running),
built with plain functions + module-level caches rather than a class --
there's exactly one of each of these, so a singleton class would just add
ceremony.
"""
import json
import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import settings

REGION_LABEL = {"KOS": "Kosovo", "LUX": "Luxembourg"}
REGION_ZIPS = {
    "KOS": {"s2": "BigEarthNet-Kosovo-S2.zip", "s1": "BigEarthNet-Kosovo-S1.zip"},
    "LUX": {"s2": "BigEarthNet-Luxembourg-S2.zip", "s1": "BigEarthNet-Luxembourg-S1.zip"},
}

# Same patterns as server/scripts/build_pair_index.py -- group(1) is the
# full BigEarthNet patch id (used both as the zip member folder name and as
# the on-disk file prefix, e.g. "..._B04.tif"), then capture date/tile/row/col.
_S2_RE = re.compile(r"(S2[AB]_MSIL2A_(\d{8})T\d{6}_N\d+_R\d+_T([0-9A-Z]+)_(\d+)_(\d+))/[^/]+\.tif$")
_S1_RE = re.compile(r"(S1[AB]_IW_GRDH_1SDV_(\d{8})T\d{6}_([0-9A-Z]+)_(\d+)_(\d+))/[^/]+_(?:VH|VV)\.tif$")


@dataclass(frozen=True)
class PatchFootprint:
    """One row of a `real-patches/*.json` fixture -- a patch's identity,
    location, and what data is actually available for it. Mirrors
    `patches.ts`'s `RawPatch` interface exactly."""

    patch_id: str
    region: str  # "KOS" | "LUX"
    tile: str
    row: int
    col: int
    lat: float
    lon: float
    polygon: list[list[float]]  # closed WGS84 ring, [lon, lat] pairs
    modalities: list[str]  # "optical" | "sar"
    timestamps: list[str]  # every real ISO capture date found for this patch

    @property
    def label(self) -> str:
        return f"{REGION_LABEL.get(self.region, self.region)} — tile {self.tile} (row {self.row}, col {self.col})"


@dataclass(frozen=True)
class ZipMemberRef:
    """Where one modality's capture of a patch actually lives on disk."""

    zip_path: Path
    member_dir: str
    full_patch_id: str  # the long BigEarthNet id, e.g. "S2A_MSIL2A_..._41_41"
    date: str


@dataclass(frozen=True)
class ResolvedPatch:
    """Everything `server/serve.py`'s `/generate` needs to answer a query
    about one patch, after extraction. `s2_dir`/`s1_dir` are real folders on
    disk (inside `settings.orchestrator_cache_dir`, a path shared with the
    eocaptioner container in Docker Compose -- see `DESIGN.md` §6)."""

    patch_id: str
    s2_dir: Optional[Path]
    s2_patch_id: Optional[str]
    s1_dir: Optional[Path]
    s1_patch_id: Optional[str]


@lru_cache(maxsize=1)
def _load_all_footprints() -> dict[str, PatchFootprint]:
    """Loads + merges both regions' fixture JSON files once, keyed by
    patchId. `lru_cache(maxsize=1)` on a zero-argument function is just a
    "compute once, remember forever" memoizer -- the standard-library
    idiom for this, no need for a hand-rolled global + None check."""
    out: dict[str, PatchFootprint] = {}
    for filename in ("kosovo.json", "luxembourg.json"):
        path = settings.patch_fixtures_dir / filename
        if not path.exists():
            continue  # matches patches.ts's graceful behaviour if a fixture is missing
        raw_list = json.loads(path.read_text(encoding="utf-8"))
        for raw in raw_list:
            out[raw["patchId"]] = PatchFootprint(
                patch_id=raw["patchId"],
                region=raw["region"],
                tile=raw["tile"],
                row=raw["row"],
                col=raw["col"],
                lat=raw["lat"],
                lon=raw["lon"],
                polygon=raw["polygon"],
                modalities=raw["modalities"],
                timestamps=raw["timestamps"],
            )
    return out


def get_patch(patch_id: str) -> Optional[PatchFootprint]:
    """Looks up one patch's footprint record, or None if unknown."""
    return _load_all_footprints().get(patch_id)


def patches_geojson(bbox: Optional[tuple[float, float, float, float]] = None) -> dict:
    """Builds the exact `PatchFeatureCollection` shape `ui/DESIGN.md` §6.5
    expects, optionally filtered to a `(minLon, minLat, maxLon, maxLat)`
    bbox -- a direct port of `patches.ts`'s `MOCK_PATCH_COLLECTION`."""
    features = []
    for p in _load_all_footprints().values():
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            if not (min_lon <= p.lon <= max_lon and min_lat <= p.lat <= max_lat):
                continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [p.polygon]},
                "properties": {
                    "patchId": p.patch_id,
                    "lat": p.lat,
                    "lon": p.lon,
                    "availableModalities": p.modalities,
                    "availableTimestamps": p.timestamps,
                    "label": p.label,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def timeseries_for(patch_id: str) -> list[dict]:
    """`GET /api/patches/:id/timeseries` data -- every real capture date
    this patch has (see `DESIGN.md` §13: BigEarthNet's dates are usually
    one S1+S2 visit a day apart, not a long time series -- this reports
    exactly what's real, never padded out)."""
    p = get_patch(patch_id)
    if p is None:
        return []
    return [{"patchId": p.patch_id, "timestamp": ts, "thumbnailUrl": f"/api/patches/{p.patch_id}/preview?composite=true_color"} for ts in p.timestamps]


def _iso_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _scan_zip(zip_path: Path, pattern: re.Pattern) -> dict[tuple[str, int, int], list[ZipMemberRef]]:
    """One namelist pass over a zip (cheap -- no decompression, just reads
    the central directory) grouping every capture by (tile, row, col)."""
    out: dict[tuple[str, int, int], list[ZipMemberRef]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        seen = set()
        for name in zf.namelist():
            m = pattern.search(name)
            if not m:
                continue
            full_patch_id, yyyymmdd, tile, row, col = m.group(1), m.group(2), m.group(3), int(m.group(4)), int(m.group(5))
            if full_patch_id in seen:
                continue  # one entry per patch, not per band file
            seen.add(full_patch_id)
            member_dir = name.rsplit("/", 1)[0]
            key = (tile, row, col)
            out.setdefault(key, []).append(
                ZipMemberRef(zip_path=zip_path, member_dir=member_dir, full_patch_id=full_patch_id, date=_iso_date(yyyymmdd))
            )
    return out


@lru_cache(maxsize=1)
def _zip_index() -> dict[str, dict[str, dict[tuple[str, int, int], list[ZipMemberRef]]]]:
    """Scans all four BigEarthNet zips once and remembers the result for
    the life of the process. Structure: `index[region]["s2" | "s1"][(tile,
    row, col)] -> [ZipMemberRef, ...]` (usually one entry; occasionally a
    few, if a location was captured more than once)."""
    index: dict[str, dict[str, dict]] = {}
    for region, zips in REGION_ZIPS.items():
        index[region] = {}
        for modality, filename in (("s2", zips["s2"]), ("s1", zips["s1"])):
            zip_path = settings.bigearthnet_data_root / filename
            if not zip_path.exists():
                index[region][modality] = {}
                continue
            pattern = _S2_RE if modality == "s2" else _S1_RE
            index[region][modality] = _scan_zip(zip_path, pattern)
    return index


def _latest_ref(refs: list[ZipMemberRef]) -> ZipMemberRef:
    return max(refs, key=lambda r: r.date)


def resolve_patch_for_query(patch_id: str, include_sar: bool) -> ResolvedPatch:
    """The main entry point `tools/eocaptioner_tool.py` calls. Given a
    short patchId and whether SAR bands are also wanted (per the context
    set's `bandSelection`), extracts whatever's needed into
    `settings.orchestrator_cache_dir` (skips extraction if already cached)
    and returns real folder paths ready to hand to `server/serve.py`.

    Raises `KeyError` if the patchId isn't in our footprint index at all,
    or `ValueError` if the index knows about it but neither zip actually
    has a matching capture (a data-integrity edge case, not expected in
    practice since the fixtures were built from these same zips).
    """
    from data.geotiff_utils import S1_BANDS, S2_BANDS, extract_patch_bands  # local import avoids a cycle at module load

    footprint = get_patch(patch_id)
    if footprint is None:
        raise KeyError(f"Unknown patch_id '{patch_id}' -- not in the patch footprint index")

    key = (footprint.tile, footprint.row, footprint.col)
    region_index = _zip_index().get(footprint.region, {})
    s2_refs = region_index.get("s2", {}).get(key, [])
    s1_refs = region_index.get("s1", {}).get(key, []) if include_sar else []

    if not s2_refs:
        raise ValueError(f"patch '{patch_id}' has no optical (S2) capture in the archives -- cannot query it")

    cache_root = settings.orchestrator_cache_dir / patch_id
    s2_ref = _latest_ref(s2_refs)
    s2_dir = cache_root / "S2"
    extract_patch_bands(s2_ref.zip_path, s2_ref.member_dir, s2_ref.full_patch_id, S2_BANDS, s2_dir)

    s1_dir = s1_patch_id = None
    if s1_refs:
        s1_ref = _latest_ref(s1_refs)
        s1_dir = cache_root / "S1"
        extract_patch_bands(s1_ref.zip_path, s1_ref.member_dir, s1_ref.full_patch_id, S1_BANDS, s1_dir)
        s1_patch_id = s1_ref.full_patch_id

    return ResolvedPatch(
        patch_id=patch_id,
        s2_dir=s2_dir,
        s2_patch_id=s2_ref.full_patch_id,
        s1_dir=s1_dir,
        s1_patch_id=s1_patch_id,
    )


def resolve_preview_sources(patch_id: str) -> ResolvedPatch:
    """Like `resolve_patch_for_query` but always includes SAR if the patch
    has it, regardless of any bandSelection -- previews (`GET
    /api/patches/:id/preview`) are just "show me what's there," not a
    query with compatibility rules attached."""
    return resolve_patch_for_query(patch_id, include_sar=True)
