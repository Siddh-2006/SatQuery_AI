# SatQuery AI — Orchestrator Design Document

**Status:** Draft v1 — reviewed with the team, about to be implemented.
**Scope:** This document covers the backend orchestrator (`orchestrator/`) that
sits between the frontend (`ui/`, see [`ui/DESIGN.md`](../ui/DESIGN.md)) and the
specialist models. It implements every endpoint in `ui/DESIGN.md` §6 exactly
as specified — the frontend needs zero changes to talk to this backend
(one additive, optional exception noted in §7).

Companion reading:
- [`ui/DESIGN.md`](../ui/DESIGN.md) — the frontend's API contract. This
  document treats that contract as fixed and does not repeat it in full.
- [`gemma4_orchestrator_instructions.md`](gemma4_orchestrator_instructions.md)
  — the real, ready-to-use system prompt for the one specialist tool that
  actually works today (EOCaptioner). Copied into
  `system_prompts/eocaptioner_s1_s2/` (§8) as the tool's canonical prompt.
- [`../SIH Idea doc.docx`](../SIH%20Idea%20doc.docx) — the problem statement
  and the full list of specialist models the team has identified (only one
  of which — EOCaptioner — has a working backend right now; see §4).

---

## Table of contents
1. [Goals & non-goals](#1-goals--non-goals)
2. [High-level architecture](#2-high-level-architecture)
3. [LLM backend: LiteRT-local vs Gemini API](#3-llm-backend-litert-local-vs-gemini-api)
4. [Tool registry — what's ready vs. stubbed](#4-tool-registry--whats-ready-vs-stubbed)
5. [Agent loop (how a query gets answered)](#5-agent-loop-how-a-query-gets-answered)
6. [Patch resolution & imagery pipeline](#6-patch-resolution--imagery-pipeline)
7. [Progress reporting — terminal + UI](#7-progress-reporting--terminal--ui)
8. [Folder layout](#8-folder-layout)
9. [Endpoint-by-endpoint mapping](#9-endpoint-by-endpoint-mapping)
10. [Persistence](#10-persistence)
11. [Configuration (env vars)](#11-configuration-env-vars)
12. [Docker / deployment](#12-docker--deployment)
13. [Known limitations / v1 scope cuts](#13-known-limitations--v1-scope-cuts)
14. [Open items / future work](#14-open-items--future-work)

---

## 1. Goals & non-goals

**Goals**
- Implement `ui/DESIGN.md` §6's API contract faithfully, so the existing
  React frontend can point `API_BASE_URL` at this backend and just work.
- Use the **LangChain** ecosystem (latest stable: `langchain` 0.3.x +
  `langchain-core`) for the LLM abstraction and tool-calling, per the
  team's decision to build the orchestrator "in lang ecosystem."
- Support **both** Gemma-4 E2B/E4B running locally via **LiteRT-LM**, and
  **Gemini API**, switchable with one environment variable — no code
  changes needed to swap.
- Wire up the one specialist tool that's actually finished — EOCaptioner
  (TerraFM vision encoder + LLM, `server/serve.py`) — using the exact
  tool-calling contract its own system prompt already defines
  (`gemma4_orchestrator_instructions.md`).
- Be honest about what isn't built yet (change detection, cross-modal
  fusion, on-demand segmentation) rather than fake it — return the
  documented `ApiError` shape with a clear message (per the team's
  decision in this planning round).
- Show the user what's happening while they wait — both in the server
  terminal and as a live status line in the UI.
- Be runnable as several small Docker containers so heavy pieces (the
  local Gemma model, the EOCaptioner/TerraFM model) can be run on a
  different, beefier machine than the lightweight orchestrator/UI.
- Simple, heavily-commented code — every file explains what it does and
  why, in plain language, so a teammate can open one file without reading
  the whole backend first (matching the standard `ui/` already set).

**Non-goals (v1)**
- Building the change-detection, cross-modal-fusion, or segmentation
  models themselves — those are separate, still-in-progress workstreams.
  This backend only needs to *not break* when asked for them (§4, §13).
- Auth/multi-tenant users — matches `ui/DESIGN.md` §9, sessions are
  identified by id only.
- Perfect production hardening (rate limiting, retries, horizontal
  scaling) — this is a hackathon deliverable; correctness and clarity
  come first.

---

## 2. High-level architecture

```
┌────────────┐   HTTP (ui/DESIGN.md §6 contract, unchanged)   ┌────────────────────┐
│  ui/ (Vite │ ──────────────────────────────────────────────▶│   orchestrator/    │
│  React app)│◀────────────────────────────────────────────── │   (FastAPI + LangChain agent)
└────────────┘         + optional SSE activity feed (§7)      └─────────┬──────────┘
                                                                          │
                                        ┌─────────────────────────────────┼───────────────────────────┐
                                        │                                 │                           │
                                        ▼                                 ▼                           ▼
                              ┌───────────────────┐          ┌─────────────────────┐      ┌──────────────────────┐
                              │  LLM backend       │          │  eocaptioner service │      │  local SQLite +      │
                              │  (env-switched)     │         │  (server/serve.py,   │      │  uploads/ + reports/ │
                              │                     │         │  TerraFM+LLM, the    │      │  (persistence, §10)  │
                              │  ─ litert-server    │         │  ONE ready tool)     │      └──────────────────────┘
                              │    (local Gemma,    │         └─────────────────────┘
                              │     own container)  │
                              │  ─ Gemini API        │
                              │    (cloud, no        │
                              │     container)        │
                              └───────────────────┘
```

Four moving pieces, each independently runnable:

| Component | What it is | Container | Can run elsewhere? |
|---|---|---|---|
| `ui` | The existing React app | `ui/Dockerfile` | Yes — static build, deploy anywhere |
| `orchestrator` | This new FastAPI + LangChain brain | `orchestrator/Dockerfile` | Yes — light, no GPU needed |
| `llm-litert` | Wraps the local `gemma-4-E2B-it.litertlm` model behind a tiny HTTP API | `orchestrator/litert_server/Dockerfile` | **Only started if `LLM_BACKEND=litert`.** Needs the 2.5GB model file mounted; benefits from a machine with decent CPU (LiteRT-LM is CPU/XNNPACK-oriented, no GPU required). |
| `eocaptioner` | The existing offline TerraFM+LLM server | `server/Dockerfile` (new) | Heaviest piece — GPU-capable machine recommended, but falls back to CPU. Independent container so it can be "outsourced" to whichever machine has the GPU. |

Why split this way: the orchestrator itself is cheap (it's just doing
prompting + HTTP calls to tools), so it can run anywhere, even a laptop.
The two model-serving pieces are the ones that need real compute — Docker
Compose profiles (§12) let you start only the ones you actually have
hardware for, and point at a remote instance of the others via env vars
instead.

---

## 3. LLM backend: LiteRT-local vs Gemini API

**Decision (confirmed this round): default is local Gemma via LiteRT.**
Gemini stays fully wired as a one-env-var swap, for anyone who wants
cloud speed or is on a machine too weak to run the local model well.

### 3.1 Why a separate `llm-litert` microservice instead of importing `litert_lm` directly in the orchestrator

The `litert_lm` Python package (see
[`gemma_models/inference.py`](gemma_models/inference.py)) is a native
inference runtime — it needs the actual `.litertlm` model file (2.5GB),
its XNNPACK cache files, and whatever native shared libraries the
`litert_lm` wheel ships. Importing that directly into the orchestrator
process would make the "lightweight brain" container just as heavy as
the model itself, and would tie the orchestrator's Python version/OS to
whatever `litert_lm` requires.

Instead, `llm-litert` is its own tiny FastAPI service
(`orchestrator/litert_server/server.py`) that:
1. Loads the `.litertlm` engine **once** at startup (mirrors
   `inference.py`'s `with llm.Engine(...) as engine:` pattern, but keeps
   the engine alive for the life of the process instead of one CLI
   session).
2. Exposes `POST /v1/chat` — takes a list of `{role, content}` messages,
   feeds them through one `engine.create_conversation()`, and returns the
   full text (or streams it, for `POST /v1/chat/stream`).
3. Nothing else. No tool-calling logic lives here — that's the
   orchestrator's job (§5). This service only ever turns "a prompt" into
   "Gemma's text reply."

The orchestrator's LangChain wrapper (`orchestrator/app/llm_litert.py`) is
then just an HTTP client wearing a `BaseChatModel` costume, so the rest of
the codebase (agent, tools, prompts) never needs to know or care which
backend is active.

### 3.2 The agent loop is a LangGraph `StateGraph`, not `AgentExecutor`

**Revision note:** the first version of this design used
`langchain.agents.AgentExecutor` (`create_react_agent` /
`create_tool_calling_agent`). It was rebuilt on **LangGraph**
(`orchestrator/app/graph.py`) instead, for three concrete reasons, not
just "because it's newer":

1. **It's what the LangChain ecosystem itself now points people to.**
   `AgentExecutor` is the legacy agent runner; LangGraph is where active
   development and the recommended patterns are, which matters given the
   brief was explicitly to build this "in the lang ecosystem, latest
   version."
2. **The retry-on-malformed-output behaviour is a real branch, not just
   "loop until done."** `gemma4_orchestrator_instructions.md` step 5 says:
   if a tool call comes back malformed for the instruction shape used
   (e.g. an MCQ instruction gets back something that isn't a lettered
   answer), retry once with a stricter template before giving up. A
   `StateGraph` expresses that directly as an edge
   (`validate_observation`, §5); `AgentExecutor`'s fixed think→act loop
   has no clean way to special-case one retry only for a *specific*
   failure shape.
3. **The graph controls tool dispatch itself, so it can pass a tool this
   turn's resolved file paths as a plain function argument.** Under
   `AgentExecutor`, a tool is only ever called with whatever arguments the
   LLM decided to pass — there was no clean way to also hand it "and
   here's where patch LUX-0417's files actually live on disk" without
   either changing the tool's LLM-visible schema (diverging from
   `gemma4_orchestrator_instructions.md`'s exact `patch_id, instruction`
   contract) or smuggling it in sideways through a `contextvars.ContextVar`
   (the earlier design's `app/request_context.py`, since deleted). With
   the graph calling tool implementations directly
   (`app/graph.py`'s `execute_tools` node → `tools/eocaptioner_tool.py`'s
   `run_eocaptioner`), that data is just... a normal argument.

### 3.3 Gemma's tool-calling: a hand-written JSON-blob loop, not native function-calling

Gemma 3n/4 E2B/E4B running through LiteRT-LM here is a plain text
completion API (see `inference.py` — `send_message_async` just streams
text chunks). There's no native "function calling" JSON-schema mode
available through this local runtime, and `query_eocaptioner` takes two
named arguments (`patch_id`, `instruction`), so a single free-text
"Action Input" string isn't enough on its own. Instead, `app/graph.py`'s
`agent_step` node (for this backend) asks the model to reply with a JSON
blob — `{"action": tool_name, "action_input": {...}}` or
`{"action": "Final Answer", "action_input": "..."}`  — and parses that
back into a structured tool call itself (`_parse_json_blob`). This is the
same idea LangChain's own (now-legacy) `create_structured_chat_agent`
used, written out by hand so the graph — not a prebuilt runner — controls
the loop, retries, and step limit. It's a good fit for Gemma regardless,
which is already comfortable with structured instruction-following (see
how strictly `gemma4_orchestrator_instructions.md` already gets it to
emit specific template shapes).

### 3.4 Gemini: native function calling

`langchain-google-genai`'s `ChatGoogleGenerativeAI` supports real
function/tool calling (`.bind_tools()`), so for this backend
`app/graph.py`'s `agent_step` node just binds the ready tools and calls
`llm.invoke(messages)` — the returned `AIMessage.tool_calls` comes back
already structured, no text parsing needed. Model name is configurable
(`GEMINI_MODEL`, default `gemini-2.5-flash` — cheap and fast; bump to a
Pro tier via env var if quality matters more than latency for a given
demo).

### 3.5 One state, one graph, backend picked per node

There's no separate "factory" module anymore — `app/graph.py`'s
`agent_step` node itself branches on `settings.llm_backend` and calls
either `_gemini_step()` or `_litert_step()`, both returning a plain
LangChain `AIMessage`. Every other node (`execute_tools`,
`validate_observation`, `compose_answer`, ...) only ever looks at that
normalized message, never at which backend produced it — see §5's graph
diagram.

---

## 4. Tool registry — what's ready vs. stubbed

From the SIH idea doc's model list, only **one** specialist has a real,
callable backend today: **EOCaptioner** (TerraFM vision encoder + a
projected LLM, `server/serve.py`), which is exactly what
`gemma4_orchestrator_instructions.md` was written for. Everything else in
the idea doc (GeoChat/TinyRS-R1, ChangeChat/DeltaVLM, MM-OVSeg/SAM,
Optical-SAR fusion) is still being trained/integrated.

`orchestrator/tools/registry.py` is the single place that decides what
the agent is allowed to call. Only tools marked `status="ready"` are
actually exposed to the LLM (rendered into the local Gemma prompt /
`.bind_tools()`'d for Gemini, via `get_ready_tool_schemas()`) or
dispatchable by the graph's `execute_tools` node
(`get_ready_tool_impls()`); everything else stays defined (for
documentation and for the day it's ready) but **not exposed to the LLM**,
so the model is never tempted to hallucinate calling something that
doesn't work.

| Tool | Backend | Status | Registered with agent? |
|---|---|---|---|
| `query_eocaptioner` | `server/serve.py` (TerraFM+LLM) | **Ready** | Yes |
| `query_change_detection` | ChangeChat/DeltaVLM | Not built | No (stub only, §8) |
| `query_cross_modal_fusion` | TerraFM dual-branch fusion | Not built | No (stub only, §8) |
| `query_segmentation` | SAM / MM-OVSeg | Not built | No (stub only, §8) |

When a request's `contextSet.type` is `bitemporal_pair` or
`cross_modal_pair`, or `groundingPreference` implies a capability none of
the *registered* tools provide, the orchestrator short-circuits **before**
even invoking the agent and returns the `unsupported_task` /
`incompatible_context` error (per this round's decision) — no point
spending an LLM call to discover what the tool registry already knows.

This also means adding a new model later is exactly three steps: drop its
system prompt + capability JSON into `system_prompts/<name>/` (§8), write
its tool function in `orchestrator/tools/`, flip its `status` to
`"ready"` in `registry.py`. Nothing else in the agent loop changes.

---

## 5. Agent loop (how a query gets answered)

`orchestrator/app/graph.py` builds one LangGraph `StateGraph` (compiled
once, reused for every request — all per-request data lives in the state
dict passed to `.invoke()`, not on the graph object itself):

```
check_compatibility --(rejected)--> reject --> END
       |(ok)
       v
resolve_patches --(failed)--> reject --> END
       |(ok)
       v
  seed_prompt
       |
       v
+--> agent_step --(final answer / step limit)--> compose_answer --> END
|         |(tool call)
|         v
|   execute_tools
|         |
|         v
+-- validate_observation
    (always loops back to agent_step -- with a corrective nudge if the
     last tool observation looked malformed and we haven't retried yet,
     otherwise plain, letting the model decide its next move)
```

For every `POST /api/query`, `api/query.py` calls `graph.run_graph(...)`,
which runs this end to end:

1. **`check_compatibility`** (`orchestrator/app/compatibility.py`) —
   mirrors the frontend's own client-side checks
   (`ui/src/api/validateContextSet.ts`) but is the *authoritative* check
   per `ui/DESIGN.md` §9's open item. Routes straight to `reject` (no LLM
   call spent) when:
   - `contextSet.type` needs a tool that isn't registered yet (§4).
   - An `uploaded_image` item is used (no registered tool can read a
     researcher's raw upload yet — see §13's honest limitation).
   - A `bandSelection` of `"sar_only"` is requested — the current
     EOCaptioner bundle always needs an optical (S2) tensor; SAR is only
     ever additive to it (`server/serve.py`'s `OfflineEOCaptioner`
     signature). Returns `incompatible_context` rather than silently
     substituting optical.
2. **`resolve_patches`** (§6) — turns the `PatchRef`/`AreaSelectionRef`
   into an actual `patch_id` the EOCaptioner tool can query (extracting
   band GeoTIFFs from the BigEarthNet zips on demand, same lazy-cache
   approach `server/serve.py` already uses for its own `/pairs/resolve`).
   A resolution failure (unknown patch, no optical capture at all) also
   routes to `reject`.
3. **`seed_prompt`** (`orchestrator/app/prompts.py`) — builds the initial
   `[SystemMessage, HumanMessage]` pair once. The system message
   concatenates:
   - A short orchestrator role/mission blurb (adapted from the SIH idea
     doc's "Agentic Model and Tool Orchestration" section).
   - Which `patch_id`(s) are available this turn and what modalities each
     has, so the agent never has to guess an id.
   - The full contents of each *registered* tool's
     `system_prompts/<name>/SYSTEM_PROMPT.md` (currently only
     `eocaptioner_s1_s2/SYSTEM_PROMPT.md`, which **is**
     `gemma4_orchestrator_instructions.md` verbatim), so the agent gets
     the exact template-shape guidance that file was carefully written to
     provide.
   - (Gemma backend only) the JSON-blob tool-calling format instructions
     from §3.3 — Gemini needs none of this, since tool calling is native.
4. **`agent_step`** (loops with `execute_tools`/`validate_observation`) —
   the LLM decides: answer directly (rare — almost every query in this
   app comes with an attached image context per `ui/DESIGN.md` §3.5) or
   call `query_eocaptioner` with a correctly-templated instruction.
   `execute_tools` dispatches the call, emitting a progress event (§7)
   before and after; `validate_observation` implements
   `gemma4_orchestrator_instructions.md` step 5's one-retry-on-malformed-
   output rule (§3.2) before looping back. A hard `MAX_AGENT_STEPS = 6`
   cap forces a stop (matching the old `AgentExecutor`'s
   `max_iterations`) so a confused local model can't hang a request
   forever.
5. **`compose_answer`** — takes the last non-tool-call `AIMessage` as
   `final_answer`. `orchestrator/app/response_builder.py` then shapes it,
   plus every `tool_calls_made` entry, into the exact `QueryResponse`
   shape (`answer`, `groundedSpans`, `evidence`, `confidence`,
   `executionTrace`, `reportUrl`):
   - `executionTrace.task` — classified from `contextSet.type` +
     which tool ran (e.g. `"vqa"`, `"captioning"`, `"grounding"`).
   - `executionTrace.modelsUsed` — `[{name: "EOCaptioner (TerraFM+LLM)",
     role: "vqa_captioning_grounding"}]` for now; will grow as more tools
     go live.
   - `evidence` — populated only when a tool call used the bounding-box
     template shape (parses the `[x0 y0, x1 y1]`-style raw answer into
     the `bbox` evidence kind); otherwise empty (a plain caption/VQA
     answer has no spatial evidence to show, which is valid per the
     type — `evidence: []` is allowed).
   - `confidence` — EOCaptioner doesn't emit a calibrated confidence
     score today, so this is a fixed, clearly-documented placeholder
     (0.75) until a real scoring signal exists (tracked in §14). Never
     fabricated to look more precise than it is.
   - `reportUrl` — generated and persisted immediately (§10) so
     "Download report" always works.
6. **Persist the turn** — `api/query.py` appends both the user and
   assistant `ChatMessage` to the session's history in SQLite (§10),
   exactly like the mock's `appendTurn` does today. (Kept in the FastAPI
   route rather than as a graph node — persistence is an HTTP-layer
   concern, not part of "how the answer gets produced.")

A rejection at step 1 or 2 raises `graph.CompatibilityError` (carrying the
exact `ApiErrorBody`), which `api/query.py` catches to return the right
`422` — see that file for why this split is cleaner than the graph
returning a response shape that's sometimes an answer and sometimes an
error.

---

## 6. Patch resolution & imagery pipeline

`orchestrator/data/patch_index.py` and `orchestrator/data/geotiff_utils.py`
adapt logic that already exists in two places in this repo, rather than
reinventing it:

- **Footprint index**: reuses the exact same fixtures the UI's mock
  already serves — `ui/src/mocks/fixtures/real-patches/{kosovo,luxembourg,
  regions}.json`, built by `ui/scripts/extract_patches.py`. The
  orchestrator reads these same JSON files (no duplicate dataset scan) to
  answer `GET /api/patches` and to know every patch's `(region, tile,
  row, col)` — encoded directly in its `patchId`, e.g.
  `"KOS-34TEN-000-041"`.
- **patchId → zip member resolution**: adapts
  `server/scripts/build_pair_index.py`'s regex-scan approach (matching
  `(tile, row, col)` out of each zip's member names — cheap, no
  decompression) to look up, on demand, which `BigEarthNet-<Region>-S1/S2
  .zip` member directory holds that exact patch for whichever date/
  product is needed.
- **Extraction + caching**: adapts `server/serve.py`'s
  `extract_patch_bands` — pulls just the needed `<patch_id>_<band>.tif`
  files out of the zip into a shared cache directory
  (`ORCHESTRATOR_CACHE_DIR`, a Docker volume shared with the
  `eocaptioner` container so it isn't re-extracted twice), skipping files
  already cached.
- **Preview rendering** (`GET /api/patches/:id/preview`): adapts
  `server/serve.py`'s `render_s2_rgb_png` for `true_color`, adds a
  `false_color` composite (swap band order to B08/B04/B03) and a `sar`
  grayscale composite (VV band, min/max stretched) — all pure
  numpy/rasterio/Pillow, no model involved, matching `ui/DESIGN.md` §2.6's
  "pre-rendered previews served by the backend."

This means the orchestrator needs read access to the same
`BigEarthNet-*.zip` files already sitting at the repo root — mounted as a
read-only volume (`BIGEARTHNET_DATA_ROOT`, §11) into both the
`orchestrator` and `eocaptioner` containers.

---

## 7. Progress reporting — terminal + UI

**Terminal**: every step in §5 logs a clear, single-line status through
Python's standard `logging` module (`orchestrator/app/progress.py`),
prefixed with the session id, e.g.:
```
[sess_9f2a] query received: "Is this place forested?"
[sess_9f2a] resolving patch LUX-0417 -> extracting S2 bands (cache miss)
[sess_9f2a] agent: calling query_eocaptioner(patch_id="LUX-0417", instruction="Does the image show mixed forest?")
[sess_9f2a] eocaptioner responded in 2.4s: "no"
[sess_9f2a] composing final answer, confidence=0.75
[sess_9f2a] done in 3.1s
```

**UI**: `POST /api/query` itself stays exactly as specified in
`ui/DESIGN.md` §6.2 (same request, same synchronous `QueryResponse`) —
this backend never breaks that contract. Live status is delivered
through one small **additive, optional** endpoint that doesn't exist in
`ui/DESIGN.md` today:

```
GET /api/sessions/:sessionId/activity   (Server-Sent Events)
  event: status
  data: {"step": "calling_tool", "detail": "query_eocaptioner(...)", "ts": "..."}
  ...
  event: done
  data: {}
```

Every progress line from `orchestrator/app/progress.py` is published to
an in-memory per-session queue (`orchestrator/app/status_bus.py`) at the
same time it's logged to the terminal — one call site, two destinations.
Each `app/graph.py` node calls `progress.report(...)` itself, right where
the work happens (e.g. `execute_tools` reports before and after each tool
call). A LangGraph `StateGraph` can also be driven with `.stream(...)` to
get its state *after* every node automatically, which was considered as a
way to derive these events centrally instead of scattering explicit
calls — deliberately not done: reconstructing the true "current state"
from a stream of partial updates means re-implementing the `messages`
field's `add_messages` reducer by hand, which is more risk than it's
worth for what a handful of explicit, obviously-correct calls already do
well at this app's scale.

Because the user explicitly asked for this to be visible in the UI too
(not just the terminal), this design includes one small, additive
frontend change: a `useOrchestratorActivity(sessionId)` hook
(`ui/src/state/useOrchestratorActivity.ts`) that opens an `EventSource` to
the endpoint above whenever `useChatStore` has an in-flight request, and a
one-line status banner in `ChatPanel` (e.g. "🛠 Calling query_eocaptioner
…") that disappears when the `done` event arrives or the request
settles. This is purely additive — nothing in `ui/src/api/types.ts` or
the existing request/response shapes changes, and the UI degrades
gracefully (just shows its existing "thinking" spinner) if this endpoint
isn't reachable at all.

---

## 8. Folder layout

```
orchestrator/
  DESIGN.md                     ← this file
  README.md                     ← quickstart: env setup, running each piece
  .env.example                  ← every env var in §11, documented inline
  Dockerfile                    ← the FastAPI orchestrator app
  requirements.txt
  gemma4_orchestrator_instructions.md   ← kept as-is; source of truth,
                                           copied verbatim into system_prompts/
  gemma_models/                 ← unchanged; the local model + inference.py
                                   the litert_server below wraps

  litert_server/                ← the small standalone LLM microservice (§3.1)
    Dockerfile
    requirements.txt
    server.py                   ← FastAPI wrapping litert_lm.Engine

  app/                          ← the orchestrator itself
    __init__.py
    main.py                     ← FastAPI app: mounts every router below, CORS,
                                   startup (loads patch index, opens DB)
    config.py                   ← Settings object, reads every env var once
    logging_utils.py            ← configures the terminal logger format
    progress.py                 ← emits one progress event -> logger + status_bus
    status_bus.py                ← in-memory per-session SSE queues (§7)
    prompts.py                   ← builds the system message text (§5 step 3)
    compatibility.py             ← authoritative context/task compatibility checks (§5 step 1)
    response_builder.py          ← graph's final state -> QueryResponse shape (§5 step 5)
    llm_litert.py                 ← LangChain BaseChatModel -> calls litert_server
    llm_gemini.py                 ← LangChain ChatGoogleGenerativeAI config
    graph.py                      ← the LangGraph StateGraph: nodes, edges, run_graph() (§5)

    api/                          ← one file per endpoint group, thin FastAPI routers
      query.py                    ← POST /api/query
      segment.py                  ← POST /api/segment (honest stub, §4/§13)
      uploads.py                  ← POST /api/uploads
      patches.py                  ← GET /api/patches, /preview, /timeseries
      reports.py                  ← GET /api/reports/:id
      sessions.py                  ← GET/POST /api/sessions, GET /api/sessions/:id
      activity.py                  ← GET /api/sessions/:id/activity (SSE, §7)

    tools/
      registry.py                  ← the ready/stub table from §4
      eocaptioner_tool.py           ← the one real tool: query_eocaptioner
      future_tools.py                ← change-detection/fusion/segmentation tool
                                        *definitions*, deliberately not registered

    data/
      patch_index.py                 ← loads the ui/ fixtures, patchId parsing (§6)
      geotiff_utils.py                 ← band loading + preview rendering (§6)
      upload_store.py                   ← saves + inspects uploaded files (§9.4)

    storage/
      db.py                             ← SQLite connection + schema (§10)
      reports.py                         ← renders + stores the downloadable report

  system_prompts/                    ← per-model system prompts + capability specs.
    README.md                          Drop a new model's prompt/capabilities here;
                                        ask to have it wired into tools/ + registry.py
                                        later — this folder is deliberately just data,
                                        no code depends on a subfolder existing yet.
    eocaptioner_s1_s2/
      SYSTEM_PROMPT.md                 ← verbatim copy of
                                          gemma4_orchestrator_instructions.md
      capabilities.json                ← machine-readable tool schema + status: ready
    change_detection_changechat/
      SYSTEM_PROMPT.md                  ← placeholder: "under development"
      capabilities.json                  ← status: not_ready
    cross_modal_fusion_terrafm/
      SYSTEM_PROMPT.md
      capabilities.json
    segmentation_sam/
      SYSTEM_PROMPT.md
      capabilities.json

  data_store/                        ← gitignored runtime data
    orchestrator.db                    (SQLite)
    uploads/
    reports/
    patch_cache/                       (extracted GeoTIFF bands, §6)
```

Plus, outside `orchestrator/`:
```
server/Dockerfile                    ← new: containerizes the existing EOCaptioner server
ui/Dockerfile                        ← new: builds + serves the existing UI
docker-compose.yml                   ← repo root; wires all of the above (§12)
```

---

## 9. Endpoint-by-endpoint mapping

| `ui/DESIGN.md` endpoint | Implementation | Notes |
|---|---|---|
| §6.2 `POST /api/query` | `app/api/query.py` → `app/graph.py` | The main event; §5 above. |
| §6.3 `POST /api/segment` | `app/api/segment.py` | Segmentation model isn't built (§4) → always returns `segmentation_failed` with a clear message, per this round's decision. Kept as a real endpoint (not 404) so the UI's existing error-handling path (`ui/DESIGN.md` §6.9) is exercised honestly. |
| §6.4 `POST /api/uploads` | `app/api/uploads.py` → `data/upload_store.py` | Real implementation: saves the file, uses `rasterio` to read CRS/transform (→ `detectedLocation`) and band count (→ best-guess `detectedModality`) for GeoTIFF/TIFF; PNG/JPEG get `null` location/modality (matches §4.2's "benchmark image" case) since they carry no geo tags. Renders a real preview thumbnail either way. |
| §6.5 `GET /api/patches` | `app/api/patches.py` → `data/patch_index.py` | Serves from the same real fixtures the UI mock already uses (§6) — bbox-filtered, real Kosovo/Luxembourg footprints, no fabricated data. |
| §6.6 `GET /api/patches/:id/preview` | `app/api/patches.py` → `data/geotiff_utils.py` | Real rendered PNGs (true_color/false_color/sar), not placeholders. |
| §6.7 `GET /api/patches/:id/timeseries` | `app/api/patches.py` → `data/patch_index.py` | Returns every real capture date the fixture has for that patch (typically the one S1+S2 visit BigEarthNet provides — see §13's honest note on why "bitemporal" is aspirational for this dataset). |
| §6.8 `GET /api/reports/:id` | `app/api/reports.py` → `storage/reports.py` | Streams a real JSON report (execution trace + answer + evidence) written at query time. |
| §8 Sessions (3 endpoints) | `app/api/sessions.py` → `storage/db.py` | Real SQLite-backed CRUD, matching `SessionSummary`/`SessionDetail` exactly. |
| *(new, additive)* `GET /api/sessions/:id/activity` | `app/api/activity.py` → `app/status_bus.py` | Not in `ui/DESIGN.md` — §7's live status feed. Frontend treats it as optional. |

---

## 10. Persistence

**SQLite** (`data_store/orchestrator.db`, via Python's built-in `sqlite3`
— no extra ORM dependency, keeps the code simple to read). Three tables:

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_updated_at TEXT NOT NULL
);

CREATE TABLE context_sets (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  type TEXT NOT NULL,             -- ContextType
  items_json TEXT NOT NULL        -- the ContextItem[] array, stored as JSON
);

CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  context_set_id TEXT NOT NULL REFERENCES context_sets(id),
  role TEXT NOT NULL,             -- "user" | "assistant"
  text TEXT NOT NULL,
  grounded_spans_json TEXT,       -- nullable, JSON
  evidence_json TEXT,             -- nullable, JSON
  confidence REAL,                -- nullable
  execution_trace_json TEXT,      -- nullable, JSON
  report_url TEXT,                -- nullable
  created_at TEXT NOT NULL
);
```

Why SQLite over a JSON file: sessions/messages are read by id constantly
(`GET /api/sessions/:id`) and appended to constantly (`POST /api/query`);
a real (if tiny) database avoids read-modify-write races on a shared JSON
blob once more than one request is in flight, while staying a single
file with zero setup — still "simple," just not naive.

Reports (`storage/reports.py`) are written as small JSON files under
`data_store/reports/<reportId>.json` at the moment a query completes
(§5 step 5), and streamed back as-is by `GET /api/reports/:id` — no
regeneration logic needed at download time.

Uploaded files live under `data_store/uploads/<fileId>/` (original file +
generated preview PNG).

---

## 11. Configuration (env vars)

All read once into one `Settings` object (`app/config.py`), documented in
`.env.example`:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BACKEND` | `litert` | `litert` \| `gemini` — the one switch from §3. |
| `LITERT_SERVER_URL` | `http://llm-litert:8090` | Where the local Gemma microservice (§3.1) listens. |
| `GEMMA_MODEL_PATH` | `gemma_models/gemma-4-E2B-it.litertlm` | Passed to `litert_server` at its own startup (not read by the orchestrator itself). |
| `GEMINI_API_KEY` | *(unset)* | Required only when `LLM_BACKEND=gemini`. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Any Gemini model id `langchain-google-genai` supports. |
| `EOCAPTIONER_URL` | `http://eocaptioner:8000` | Where `server/serve.py` listens (§4/§6). |
| `BIGEARTHNET_DATA_ROOT` | `/data/bigearthnet` | Folder holding the four `BigEarthNet-*.zip` files (read-only mount). |
| `ORCHESTRATOR_CACHE_DIR` | `/data/patch_cache` | Shared with `eocaptioner` — extracted band GeoTIFFs (§6). |
| `ORCHESTRATOR_DB_PATH` | `/data/orchestrator.db` | SQLite file (§10). |
| `UPLOAD_STORE_DIR` | `/data/uploads` | §9.4. |
| `REPORT_STORE_DIR` | `/data/reports` | §10. |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173` | Comma-separated; the Vite dev server origin by default. |
| `ORCHESTRATOR_PORT` | `8080` | FastAPI's own port. |
| `LOG_LEVEL` | `INFO` | Standard Python logging level for `progress.py` (§7). |

---

## 12. Docker / deployment

`docker-compose.yml` at the repo root, four services, using **profiles**
so nobody is forced to start pieces they don't have hardware for:

```yaml
services:
  ui:                     # always started — cheap, static
    build: ./ui
    ports: ["5173:80"]
    environment:
      - VITE_API_BASE_URL=http://localhost:8080

  orchestrator:           # always started — cheap, the brain
    build: ./orchestrator
    ports: ["8080:8080"]
    env_file: .env
    volumes:
      - ./BigEarthNet-Kosovo-S1.zip:/data/bigearthnet/BigEarthNet-Kosovo-S1.zip:ro
      - ./BigEarthNet-Kosovo-S2.zip:/data/bigearthnet/BigEarthNet-Kosovo-S2.zip:ro
      - ./BigEarthNet-Luxembourg-S1.zip:/data/bigearthnet/BigEarthNet-Luxembourg-S1.zip:ro
      - ./BigEarthNet-Luxembourg-S2.zip:/data/bigearthnet/BigEarthNet-Luxembourg-S2.zip:ro
      - patch_cache:/data/patch_cache
      - orchestrator_data:/data
    depends_on: [eocaptioner]

  llm-litert:             # only started with --profile litert (the default path)
    profiles: ["litert"]
    build: ./orchestrator/litert_server
    ports: ["8090:8090"]
    volumes:
      - ./orchestrator/gemma_models:/models:ro

  eocaptioner:            # heaviest piece — can be pointed at a remote host instead
    profiles: ["eocaptioner"]
    build: ./server
    ports: ["8000:8000"]
    volumes:
      - ./server/offline_model:/app/offline_model:ro
      - ./BigEarthNet-Kosovo-S1.zip:/app/BigEarthNet-Kosovo-S1.zip:ro
      - ./BigEarthNet-Kosovo-S2.zip:/app/BigEarthNet-Kosovo-S2.zip:ro
      - ./BigEarthNet-Luxembourg-S1.zip:/app/BigEarthNet-Luxembourg-S1.zip:ro
      - ./BigEarthNet-Luxembourg-S2.zip:/app/BigEarthNet-Luxembourg-S2.zip:ro
      - patch_cache:/app/.cache

volumes:
  patch_cache:
  orchestrator_data:
```

Usage:
```bash
# Everything on one machine (default path — local Gemma + local EOCaptioner):
docker compose --profile litert --profile eocaptioner up

# Gemini instead of local Gemma (set LLM_BACKEND=gemini + GEMINI_API_KEY in .env):
docker compose --profile eocaptioner up

# EOCaptioner running on a separate GPU box: set EOCAPTIONER_URL to that box's
# address in .env, and just don't pass --profile eocaptioner here.
docker compose --profile litert up
```

Each Dockerfile is a plain, heavily-commented `python:3.11-slim` (or
`-cpu`/`-cuda` variant for `eocaptioner`) image — no exotic build steps,
so any teammate can read the Dockerfile top-to-bottom and understand
exactly what gets installed and why.

---

## 13. Known limitations / v1 scope cuts

Documented here explicitly rather than discovered by surprise later:

- **Only single-image queries actually get an answer.** `bitemporal_pair`
  and `cross_modal_pair` context sets return `unsupported_task` — no
  change-detection or fusion model exists yet (§4). This is expected and
  matches the "under development" models in the idea doc.
- **SAR-only queries aren't supported by the current EOCaptioner bundle**
  (`bandSelection: "sar_only"`) — its encoder always requires an optical
  tensor (§5 step 1). Returns `incompatible_context`.
- **Uploaded images (`uploaded_image` context items) aren't queryable
  yet** — EOCaptioner's loader expects the exact per-band-file layout
  BigEarthNet patches come in (`<patch_id>_<band>.tif` × 12), not an
  arbitrary single GeoTIFF a researcher drops in. `POST /api/uploads`
  itself works fully (saves the file, extracts what metadata it can,
  renders a preview) — it's only *querying* an upload that isn't wired
  yet. Returns `incompatible_context` with a clear message. Tracked in
  §14 as the natural next integration once ISRO/SAC eval data needs it.
- **`POST /api/segment` always returns `segmentation_failed`** — SAM/
  MM-OVSeg isn't integrated (§4/§9). The point-segment map tool will
  visibly not work until this lands; the free-draw and footprint-select
  tools are unaffected.
- **`confidence` is a fixed placeholder (0.75)**, not a calibrated score
  — EOCaptioner doesn't produce one today. Never dressed up to look more
  precise than it is.
- **"Bitemporal" timeseries data is thin** — BigEarthNet's Kosovo/
  Luxembourg patches mostly carry one S1 + one S2 capture a day apart at
  the same location, not a genuine multi-year time series. `GET /api/
  patches/:id/timeseries` reports exactly what's real (usually 1-2
  entries) rather than fabricating more.
- **AreaSelectionRef with multiple `resolvedPatchIds`** is answered
  against only the *first* resolved patch — there's no real
  crop-to-mask inference path yet. Noted plainly in the assembled system
  prompt context so the agent doesn't imply it examined the whole area.

---

## 14. Open items / future work

- Wire up ChangeChat/DeltaVLM, TerraFM fusion, and SAM/MM-OVSeg as they
  become ready — drop each one's system prompt + capabilities.json into
  `system_prompts/` (§8) and ask for it to be integrated; the tool
  registry (§4) and agent loop (§5) need no structural changes.
- A real confidence signal — DARFT (per the idea doc) explicitly targets
  "decision-ambiguous" low-confidence cases; once available, replace the
  §13 placeholder.
- Querying an uploaded image directly (not just storing/previewing it) —
  needed once ISRO/SAC Cartosat/RISAT evaluation pairs are in play.
- `POST /api/segment` real implementation once SAM/MM-OVSeg lands.
- Swap the manual regex-scan patchId→zip resolution (§6) for a proper
  spatial/id index if patch counts grow enough that per-request zip
  namelist scans become slow (currently fine — a few thousand patches).
- Multi-worker/production ASGI serving (currently single `uvicorn`
  worker per container, matching the hackathon's needs).
