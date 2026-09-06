"""
app/api/reports.py
=====================
`GET /api/reports/:reportId` -- ui/DESIGN.md §6.8. Streams back the exact
JSON file `app/response_builder.py` wrote at query time
(`storage/reports.py`) -- no regeneration logic here at all.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from storage.reports import read_report_bytes

router = APIRouter()


@router.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    content = read_report_bytes(report_id)
    if content is None:
        raise HTTPException(404, f"Unknown report id '{report_id}'")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{report_id}.json"'},
    )
