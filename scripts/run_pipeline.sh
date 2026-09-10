#!/usr/bin/env bash
# scripts/run_pipeline.sh
# =========================
# Starts the ENTIRE SatQuery AI stack locally (no Docker -- see
# orchestrator/DESIGN.md §12 for the Docker Compose path instead) with one
# command: litert_server (unless LLM_BACKEND=gemini), server/serve.py
# (EOCaptioner), the orchestrator, and the UI dev server. Each service gets
# its own venv (created on first run if missing, dependencies kept in sync
# on every run), logs to logs/<service>.log, and everything is torn down
# cleanly when you press Ctrl+C (or the script exits any other way).
#
# Usage:
#   ./scripts/run_pipeline.sh                # everything, litert backend
#   ./scripts/run_pipeline.sh --gemini        # use Gemini instead of local Gemma
#   ./scripts/run_pipeline.sh --no-ui         # skip the UI dev server
#   ./scripts/run_pipeline.sh --no-eocaptioner  # skip EOCaptioner (e.g. it
#                                                # runs on a separate GPU box --
#                                                # set EOCAPTIONER_URL in .env)
#
# Reads repo-root `.env` if present (copy it from orchestrator/.env.example
# once) for LLM_BACKEND, ports, GEMINI_API_KEY, etc. -- see that file's
# "port map" section for how the *_PORT / *_URL variables relate.
#
# Run from anywhere; it resolves every path relative to the repo root
# (where this script's parent's parent lives), never relative to your
# current directory.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Config: repo-root .env (if present) + defaults matching
# orchestrator/.env.example's port map exactly.
# ---------------------------------------------------------------------------
if [ -f "$REPO_ROOT/.env" ]; then
  echo "Loading $REPO_ROOT/.env"
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

LLM_BACKEND="${LLM_BACKEND:-litert}"
ORCHESTRATOR_PORT="${ORCHESTRATOR_PORT:-8080}"
LITERT_SERVER_PORT="${LITERT_SERVER_PORT:-9001}"
EOCAPTIONER_PORT="${EOCAPTIONER_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"

RUN_UI=true
RUN_EOCAPTIONER=true
for arg in "$@"; do
  case "$arg" in
    --gemini) LLM_BACKEND=gemini ;;
    --litert) LLM_BACKEND=litert ;;
    --no-ui) RUN_UI=false ;;
    --no-eocaptioner) RUN_EOCAPTIONER=false ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (see --help)" >&2
      exit 1
      ;;
  esac
done

