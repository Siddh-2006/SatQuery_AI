"""
app/api/segment.py
=====================
`POST /api/segment` -- ui/DESIGN.md §6.3, backs the point-segment map tool
(§2.5). Per this planning round's decision (`orchestrator/DESIGN.md`
§4/§13), no segmentation model (SAM/MM-OVSeg) is integrated yet, so this
always returns the honest `segmentation_failed` error rather than a
fabricated mask -- kept as a real endpoint (not 404) so the frontend's
existing error-handling path is exercised exactly as ui/DESIGN.md §6.9
describes.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/api/segment")
async def post_segment(request: Request):
    body = await request.json()
    point = body.get("point", {})
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
