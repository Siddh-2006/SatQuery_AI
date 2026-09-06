"""
app/api/activity.py
======================
`GET /api/sessions/:sessionId/activity` -- the ADDITIVE, optional live
status feed from `orchestrator/DESIGN.md` §7. Not part of ui/DESIGN.md's
documented contract; the UI degrades gracefully if this isn't consumed or
isn't reachable. Server-Sent Events (SSE): a plain, one-way,
plain-text-over-HTTP stream -- no extra library needed, just formatting
`text/event-stream` by hand, which is only a few lines.
"""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import status_bus

router = APIRouter()


@router.get("/api/sessions/{session_id}/activity")
async def get_activity(session_id: str):
    async def event_stream():
        async for event in status_bus.subscribe(session_id):
            event_name = "done" if event["step"] == "done" else "status"
            yield f"event: {event_name}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