if [ "$LLM_BACKEND" = "gemini" ] && [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "ERROR: LLM_BACKEND=gemini but GEMINI_API_KEY is not set (in your .env)." >&2
  exit 1
fi

# The URLs the orchestrator uses to reach the other two services -- only
# defaulted here if .env didn't already set them (it does, for anyone
# following orchestrator/.env.example).
export LLM_BACKEND
export LITERT_SERVER_URL="${LITERT_SERVER_URL:-http://localhost:$LITERT_SERVER_PORT}"
export EOCAPTIONER_URL="${EOCAPTIONER_URL:-http://localhost:$EOCAPTIONER_PORT}"
export BIGEARTHNET_DATA_ROOT="${BIGEARTHNET_DATA_ROOT:-$REPO_ROOT}"
export PATCH_FIXTURES_DIR="${PATCH_FIXTURES_DIR:-$REPO_ROOT/ui/src/mocks/fixtures/real-patches}"
export ORCHESTRATOR_CACHE_DIR="${ORCHESTRATOR_CACHE_DIR:-$REPO_ROOT/orchestrator/data_store/patch_cache}"
export ORCHESTRATOR_DB_PATH="${ORCHESTRATOR_DB_PATH:-$REPO_ROOT/orchestrator/data_store/orchestrator.db}"
export UPLOAD_STORE_DIR="${UPLOAD_STORE_DIR:-$REPO_ROOT/orchestrator/data_store/uploads}"
export REPORT_STORE_DIR="${REPORT_STORE_DIR:-$REPO_ROOT/orchestrator/data_store/reports}"
export CORS_ALLOW_ORIGINS="${CORS_ALLOW_ORIGINS:-http://localhost:$UI_PORT}"
export ORCHESTRATOR_PORT

mkdir -p "$REPO_ROOT/logs"

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

# Picks a real Python interpreter to create NEW venvs with -- not just
# "python", since on Windows that name is sometimes a Microsoft Store stub
# that prints an install nag and exits non-zero instead of running.
find_base_python() {
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" --version >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

# Absolute path to a venv's own python, regardless of OS layout.
venv_python() {
  local dir="$1"
  if [ -f "$dir/Scripts/python.exe" ]; then
    printf '%s' "$dir/Scripts/python.exe"
  else
    printf '%s' "$dir/bin/python"
  fi
}

# Creates $1 (a venv dir) if missing (optionally with $3 as an extra `python
# -m venv` flag, e.g. --system-site-packages) and installs/syncs $2
# (a requirements.txt) into it. Safe to call every run -- pip skips
# already-satisfied packages, so a warm venv re-syncs in a couple seconds.
ensure_venv() {
  local dir="$1" reqs="$2" extra_flag="${3:-}"
  if [ ! -d "$dir" ]; then
    local base_py
    base_py="$(find_base_python)" || { echo "ERROR: no working Python interpreter found on PATH" >&2; exit 1; }
    echo "  [setup] creating venv: $dir"
    "$base_py" -m venv $extra_flag "$dir"
  fi
  local py
  py="$(venv_python "$dir")"
  echo "  [setup] syncing deps: $reqs"
  "$py" -m pip install --disable-pip-version-check -q -r "$reqs"
}

# Kills whatever is currently listening on $1, if anything -- used both to
# guarantee a clean slate before starting a service, and (with the same
# ports) as the definitive step in cleanup() below. Works whether the
# process is one we started or a stray leftover from a previous run;
# Windows (netstat+taskkill) and Unix (lsof+kill) both supported.
free_port() {
  local port="$1"
  if command -v netstat >/dev/null 2>&1 && command -v taskkill >/dev/null 2>&1; then
    local pid
    pid="$(netstat -ano 2>/dev/null | grep -E ":${port}[^0-9].*LISTENING" | awk '{print $NF}' | head -1)"
    if [ -n "${pid:-}" ]; then
      echo "  [port $port] in use by pid $pid -- stopping it"
      taskkill //PID "$pid" //F >/dev/null 2>&1 || true
    fi
  elif command -v lsof >/dev/null 2>&1; then
    local pid
    pid="$(lsof -ti tcp:"$port" 2>/dev/null | head -1)"
    if [ -n "${pid:-}" ]; then
      echo "  [port $port] in use by pid $pid -- stopping it"
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
}

# Best-effort "is this machine tight on RAM" check -- purely informational,
# never blocks. Running litert_server's 2.5GB model AND eocaptioner's
# TerraFM+LLM (several more GB) at once needs real headroom; on an ~8GB
# machine this was observed to exhaust memory and segfault eocaptioner
# outright (a native-code crash, not a catchable Python error) rather than
# failing cleanly. If neither /proc/meminfo (Linux) nor wmic (Windows) is
# available, this just silently does nothing rather than guessing.
warn_if_low_memory() {
  local avail_mb=""
  if [ -r /proc/meminfo ]; then
    avail_mb="$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo 2>/dev/null)"
  elif command -v wmic >/dev/null 2>&1; then
    avail_mb="$(wmic OS get FreePhysicalMemory /value 2>/dev/null | tr -d '\r' | grep -o '[0-9]\+' | head -1)"
    [ -n "$avail_mb" ] && avail_mb=$((avail_mb / 1024))
  fi
  if [ -n "$avail_mb" ] && [ "$avail_mb" -lt 4096 ]; then
    echo "  NOTE: only ~${avail_mb}MB RAM free. Running the local Gemma model AND EOCaptioner"
    echo "        together needs several GB and can crash outright on a tight machine (this was"
    echo "        observed on an 8GB dev box). If eocaptioner segfaults below, try:"
    echo "          ./scripts/run_pipeline.sh --gemini            (frees ~2.5GB by skipping local Gemma)"
    echo "          ./scripts/run_pipeline.sh --no-eocaptioner    (run it on another machine instead)"
  fi
}

# Polls $2 (a health URL) until it responds or $3 seconds pass. Never
# fails the script either way -- a slow-loading model (EOCaptioner can take
# 1-2 minutes on CPU) just gets a "still loading" note; it'll come up on
# its own and the orchestrator handles a briefly-unavailable tool gracefully.
wait_healthy() {
  local name="$1" url="$2" timeout="${3:-60}" waited=0
  printf "  waiting for %s" "$name"
  while ! curl -s -m 2 "$url" >/dev/null 2>&1; do
    sleep 2; waited=$((waited + 2)); printf "."
    if [ "$waited" -ge "$timeout" ]; then
      echo " still not ready after ${timeout}s -- continuing anyway (see logs/$name.log)"
      return 1
    fi
  done
  echo " ready"
}

# ---------------------------------------------------------------------------
# Cleanup -- runs on Ctrl+C or any exit. Frees every port this script might
# have bound, which is more reliable than tracking PIDs alone: npm and some
# venv-wrapped launches spawn through an extra process on Windows, so the
# PID `$!` captures isn't always the one actually holding the port.
# ---------------------------------------------------------------------------
cleanup() {
  echo
  echo "Stopping pipeline..."
  free_port "$UI_PORT"
  free_port "$ORCHESTRATOR_PORT"
  [ "$LLM_BACKEND" = "litert" ] && free_port "$LITERT_SERVER_PORT"
  [ "$RUN_EOCAPTIONER" = true ] && free_port "$EOCAPTIONER_PORT"
  echo "Done."
}
trap cleanup EXIT INT TERM

echo "=== SatQuery AI -- local pipeline (LLM_BACKEND=$LLM_BACKEND) ==="

# ---------------------------------------------------------------------------
# 1. Local Gemma via litert_server (skipped entirely for --gemini)
# ---------------------------------------------------------------------------
if [ "$LLM_BACKEND" = "litert" ]; then
  free_port "$LITERT_SERVER_PORT"
  # Prefer an existing gemma_models/.venv if one's already set up there
  # (avoids re-downloading the litert-lm wheel) -- else use the documented
  # canonical location and create it fresh.
  if [ -d "$REPO_ROOT/orchestrator/gemma_models/.venv" ]; then
    LITERT_VENV="$REPO_ROOT/orchestrator/gemma_models/.venv"
  else
    LITERT_VENV="$REPO_ROOT/orchestrator/litert_server/.venv"
  fi
  echo "[1/4] litert_server"
  ensure_venv "$LITERT_VENV" "$REPO_ROOT/orchestrator/litert_server/requirements.txt"
  PY_LITERT="$(venv_python "$LITERT_VENV")"
  LITERT_SERVER_PORT="$LITERT_SERVER_PORT" MODEL_PATH="$REPO_ROOT/orchestrator/gemma_models/gemma-4-E2B-it.litertlm" \
    "$PY_LITERT" "$REPO_ROOT/orchestrator/litert_server/server.py" > "$REPO_ROOT/logs/litert_server.log" 2>&1 &
  echo "      started (pid $!, log: logs/litert_server.log)"
  # Deliberately BLOCKS here until litert_server is actually up, rather than
  # firing all four services at once and checking health at the end. Model
  # loading (this + eocaptioner below) is memory/CPU-heavy enough that
  # starting them simultaneously was observed to exhaust Git-Bash's fork()
  # emulation on Windows and outright segfault one of the child processes --
  # staggering keeps peak concurrent load down.
  wait_healthy litert_server "http://localhost:$LITERT_SERVER_PORT/health" 120
else
  echo "[1/4] litert_server -- skipped (LLM_BACKEND=gemini)"
fi

# ---------------------------------------------------------------------------
# 2. EOCaptioner (server/serve.py) -- the one ready specialist tool
# ---------------------------------------------------------------------------
if [ "$RUN_EOCAPTIONER" = true ]; then
  free_port "$EOCAPTIONER_PORT"
  echo "[2/4] eocaptioner (server/serve.py) -- loads a real model, can take 1-2 min on CPU"
  [ "$LLM_BACKEND" = "litert" ] && warn_if_low_memory
  # --system-site-packages: if torch/transformers/rasterio are already
  # installed globally (e.g. from earlier training work), reuse them
  # instead of re-downloading multi-GB wheels -- harmless if they aren't.
  ensure_venv "$REPO_ROOT/server/.venv" "$REPO_ROOT/server/requirements.txt" --system-site-packages
  PY_EOCAP="$(venv_python "$REPO_ROOT/server/.venv")"
  EOCAPTIONER_PORT="$EOCAPTIONER_PORT" \
    "$PY_EOCAP" "$REPO_ROOT/server/serve.py" --bundle "$REPO_ROOT/server/offline_model" --host 0.0.0.0 \
    > "$REPO_ROOT/logs/eocaptioner.log" 2>&1 &
  echo "      started (pid $!, log: logs/eocaptioner.log)"
  # See the litert_server wait above -- same reasoning, staggered on purpose.
  wait_healthy eocaptioner "http://localhost:$EOCAPTIONER_PORT/health" 180
else
  echo "[2/4] eocaptioner -- skipped (--no-eocaptioner; make sure EOCAPTIONER_URL in .env points somewhere real)"
fi

# ---------------------------------------------------------------------------
# 3. The orchestrator itself
# ---------------------------------------------------------------------------
free_port "$ORCHESTRATOR_PORT"
echo "[3/4] orchestrator"
ensure_venv "$REPO_ROOT/orchestrator/.venv" "$REPO_ROOT/orchestrator/requirements.txt"
PY_ORCH="$(venv_python "$REPO_ROOT/orchestrator/.venv")"
# PYTHONPATH=orchestrator/, not `cd` into it, so every path this script
# computed above (all absolute, from $REPO_ROOT) stays valid regardless of
# the orchestrator process's own working directory.
PYTHONPATH="$REPO_ROOT/orchestrator" "$PY_ORCH" -m uvicorn app.main:app --host 0.0.0.0 --port "$ORCHESTRATOR_PORT" \
  > "$REPO_ROOT/logs/orchestrator.log" 2>&1 &
echo "      started (pid $!, log: logs/orchestrator.log)"
wait_healthy orchestrator "http://localhost:$ORCHESTRATOR_PORT/health" 30

# ---------------------------------------------------------------------------
# 4. The UI dev server
# ---------------------------------------------------------------------------
if [ "$RUN_UI" = true ]; then
  free_port "$UI_PORT"
  echo "[4/4] ui (vite dev server)"
  if [ ! -d "$REPO_ROOT/ui/node_modules" ]; then
    echo "  [setup] npm install (first run only)"
    npm --prefix "$REPO_ROOT/ui" install --silent
  fi
  VITE_API_BASE_URL="http://localhost:$ORCHESTRATOR_PORT" \
    npm --prefix "$REPO_ROOT/ui" run dev -- --port "$UI_PORT" > "$REPO_ROOT/logs/ui.log" 2>&1 &
  echo "      started (pid $!, log: logs/ui.log)"
  wait_healthy ui "http://localhost:$UI_PORT" 60
else
  echo "[4/4] ui -- skipped (--no-ui)"
fi

echo
echo "=== Up ==="
echo "  UI:           http://localhost:$UI_PORT"
echo "  Orchestrator: http://localhost:$ORCHESTRATOR_PORT  (GET /health for status)"
[ "$LLM_BACKEND" = "litert" ] && echo "  litert_server: http://localhost:$LITERT_SERVER_PORT"
[ "$RUN_EOCAPTIONER" = true ] && echo "  eocaptioner:   http://localhost:$EOCAPTIONER_PORT"
echo
echo "Logs are in $REPO_ROOT/logs/. Press Ctrl+C to stop everything."

# Keep the script (and therefore this terminal) alive so Ctrl+C has
# something to interrupt -- `wait` blocks on every background job started
# above, and the EXIT trap fires as soon as this returns for any reason.
wait
