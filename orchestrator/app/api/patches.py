"""
app/api/patches.py
=====================
Three endpoints from ui/DESIGN.md §6.5-6.7, all backed by
`data/patch_index.py` + `data/geotiff_utils.py`:

- `GET /api/patches` -- footprint layer (§6.5)
- `GET /api/patches/:id/preview` -- rendered composite PNG (§6.6)
- `GET /api/patches/:id/timeseries` -- known captures at that location (§6.7)
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from data import geotiff_utils, patch_index

router = APIRouter()


@router.get("/api/patches")
async def get_patches(bbox: str | None = Query(default=None)):
    parsed_bbox = None
    if bbox:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox.split(","))
        parsed_bbox = (min_lon, min_lat, max_lon, max_lat)
    return patch_index.patches_geojson(parsed_bbox)


@router.get("/api/patches/{patch_id}/preview")
async def get_patch_preview(patch_id: str, composite: str = Query(default="true_color")):
    # NOTE: resolve_preview_sources() and render_composite_png() are both
    # wrapped in the SAME try block on purpose. An earlier version only
    # wrapped the render call, but resolve_preview_sources() is the one
    # that actually needs the BigEarthNet-*.zip files to exist -- it also
    # raises ValueError (patch_index.py's "no optical capture in the
    # archives" case, e.g. when BIGEARTHNET_DATA_ROOT is wrong or a zip
    # is missing/misnamed) and that was escaping uncaught as a raw 500
    # instead of the clear 4xx below. See patch_index.diagnose_data_root()
    # for the startup-time version of this same check.
    try:
        resolved = patch_index.resolve_preview_sources(patch_id)
        png_bytes = geotiff_utils.render_composite_png(
            resolved.s2_dir, resolved.s2_patch_id, composite, resolved.s1_dir, resolved.s1_patch_id
        )
    except KeyError:
        raise HTTPException(404, f"Unknown patch_id '{patch_id}'")
    except ValueError as e:
        raise HTTPException(
            422,
            f"{e} -- check BIGEARTHNET_DATA_ROOT (see orchestrator/README.md); "
            f"the server logged what it found for BigEarthNet zips at startup.",
        )
    return Response(content=png_bytes, media_type="image/png")


@router.get("/api/patches/{patch_id}/timeseries")
async def get_patch_timeseries(patch_id: str):
    return patch_index.timeseries_for(patch_id)
