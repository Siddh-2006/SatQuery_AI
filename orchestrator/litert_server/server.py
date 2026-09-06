"""
litert_server/server.py
=========================
A tiny, standalone FastAPI service that wraps the local Gemma model
(`gemma_models/gemma-4-E2B-it.litertlm`) running through Google's
LiteRT-LM runtime, and exposes it as one plain HTTP endpoint:

    POST /v1/chat   {"prompt": "..."}   ->   {"text": "..."}

This is deliberately the ONLY thing this service does -- no tool-calling,
no prompt assembly, no agent logic. All of that lives in the main
`orchestrator` app (`app/llm_factory.py`, `app/agent.py`); this service's
only job is "turn one prompt string into Gemma's text reply," exactly the
way `gemma_models/inference.py`'s little CLI loop already does, just kept
alive as a server instead of exiting after one interactive session.

See `orchestrator/DESIGN.md` §3.1 for why this is its own microservice
rather than being imported directly into the orchestrator process: the
`litert_lm` package needs the actual 2.5GB model file + native runtime
libraries, which would make the "lightweight brain" container just as
heavy as the model itself.

Run:
    cd orchestrator/litert_server
    MODEL_PATH=../gemma_models/gemma-4-E2B-it.litertlm python server.py
"""
import os
import threading

import litert_lm as llm
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_PATH = os.environ.get("MODEL_PATH", "../gemma_models/gemma-4-E2B-it.litertlm")

llm.set_min_log_severity(llm.LogSeverity.ERROR)

app = FastAPI(title="litert-gemma-server")

# The engine is a heavyweight object (loads the whole model into memory) --
# created once at startup and kept alive for the process's lifetime, unlike
# `inference.py`'s CLI which opens/closes it around one interactive session.
_engine = None
# litert_lm's Engine is not documented as thread-safe for concurrent calls,
# and FastAPI may run sync route handlers on different worker threads --
# this lock just serializes actual model calls so two requests never touch
# the engine at the same time. A hackathon-scale service only ever expects
# one query in flight at once anyway (the UI sends one at a time).
_engine_lock = threading.Lock()


@app.on_event("startup")
def load_model():
    global _engine
    _engine = llm.Engine(MODEL_PATH)
    _engine.__enter__()  # see module docstring -- kept open for the server's whole life
    print(f"Loaded {MODEL_PATH}")


@app.on_event("shutdown")
def unload_model():
    if _engine is not None:
        _engine.__exit__(None, None, None)


class ChatRequest(BaseModel):
    prompt: str


@app.get("/health")
def health():
    return {"status": "ok" if _engine is not None else "loading"}


@app.post("/v1/chat")
def chat(req: ChatRequest):
    """One prompt in, the full completion text out -- no streaming over
    this endpoint (the orchestrator's ReAct loop needs the whole answer
    before it can decide what to do next anyway, so streaming here would
    add complexity for no benefit)."""
    with _engine_lock:
        with _engine.create_conversation() as convo:
            text_parts = []
            for chunk in convo.send_message_async(req.prompt):
                text_parts.append(chunk["content"][0]["text"])
    return {"text": "".join(text_parts)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8090")))
