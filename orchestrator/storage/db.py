"""
storage/db.py
==============
SQLite-backed session/message store. Plain `sqlite3` (standard library,
no ORM) -- see `orchestrator/DESIGN.md` §10 for why. Every function here
opens its own short-lived connection and closes it before returning
(`sqlite3` connections aren't meant to be shared across threads, and
FastAPI may run request handlers on different threads) -- simple and
correct, at the cost of a little per-call overhead that's irrelevant at
this app's scale.

Every function maps 1:1 onto something `ui/DESIGN.md` §8 (Sessions) or
§3/§6.2 (chat messages) needs, using exactly the field names
`api/sessions.py` needs to hand back to the frontend.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_sets (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    type TEXT NOT NULL,
    items_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    context_set_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    grounded_spans_json TEXT,
    evidence_json TEXT,
    confidence REAL,
    execution_trace_json TEXT,
    report_url TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.orchestrator_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Creates the schema if it doesn't exist yet. Called once at FastAPI
    startup (`app/main.py`) -- safe to call repeatedly, `CREATE TABLE IF
    NOT EXISTS` is a no-op once the tables are there."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def create_session() -> str:
    session_id = f"sess_{uuid.uuid4().hex[:10]}"
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, last_updated_at) VALUES (?, ?, ?, ?)",
            (session_id, "Untitled session", now, now),
        )
    return session_id


def create_session_with_id(session_id: str) -> None:
    """Same as `create_session()` but with a caller-supplied id -- used
    defensively by `api/query.py` if a query somehow arrives for a
    session id that was never registered via `POST /api/sessions` (should
    not happen in normal UI use, but a query shouldn't 500 over it)."""
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, created_at, last_updated_at) VALUES (?, ?, ?, ?)",
            (session_id, "Untitled session", now, now),
        )


def list_sessions() -> list[dict]:
    """Newest-first, per `ui/DESIGN.md` §8's "Load session" dropdown."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM sessions ORDER BY last_updated_at DESC").fetchall()
    return [
        {"id": r["id"], "title": r["title"], "createdAt": r["created_at"], "lastUpdatedAt": r["last_updated_at"]}
        for r in rows
    ]


def get_session_detail(session_id: str) -> Optional[dict]:
    """Returns the full `SessionDetail` shape (`ui/DESIGN.md` §8): the
    session summary plus every context set and message it's ever had."""
    with _connect() as conn:
        session_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session_row is None:
            return None
        context_rows = conn.execute("SELECT * FROM context_sets WHERE session_id = ?", (session_id,)).fetchall()
        message_rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,)
        ).fetchall()

    context_sets = [{"id": r["id"], "type": r["type"], "items": json.loads(r["items_json"])} for r in context_rows]
    messages = []
    for r in message_rows:
        msg = {
            "id": r["id"],
            "role": r["role"],
            "text": r["text"],
            "contextSetId": r["context_set_id"],
            "createdAt": r["created_at"],
        }
        if r["grounded_spans_json"] is not None:
            msg["groundedSpans"] = json.loads(r["grounded_spans_json"])
        if r["evidence_json"] is not None:
            msg["evidence"] = json.loads(r["evidence_json"])
        if r["confidence"] is not None:
            msg["confidence"] = r["confidence"]
        if r["execution_trace_json"] is not None:
            msg["executionTrace"] = json.loads(r["execution_trace_json"])
        if r["report_url"] is not None:
            msg["reportUrl"] = r["report_url"]
        messages.append(msg)

    return {
        "id": session_row["id"],
        "title": session_row["title"],
        "createdAt": session_row["created_at"],
        "lastUpdatedAt": session_row["last_updated_at"],
        "contextSets": context_sets,
        "messages": messages,
    }


def upsert_context_set(session_id: str, context_set: dict) -> None:
    """Stores (or overwrites, if the same context set id is reused) one
    `ContextSet` so `GET /api/sessions/:id` can return it later. Called
    every time a query is answered (`api/query.py`) -- a context set can
    be reused across several turns, so this is an upsert, not an insert."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO context_sets (id, session_id, type, items_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET type = excluded.type, items_json = excluded.items_json",
            (context_set["id"], session_id, context_set["type"], json.dumps(context_set["items"])),
        )


def append_message(session_id: str, context_set_id: str, message: dict) -> None:
    """Appends one `ChatMessage` (user or assistant) and bumps the
    session's `last_updated_at` so the session switcher's newest-first
    ordering (`list_sessions`) stays correct."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO messages
               (id, session_id, context_set_id, role, text, grounded_spans_json, evidence_json,
                confidence, execution_trace_json, report_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message["id"],
                session_id,
                context_set_id,
                message["role"],
                message["text"],
                json.dumps(message["groundedSpans"]) if "groundedSpans" in message else None,
                json.dumps(message["evidence"]) if "evidence" in message else None,
                message.get("confidence"),
                json.dumps(message["executionTrace"]) if "executionTrace" in message else None,
                message.get("reportUrl"),
                message["createdAt"],
            ),
        )
        conn.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (message["createdAt"], session_id))

        # The session's title is derived from its first user message, per
        # ui/DESIGN.md §8 ("titled by their first query") -- only set it
        # the first time so later turns don't keep overwriting it.
        if message["role"] == "user":
            row = conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is not None and row["title"] == "Untitled session":
                title = message["text"][:80]
                conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))


def session_exists(session_id: str) -> bool:
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None
