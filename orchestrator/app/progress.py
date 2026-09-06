"""
app/progress.py
=================
One function, `report()`, called from every meaningful step of answering
a query (`app/agent.py`, `app/compatibility.py`, `data/patch_index.py`'s
callers, etc.). It does exactly two things every time:

1. Logs a clear line to the terminal (via the standard `logging` module,
   configured by `logging_utils.py`) -- so whoever is running the server
   can watch it work.
2. Publishes the same event to `status_bus.py`, so a subscribed UI client
   sees it live too (`orchestrator/DESIGN.md` §7).

Centralizing both in one call means every "here's what I'm doing" message
in the codebase automatically reaches both destinations -- nobody writing
a new step has to remember to do both separately.
"""
import logging

from app import status_bus

logger = logging.getLogger("orchestrator")


def report(session_id: str, step: str, detail: str = "") -> None:
    """`step` is a short machine-friendly tag (e.g. "classifying_task",
    "resolving_patch", "calling_tool", "composing_answer", "done") --
    `detail` is the human-readable specifics. Example:
        report(session_id, "calling_tool", "query_eocaptioner(patch_id='KOS-...', instruction='...')")
    """
    message = f"[{session_id}] {step}" + (f": {detail}" if detail else "")
    logger.info(message)
    status_bus.publish(session_id, step, detail)


def publish_done(session_id: str) -> None:
    """Thin pass-through to `status_bus.publish_done` -- kept here too so
    every call site only ever needs `from app import progress`, one import
    for both "narrate a step" and "mark this turn's activity stream over"."""
    status_bus.publish_done(session_id)
