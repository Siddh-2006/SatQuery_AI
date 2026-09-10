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
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import activity, patches, query, reports, segment, sessions, uploads
from app.config import settings
from app.logging_utils import configure_logging
from data.patch_index import data_root_status, diagnose_data_root
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

    # Loud, up-front data check (orchestrator/DESIGN.md §6) -- a missing or
    # misplaced BigEarthNet-*.zip / patch fixture JSON is the #1 cause of
    # "it works on my machine but not my teammate's": patch footprints and
    # previews fail silently/per-request otherwise (see git history on
    # app/api/patches.py for the bug this used to hide behind). Printed
    # once here so it's the first thing anyone sees in the terminal.
    logger = logging.getLogger("orchestrator")
    logger.info("Checking BigEarthNet data files...")
    for line in diagnose_data_root():
        logger.info(line)
    status = data_root_status()
    if status["zipsFound"] < status["zipsExpected"]:
        logger.warning(
            "Only %d/%d BigEarthNet zip files found -- patch PREVIEWS will fail (422) for any patch in a "
            "missing region. Footprints/map still work (those come from the fixture JSONs, which ARE in git).",
            status["zipsFound"], status["zipsExpected"],
        )
    if status["fixturesFound"] < status["fixturesExpected"]:
        logger.warning(
            "Only %d/%d patch fixture JSON files found -- the map's footprint layer will be empty or incomplete.",
            status["fixturesFound"], status["fixturesExpected"],
        )


@app.get("/health")
def health():
    """Simple liveness probe -- also handy for `docker compose` health
    checks and for confirming which LLM backend is currently active. Also
    reports how many of the 4 BigEarthNet zips / 3 fixture JSONs were
    actually found (`data/patch_index.diagnose_data_root`'s machine-
    readable form) -- checkable remotely (e.g. by a teammate over
    screenshare) without needing terminal/log access."""
    return {"status": "ok", "llmBackend": settings.llm_backend, "dataStatus": data_root_status()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.orchestrator_port, reload=False)
