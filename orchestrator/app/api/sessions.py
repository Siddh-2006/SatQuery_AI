"""
app/api/sessions.py
======================
The three session endpoints from ui/DESIGN.md §8, backed directly by
`storage/db.py`. Thin on purpose -- all the real logic (schema, queries)
lives in that module.
"""
from fastapi import APIRouter, HTTPException

from storage import db

router = APIRouter()


@router.get("/api/sessions")
async def get_sessions():
    return db.list_sessions()


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    detail = db.get_session_detail(session_id)
    if detail is None:
        raise HTTPException(404, "Session not found.")
    return detail


@router.post("/api/sessions")
async def post_session():
    return {"id": db.create_session()}
