"""
app/api/query.py
==================
`POST /api/query` -- ui/DESIGN.md §6.2, the orchestrator's main entry
point. Thin by design: this file only handles HTTP concerns (parsing the
body, mapping outcomes to status codes, persisting the turn); all the
actual thinking happens in `app/graph.py` (the LangGraph agent loop,
which includes the compatibility check as its first node -- see that
file's docstring for why this moved off `langchain.agents.AgentExecutor`).
"""
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import progress
from app.graph import CompatibilityError, run_graph
from app.response_builder import build_query_response
from storage import db

router = APIRouter()
logger = logging.getLogger("orchestrator")


@router.post("/api/query")
async def post_query(request: Request):
    body = await request.json()
    session_id = body["sessionId"]
    query_text = body["query"]
    context_set = body["contextSet"]

    # A session created client-side (POST /api/sessions) should already
    # exist, but guard against a stray/reused id anyway rather than
    # letting append_message fail on a foreign-key-less insert.
    if not db.session_exists(session_id):
        db.create_session_with_id(session_id)

    db.upsert_context_set(session_id, context_set)

    now = _now()
    user_message = {
        "id": f"msg_{uuid.uuid4().hex[:10]}",
        "role": "user",
        "text": query_text,
        "contextSetId": context_set["id"],
        "createdAt": now,
    }
    db.append_message(session_id, context_set["id"], user_message)

    try:
        final_state = run_graph(session_id, query_text, context_set)
        response = build_query_response(session_id=session_id, query=query_text, state=final_state)
    except CompatibilityError as e:
        # The graph's check_compatibility/resolve_patches node rejected this
        # request -- e.error_body is already the exact ApiErrorBody shape.
        progress.report(session_id, "rejected", e.error_body["error"]["message"])
        progress.publish_done(session_id)
        return JSONResponse(e.error_body, status_code=422)
    except Exception as e:  # pragma: no cover - genuine unexpected failure, not a compatibility case
        logger.exception("run_graph failed")
        progress.report(session_id, "error", str(e))
        progress.publish_done(session_id)
        return JSONResponse(
            {"error": {"code": "model_error", "message": f"The orchestrator failed to answer: {e}", "details": {}}},
            status_code=500,
        )

    assistant_message = {
        "id": f"msg_{uuid.uuid4().hex[:10]}",
        "role": "assistant",
        "text": response["answer"],
        "groundedSpans": response["groundedSpans"],
        "evidence": response["evidence"],
        "confidence": response["confidence"],
        "executionTrace": response["executionTrace"],
        "reportUrl": response["reportUrl"],
        "contextSetId": context_set["id"],
        "createdAt": _now(),
    }
    db.append_message(session_id, context_set["id"], assistant_message)
    progress.publish_done(session_id)

    return JSONResponse(response)


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
