"""
app/main.py
=============
The FastAPI application entry point. Run with:

    cd orchestrator
    uvicorn app.main:app --host 0.0.0.0 --port 8080

(or just `python -m app.main`, see the bottom of this file). Mounts one
router per endpoint group (`app/api/*.py`), configures CORS for the Vite
dev server, and initializes the SQLite schema on startup. See
`orchestrator/DESIGN.md` for the full architecture this ties together.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import activity, patches, query, reports, segment, sessions, uploads
from app.config import settings
from app.logging_utils import configure_logging
from storage.db import init_db

configure_logging()

app = FastAPI(
    title="SatQuery AI — Orchestrator",
    description="Agentic remote-sensing orchestrator implementing ui/DESIGN.md's API contract. See orchestrator/DESIGN.md.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One router per endpoint group -- see app/api/__init__.py for why each
# stays a thin, plain-dict-based FastAPI route rather than a heavier
# Pydantic-modeled one.
app.include_router(query.router)
app.include_router(segment.router)
app.include_router(uploads.router)
app.include_router(patches.router)
app.include_router(reports.router)
app.include_router(sessions.router)
app.include_router(activity.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health():
    """Simple liveness probe -- also handy for `docker compose` health
    checks and for confirming which LLM backend is currently active."""
    return {"status": "ok", "llmBackend": settings.llm_backend}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.orchestrator_port, reload=False)
