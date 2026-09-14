"""
app/api/segment.py
=====================
`POST /api/segment` -- ui/DESIGN.md §6.3, backs the point-segment map tool
(§2.5). No segmentation model (SAM/MM-OVSeg) is integrated yet
(`orchestrator/DESIGN.md` §4/§13), so this endpoint has two behaviours:

- DEMO_PLACEHOLDERS=false (production, and what `main` should run): the
  honest `segmentation_failed` error rather than a fabricated mask -- kept
  as a real endpoint (not 404) so the frontend's error-handling path is
  exercised exactly as ui/DESIGN.md §6.9 describes.
- DEMO_PLACEHOLDERS=true (this demo branch): a fixed square around the
  clicked point, so the map tool can be demonstrated end-to-end.

On the placeholder shape: `SegmentResponse` has nowhere to put prose, so
`modelUsed` carries the disclaimer -- the UI renders that string in the
evidence drawer, which is the one place a viewer would look to ask "what
produced this outline". `confidence` is 0.0 for the same reason it is on a
placeholder query answer (see app/response_builder.py). The square is
deliberately a plain axis-aligned box, not a convincing organic blob: it
should be obvious at a glance that no model drew it.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter()

# Half-width of the placeholder square, in degrees. ~0.002deg is roughly
# 200m at these latitudes -- big enough to see on the map at patch zoom,
# small enough not to swamp the 1.2km BigEarthNet patch it sits in.
_PLACEHOLDER_HALF_DEG = 0.002


@router.post("/api/segment")
async def post_segment(request: Request):
    body = await request.json()
    point = body.get("point", {})

    if not settings.demo_placeholders:
        return JSONResponse(
            {
                "error": {
                    "code": "segmentation_failed",
                    "message": (
                        "On-demand segmentation isn't integrated yet (SAM/MM-OVSeg are still being trained). "
                        "Try 'Footprint select' or 'Free draw' to add an area to context instead."
                    ),
                    "details": {"point": point},
                }
            },
            status_code=422,
        )

    lat = float(point.get("lat", 0.0))
    lon = float(point.get("lon", 0.0))
    d = _PLACEHOLDER_HALF_DEG
    patch_hint = body.get("patchIdHint")

    return JSONResponse(
        {
            "geometry": {
                "type": "Polygon",
                # GeoJSON rings are [lon, lat] and must close on the first point.
                "coordinates": [
                    [
                        [lon - d, lat - d],
                        [lon + d, lat - d],
                        [lon + d, lat + d],
                        [lon - d, lat + d],
                        [lon - d, lat - d],
                    ]
                ],
            },
            "resolvedPatchIds": [patch_hint] if patch_hint else [],
            "confidence": 0.0,
            "modelUsed": "PLACEHOLDER — no segmentation model ran (SAM / MM-OVSeg not integrated yet)",
        }
    )
