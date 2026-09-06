# System prompts & capability specs — one folder per specialist model

Each subfolder here describes ONE specialist model the orchestrator might
call as a tool. A subfolder always has exactly two files:

- `SYSTEM_PROMPT.md` — the natural-language instructions that tell the
  orchestrator LLM *how* to use this specific tool correctly (what query
  shapes it accepts, how to phrase things, common mistakes to avoid,
  few-shot examples). This is the same kind of document as
  [`../gemma4_orchestrator_instructions.md`](../gemma4_orchestrator_instructions.md)
  (in fact, `eocaptioner_s1_s2/SYSTEM_PROMPT.md` IS that file, copied
  verbatim) — written by whoever trained/integrated that model, since
  they know its quirks best.
- `capabilities.json` — a small machine-readable file the orchestrator
  code actually reads (`orchestrator/tools/registry.py`), recording:
  - `"status"`: `"ready"` or `"not_ready"` — whether this model has a real
    backend to call yet. Only `"ready"` tools are ever bound to the LLM
    agent (see `orchestrator/DESIGN.md` §4) — this is what stops the
    agent from hallucinating a call to something that doesn't exist.
  - `"tool_name"`, `"description"`, `"parameters"` — the JSON-schema-ish
    shape of the tool call itself.
  - `"backend_url_env"` — which environment variable points at this
    model's HTTP server, if it has one.

## Why this folder exists

Right now only `eocaptioner_s1_s2/` is `"ready"` — every other specialist
model in the SIH idea doc (change detection, cross-modal fusion,
segmentation) is still being trained/integrated by other teammates. This
folder is deliberately just **data**, with no code depending on any
particular subfolder existing — so the moment one of those models is
ready:

1. Drop its `SYSTEM_PROMPT.md` + `capabilities.json` in a new subfolder
   here (or update an existing stub's `capabilities.json` `status` field
   to `"ready"` and fill in its real details).
2. Ask for it to be wired into `orchestrator/tools/` (write the actual
   Python tool function that calls its backend) and flip its entry in
   `orchestrator/tools/registry.py`.

Nothing else in the orchestrator's agent loop needs to change — see
`orchestrator/DESIGN.md` §4 and §14.
