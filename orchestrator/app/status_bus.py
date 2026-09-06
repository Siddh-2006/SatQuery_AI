"""
app/status_bus.py
===================
The in-memory "what is the orchestrator doing right now" pub/sub used by
`orchestrator/DESIGN.md` §7's optional live activity feed
(`GET /api/sessions/:id/activity`, an SSE endpoint -- see `api/activity.py`).

One `asyncio.Queue` per session id, created on first use and thrown away
once its subscriber disconnects. This is intentionally the simplest thing
that works for a single-process hackathon deployment -- NOT a durable
message bus. If the orchestrator ever runs as more than one worker
process, this would need to move to something shared (Redis pub/sub, most
simply) since each worker would otherwise have its own, disconnected copy
of this dict. Noted here so nobody is surprised later.

`progress.py` is the only other module that touches this file -- it calls
`publish()` every time it logs a line, so the terminal and the UI always
see the exact same sequence of steps.
"""
import asyncio
import time

_queues: dict[str, "asyncio.Queue[dict]"] = {}


def _queue_for(session_id: str) -> "asyncio.Queue[dict]":
    if session_id not in _queues:
        _queues[session_id] = asyncio.Queue()
    return _queues[session_id]


def publish(session_id: str, step: str, detail: str) -> None:
    """Pushes one status event. Safe to call even if nobody is listening
    (the queue just accumulates events, which is fine at this app's scale
    -- one query's worth of events is a handful of small dicts). Called
    from sync code sometimes (the LangChain agent callback runs
    synchronously) so this itself stays a plain sync function; `put_nowait`
    never blocks."""
    event = {"step": step, "detail": detail, "ts": time.time()}
    _queue_for(session_id).put_nowait(event)


def publish_done(session_id: str) -> None:
    """Marks the end of one query's activity stream -- `api/activity.py`
    forwards this as an SSE `event: done` so the UI's status banner knows
    to clear itself even if it can't otherwise tell the request finished."""
    _queue_for(session_id).put_nowait({"step": "done", "detail": "", "ts": time.time()})


async def subscribe(session_id: str):
    """An async generator yielding status events for `session_id` as they
    arrive -- `api/activity.py`'s SSE route just `async for`s this
    directly. Stops (via the caller cancelling the request) whenever the
    browser closes the EventSource connection; nothing needs to explicitly
    unsubscribe since asyncio handles the cancellation for us."""
    queue = _queue_for(session_id)
    while True:
        event = await queue.get()
        yield event
        if event["step"] == "done":
            return
