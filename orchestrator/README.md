# SatQuery AI — Orchestrator

The agentic backend behind SatQuery AI. Read
[`DESIGN.md`](DESIGN.md) first — this README is just "how do I run it."

## Running everything with Docker Compose (recommended)

From the repo root (`sih_model/`):

```bash
cp orchestrator/.env.example .env
# edit .env if needed (defaults work for the local-Gemma path out of the box)

# Local Gemma + local EOCaptioner, all on this machine:
docker compose --profile litert --profile eocaptioner up --build

# Using Gemini instead of the local model (set LLM_BACKEND=gemini and
# GEMINI_API_KEY in .env first):
docker compose --profile eocaptioner up --build

# EOCaptioner running on a separate machine (set EOCAPTIONER_URL in .env
# to that machine's address, and don't start the eocaptioner profile here):
docker compose --profile litert up --build
```

Then open http://localhost:5173 (the UI) — it talks to the orchestrator
at http://localhost:8080.

See `orchestrator/DESIGN.md` §12 for the full compose layout and why it's
split into these particular pieces.

## Running without Docker (local dev)

You'll need Python 3.11+ and the four `BigEarthNet-*.zip` files at the
repo root (already there if you cloned the whole project).

**1. The orchestrator itself:**
```bash
cd orchestrator
python -m venv .venv && .venv\Scripts\activate   # Windows; use `source .venv/bin/activate` on Linux/Mac
pip install -r requirements.txt
copy .env.example .env                            # or `cp` on Linux/Mac — then edit paths to be local, not container paths
set BIGEARTHNET_DATA_ROOT=..                       # PowerShell: $env:BIGEARTHNET_DATA_ROOT=".."
python -m app.main
```
It starts on http://localhost:8080.

**2. The local Gemma model server** (only if `LLM_BACKEND=litert`, the default):
```bash
cd orchestrator/litert_server
pip install -r requirements.txt
set MODEL_PATH=../gemma_models/gemma-4-E2B-it.litertlm
python server.py
```
It starts on http://localhost:8090. (Skip this entirely if you set
`LLM_BACKEND=gemini` and `GEMINI_API_KEY` instead.)

**3. The EOCaptioner model server** (the one ready specialist tool):
```bash
cd server
pip install -r requirements.txt   # see that folder's own README/serve.py header
python serve.py --bundle offline_model --port 8000
```

**4. The UI:**
```bash
cd ui
npm install
npm run dev
```
Point it at the real backend instead of the MSW mock — see
`ui/src/main.tsx` for the one-line toggle `ui/DESIGN.md` describes.

## Folder map

See `DESIGN.md` §8 for the full layout with explanations. Quick version:
- `app/` — the FastAPI app + LangChain agent (the actual orchestrator).
- `tools/` — LangChain tool definitions; `tools/registry.py` decides
  what's actually callable today (§4).
- `data/` — turns a `patchId` into real pixels.
- `storage/` — SQLite sessions/messages + report files.
- `system_prompts/` — one folder per specialist model's instructions +
  capability spec; drop a new model's docs here when it's ready.
- `litert_server/` — the standalone local-Gemma HTTP wrapper.
- `data_store/` — gitignored runtime data (db, uploads, reports, cache).

## Adding a new specialist model later

See `DESIGN.md` §4/§14 — in short: drop its system prompt + capability
JSON into `system_prompts/<name>/`, write its real tool function in
`tools/`, flip its `capabilities.json` `status` to `"ready"`. Nothing else
in the agent loop needs to change.
