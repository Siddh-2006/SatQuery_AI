"""
orchestrator/app
=================
The orchestrator's own Python package. Everything that answers
`ui/DESIGN.md`'s API contract lives under here. See `orchestrator/DESIGN.md`
for the full architecture write-up -- this package docstring only gives the
one-paragraph version:

`main.py` builds the FastAPI app and mounts one router per endpoint group
(`api/`). Each request that needs the LLM goes through `agent.py`, which
picks a backend via `llm_factory.py` (local Gemma via LiteRT, or Gemini --
switched with the `LLM_BACKEND` env var) and runs a LangChain agent bound
to whichever tools are marked "ready" in `tools/registry.py`. Imagery is
resolved to real files by `data/`, and everything durable (sessions,
messages, reports) is stored by `storage/`.
"""
