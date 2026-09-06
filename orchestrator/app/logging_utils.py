"""
app/logging_utils.py
======================
Configures Python's standard `logging` module once, at startup, so every
`logger.info(...)` call anywhere in the orchestrator prints a clean,
consistent, single-line message to the terminal -- this is the "show what
it's doing in the terminal" half of `orchestrator/DESIGN.md` §7 (the other
half, the UI status feed, is `status_bus.py`).

Deliberately not using a third-party logging library (structlog, loguru,
...) -- the standard library's `logging` does everything needed here, and
"one more dependency to explain" isn't worth it for a log line format.
"""
import logging
import sys

from app.config import settings


def configure_logging() -> None:
    """Call once, at process startup (`app/main.py`). Safe to call more
    than once -- `force=True` just replaces any earlier handlers instead
    of stacking duplicates (matters mainly under `uvicorn --reload`)."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
