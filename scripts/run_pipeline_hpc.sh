#!/usr/bin/env bash
#SBATCH --job-name=satquery
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=04:00:00
#SBATCH --output=slurm-satquery-%j.out
#
# scripts/run_pipeline_hpc.sh
# ===========================
# The HPC/Slurm counterpart of scripts/run_pipeline.sh: the same four services
# (litert_server, EOCaptioner, orchestrator, UI), but running inside a Slurm
# batch job on a GPU node instead of on your laptop.
#
#   ./scripts/run_pipeline_hpc.sh              # set up, submit, print how to connect
#   ./scripts/run_pipeline_hpc.sh --time 08:00:00 --gres gpu:h100:1
#   ./scripts/run_pipeline_hpc.sh --setup-only # just build the envs, don't submit
#   ./scripts/run_pipeline_hpc.sh --gemini     # Gemini instead of local Gemma
#   ./scripts/run_pipeline_hpc.sh --no-ui      # orchestrator API only, no web UI
#
# ONE FILE, TWO MODES -- it re-executes itself under Slurm:
#
#   submit mode  (you run it on the LOGIN node; $SLURM_JOB_ID is unset)
#                installs/syncs the Python envs and node_modules -- the steps
#                that need the internet, which login nodes have and compute
#                nodes usually don't -- then `sbatch`es this same file and
#                waits until the job is RUNNING to print your tunnel command.
#
#   job mode     (Slurm runs it on the COMPUTE node; $SLURM_JOB_ID is set)
#                activates conda, picks a free port block, starts the four
#                services, and blocks until the job ends or is scancel'd.
#
# WHY IT DIFFERS FROM run_pipeline.sh (each of these is a real HPC constraint,
# not a stylistic choice):
#
#   * conda, not per-service venvs from scratch. EOCaptioner runs in the
#     existing `eocaptioner` conda env, which already has a CUDA-matched
#     torch -- never pip-install torch over a cluster's tuned build. The
#     orchestrator and litert_server still get their own small venvs, because
#     all three services pin DIFFERENT fastapi versions (0.111 / 0.115 /
#     0.141) and cannot share one environment; those venvs are created from
#     the conda env's interpreter, so it stays one Python version throughout.
#
#   * Ports are derived from your UID, not fixed at 8080/9001/8000/5173.
#     A GPU node can host other people's jobs, and you cannot kill their
#     process off "your" port the way run_pipeline.sh's free_port does -- so
#     this claims a private 4-port block and shifts it if it's taken.
#
#   * The UI is a production build served statically, NOT `vite dev`.
#     ui/src/main.tsx starts Mock Service Worker whenever import.meta.env.DEV
#     is true, so a dev server answers every /api call from fixtures and never
#     reaches the orchestrator at all. A production build turns mocks off; it
#     also needs no Node at runtime, which matters because compute nodes don't
#     always carry the same toolchain as login nodes.
#
#   * Services bind 0.0.0.0 on the compute node and you reach them over an SSH
#     tunnel. That is also why VITE_API_BASE_URL is baked as
#     http://localhost:<orchestrator port>: the UI's fetches run in the browser
#     on YOUR machine, so they must target your end of the tunnel, not the
#     node's hostname (which your laptop can't resolve anyway).
#
# Knobs (flag, or env var, or repo-root .env -- in that order of precedence):
#   SATQUERY_CONDA_ENV   conda env for EOCaptioner        (default: eocaptioner)
#   SATQUERY_PORT_BASE   first port of the 4-port block   (default: from your UID)
#   SATQUERY_ENV_ROOT    where the two venvs live         (default: <repo>/.hpc-envs)
#   SATQUERY_DATA_ROOT   folder with the BigEarthNet zips (default: <repo>)
#   SATQUERY_MODULES     `module load` these first        (e.g. "cuda/12.4 nodejs/20")
set -uo pipefail

# ---------------------------------------------------------------------------
# Repo root. In job mode $BASH_SOURCE is USELESS: Slurm copies the batch
# script into its spool dir (/var/spool/slurmd/job*/slurm_script), so it no
# longer sits next to the repo. Submit mode exports SATQUERY_REPO_ROOT for the
# job to inherit (sbatch --export=ALL), with $SLURM_SUBMIT_DIR as the fallback
# for anyone who ran `sbatch scripts/run_pipeline_hpc.sh` by hand.
# ---------------------------------------------------------------------------
if [ -n "${SATQUERY_REPO_ROOT:-}" ]; then
  REPO_ROOT="$SATQUERY_REPO_ROOT"
elif [ -n "${SLURM_JOB_ID:-}" ]; then
  REPO_ROOT="${SLURM_SUBMIT_DIR:-$PWD}"
else
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$REPO_ROOT" || { echo "ERROR: repo root '$REPO_ROOT' is not reachable" >&2; exit 1; }

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

CONDA_ENV_NAME="${SATQUERY_CONDA_ENV:-eocaptioner}"
ENV_ROOT="${SATQUERY_ENV_ROOT:-$REPO_ROOT/.hpc-envs}"
DATA_ROOT="${SATQUERY_DATA_ROOT:-${BIGEARTHNET_DATA_ROOT:-$REPO_ROOT}}"
LLM_BACKEND="${LLM_BACKEND:-litert}"
HPC_LOG_ROOT="$REPO_ROOT/logs/hpc"

# Slurm resources -- defaults mirror the #SBATCH block above; every one is
# overridable because partition/account/gres names are cluster-specific.
SBATCH_TIME="${SATQUERY_TIME:-04:00:00}"
SBATCH_GRES="${SATQUERY_GRES:-gpu:1}"
SBATCH_CPUS="${SATQUERY_CPUS:-8}"
SBATCH_MEM="${SATQUERY_MEM:-64G}"
SBATCH_PARTITION="${SATQUERY_PARTITION:-}"
SBATCH_ACCOUNT="${SATQUERY_ACCOUNT:-}"
SBATCH_QOS="${SATQUERY_QOS:-}"

RUN_UI=true
RUN_EOCAPTIONER=true
DO_SETUP=true
SETUP_ONLY=false
WAIT_FOR_START=true

while [ $# -gt 0 ]; do
  case "$1" in
    --gemini) LLM_BACKEND=gemini ;;
    --litert) LLM_BACKEND=litert ;;
    --no-ui) RUN_UI=false ;;
    --no-eocaptioner) RUN_EOCAPTIONER=false ;;
    --no-setup) DO_SETUP=false ;;
    --setup-only) SETUP_ONLY=true ;;
    --no-wait) WAIT_FOR_START=false ;;
    --time) SBATCH_TIME="$2"; shift ;;
    --gres) SBATCH_GRES="$2"; shift ;;
    --cpus) SBATCH_CPUS="$2"; shift ;;
    --mem) SBATCH_MEM="$2"; shift ;;
    --partition|-p) SBATCH_PARTITION="$2"; shift ;;
    --account|-A) SBATCH_ACCOUNT="$2"; shift ;;
    --qos) SBATCH_QOS="$2"; shift ;;
    --conda-env) CONDA_ENV_NAME="$2"; shift ;;
    --port-base) SATQUERY_PORT_BASE="$2"; shift ;;
    --module) SATQUERY_MODULES="${SATQUERY_MODULES:-} $2"; shift ;;
    -h|--help)
      sed -n '/^# scripts\/run_pipeline_hpc.sh/,/^set -uo pipefail/p' "${BASH_SOURCE[0]}" \
        | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 1 ;;
  esac
  shift
done

if [ "$LLM_BACKEND" = "gemini" ] && [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "ERROR: LLM_BACKEND=gemini but GEMINI_API_KEY is not set (in your .env)." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Sources conda's shell hook and activates $1. `conda activate` is a shell
# FUNCTION, not the `conda` binary, so it does not exist in a non-interactive
# batch shell until profile.d/conda.sh is sourced -- the single most common
# reason a conda env "works when I ssh in" but not under sbatch. set +u around
# it because those scripts read unset variables and would trip `set -u`.
activate_conda() {
  local env_name="$1" conda_base=""
  if [ -n "${CONDA_EXE:-}" ]; then
    conda_base="$(dirname "$(dirname "$CONDA_EXE")")"
  elif command -v conda >/dev/null 2>&1; then
    conda_base="$(conda info --base 2>/dev/null)"
  fi
  if [ -z "$conda_base" ] || [ ! -f "$conda_base/etc/profile.d/conda.sh" ]; then
    echo "ERROR: conda not found. Load it first (e.g. 'module load anaconda3')," >&2
    echo "       or pass --module with whatever your cluster calls it." >&2
    return 1
  fi
  set +u
  # shellcheck disable=SC1091
  source "$conda_base/etc/profile.d/conda.sh"
  conda activate "$env_name" || { set -u; echo "ERROR: 'conda activate $env_name' failed." >&2; return 1; }
  set -u
}

load_modules() {
  [ -z "${SATQUERY_MODULES:-}" ] && return 0
  if ! command -v module >/dev/null 2>&1; then
    echo "  NOTE: SATQUERY_MODULES set but no 'module' command here -- skipping." >&2
    return 0
  fi
  local m
  for m in $SATQUERY_MODULES; do
    echo "  [module] load $m"
    set +u
    module load "$m" || echo "  WARNING: module load $m failed" >&2
    set -u
  done
}

venv_python() { printf '%s' "$1/bin/python"; }

# Creates venv $1 if missing and syncs requirements $2 into it. Called only
# from setup (login node) -- pip needs the internet that compute nodes lack.
ensure_venv() {
  local dir="$1" reqs="$2"
  if [ ! -d "$dir" ]; then
    echo "  [setup] creating venv: $dir"
    python -m venv "$dir" || return 1
  fi
  echo "  [setup] syncing deps: ${reqs#"$REPO_ROOT"/}"
  "$(venv_python "$dir")" -m pip install --disable-pip-version-check -q -r "$reqs"
}

# True if nothing is listening on $1. Uses Python rather than lsof/ss because
# the conda env guarantees a Python, and those two tools are frequently absent
# or restricted on compute nodes.
port_free() {
  python - "$1" >/dev/null 2>&1 <<'PY'
import socket, sys
s = socket.socket()
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

# A stable, collision-resistant 4-port block per user. Deterministic on
# purpose: the tunnel command you saved last week keeps working, and the UI
# build's baked API URL stays valid from one job to the next.
#
# Range 20000-31999 is chosen to sit entirely BELOW Linux's default ephemeral
# range (net.ipv4.ip_local_port_range, usually 32768-60999). A port up there
# can be grabbed by any outbound connection on the node between our free-check
# and our bind, which would fail a service minutes into startup for no visible
# reason; down here nothing else hands ports out.
default_port_base() { echo $(( 20000 + ($(id -u) % 3000) * 4 )); }

# Polls a health URL until it answers or $3 seconds pass -- never fatal, same
# as run_pipeline.sh: a model still loading isn't an error, and the
# orchestrator tolerates a tool that isn't up yet.
wait_healthy() {
  local name="$1" url="$2" timeout="${3:-60}" waited=0
  printf "  waiting for %s" "$name"
  while ! curl -s -m 2 "$url" >/dev/null 2>&1; do
    sleep 5; waited=$((waited + 5)); printf "."
    if [ "$waited" -ge "$timeout" ]; then
      echo " still not ready after ${timeout}s -- continuing anyway (see ${LOG_DIR:-logs/hpc}/$name.log)"
      return 1
    fi
  done
  echo " ready"
}

# ===========================================================================
# SUBMIT MODE -- runs on the login node
# ===========================================================================
if [ -z "${SLURM_JOB_ID:-}" ]; then
  echo "=== SatQuery AI -- HPC submit (LLM_BACKEND=$LLM_BACKEND) ==="

  command -v sbatch >/dev/null 2>&1 || {
    echo "ERROR: sbatch not found -- are you on the cluster's login node?" >&2
    echo "       (For a laptop/workstation use scripts/run_pipeline.sh instead.)" >&2
    exit 1
  }

  load_modules
  activate_conda "$CONDA_ENV_NAME" || exit 1
  echo "  conda env: $CONDA_ENV_NAME ($(python --version 2>&1))"

  PORT_BASE="${SATQUERY_PORT_BASE:-$(default_port_base)}"

  if [ "$DO_SETUP" = true ]; then
    echo
    echo "--- Setup (login node: this is where the internet is) ---"
    mkdir -p "$ENV_ROOT"

    # EOCaptioner's deps go into the conda env, but NOT torch: the cluster's
    # torch is built against this machine's CUDA/driver stack, and pip would
    # happily replace it with a generic wheel that then can't see the H100.
    if [ "$RUN_EOCAPTIONER" = true ]; then
      echo "  [setup] EOCaptioner deps into conda env '$CONDA_ENV_NAME' (torch left alone)"
      grep -v -E '^[[:space:]]*(torch([=<>~!]|$)|#|$)' "$REPO_ROOT/server/requirements.txt" \
        > "$ENV_ROOT/eocaptioner-reqs.txt"
      python -m pip install --disable-pip-version-check -q -r "$ENV_ROOT/eocaptioner-reqs.txt" \
        || echo "  WARNING: some EOCaptioner deps failed to install -- see the output above" >&2
      python - <<'PY' || echo "  WARNING: torch is not importable in this conda env" >&2
import torch
print(f"  [setup] torch {torch.__version__} (CUDA build: {torch.version.cuda or 'cpu-only'})")
PY
    fi

    ensure_venv "$ENV_ROOT/orchestrator" "$REPO_ROOT/orchestrator/requirements.txt" \
      || { echo "ERROR: orchestrator venv setup failed" >&2; exit 1; }
    if [ "$LLM_BACKEND" = "litert" ]; then
      ensure_venv "$ENV_ROOT/litert_server" "$REPO_ROOT/orchestrator/litert_server/requirements.txt" \
        || { echo "ERROR: litert_server venv setup failed" >&2; exit 1; }
    fi

    # UI: install once, then build against the port block we're about to
    # request. Job mode re-checks the baked URL against the ports it actually
    # got and only rebuilds on a mismatch.
    if [ "$RUN_UI" = true ]; then
      if command -v npm >/dev/null 2>&1; then
        [ -d "$REPO_ROOT/ui/node_modules" ] || {
          echo "  [setup] npm install (first run only)"
          npm --prefix "$REPO_ROOT/ui" install --silent
        }
        echo "  [setup] building UI (production build -- mocks off, real orchestrator)"
        if VITE_API_BASE_URL="http://localhost:$PORT_BASE" \
             npm --prefix "$REPO_ROOT/ui" run build --silent; then
          echo "http://localhost:$PORT_BASE" > "$REPO_ROOT/ui/dist/.api-base"
        else
          echo "  WARNING: UI build failed -- the job will retry it, or pass --no-ui" >&2
        fi
      else
        echo "  WARNING: no npm on this node -- cannot build the UI." >&2
        echo "           Try '--module nodejs' (your cluster's Node module), or --no-ui." >&2
      fi
    fi
  else
    echo "  [setup] skipped (--no-setup)"
  fi

  [ "$SETUP_ONLY" = true ] && { echo; echo "Setup done (--setup-only); nothing submitted."; exit 0; }

  mkdir -p "$HPC_LOG_ROOT"

  # Everything the job needs, handed over through the environment
  # (sbatch --export=ALL) rather than argv -- so job mode reads exactly the
  # same variable names submit mode did.
  export SATQUERY_REPO_ROOT="$REPO_ROOT"
  export SATQUERY_CONDA_ENV="$CONDA_ENV_NAME"
  export SATQUERY_ENV_ROOT="$ENV_ROOT"
  export SATQUERY_DATA_ROOT="$DATA_ROOT"
  export SATQUERY_PORT_BASE="$PORT_BASE"
  export SATQUERY_LOGIN_HOST="${SATQUERY_LOGIN_HOST:-$(hostname -f 2>/dev/null || hostname)}"
  # Passed along purely so the job can quote the real walltime back at you in
  # connect.txt -- a --time flag lives in sbatch's arguments, not in any env
  # var the job could otherwise read.
  export SATQUERY_TIME="$SBATCH_TIME"
  export LLM_BACKEND
  [ -n "${SATQUERY_MODULES:-}" ] && export SATQUERY_MODULES

  SBATCH_ARGS=(
    --job-name=satquery
    --time="$SBATCH_TIME"
    --gres="$SBATCH_GRES"
    --cpus-per-task="$SBATCH_CPUS"
    --mem="$SBATCH_MEM"
    --output="$HPC_LOG_ROOT/slurm-%j.out"
    --export=ALL
  )
  [ -n "$SBATCH_PARTITION" ] && SBATCH_ARGS+=(--partition="$SBATCH_PARTITION")
  [ -n "$SBATCH_ACCOUNT" ]   && SBATCH_ARGS+=(--account="$SBATCH_ACCOUNT")
  [ -n "$SBATCH_QOS" ]       && SBATCH_ARGS+=(--qos="$SBATCH_QOS")

  JOB_ARGS=()
  [ "$RUN_UI" = false ] && JOB_ARGS+=(--no-ui)
  [ "$RUN_EOCAPTIONER" = false ] && JOB_ARGS+=(--no-eocaptioner)
  [ "$LLM_BACKEND" = "gemini" ] && JOB_ARGS+=(--gemini)

  echo
  echo "--- Submitting ---"
  echo "  resources: $SBATCH_GRES, $SBATCH_CPUS cpus, $SBATCH_MEM, walltime $SBATCH_TIME"
  JOB_ID="$(sbatch --parsable "${SBATCH_ARGS[@]}" "$REPO_ROOT/scripts/run_pipeline_hpc.sh" ${JOB_ARGS[@]+"${JOB_ARGS[@]}"})" \
    || { echo "ERROR: sbatch rejected the job (see above)." >&2; exit 1; }
  # On a federated cluster --parsable returns "jobid;clustername"; everything
  # below uses the id in paths and squeue queries, so keep only that part.
  JOB_ID="${JOB_ID%%;*}"
  echo "  job $JOB_ID submitted"
  echo "  stop it any time with:  scancel $JOB_ID"

  CONNECT_FILE="$HPC_LOG_ROOT/$JOB_ID/connect.txt"
  if [ "$WAIT_FOR_START" = false ]; then
    echo
    echo "Not waiting (--no-wait). Once it starts, connection details land in:"
    echo "  $CONNECT_FILE"
    exit 0
  fi

  echo
  printf "Waiting for the job to start (Ctrl+C is safe -- the job keeps running)"
  while true; do
    state="$(squeue -h -j "$JOB_ID" -o '%T' 2>/dev/null | tr -d ' ')"
    if [ -z "$state" ]; then
      echo
      echo "Job $JOB_ID is no longer queued -- check $HPC_LOG_ROOT/slurm-$JOB_ID.out"
      exit 1
    fi
    [ "$state" = "RUNNING" ] && break
    sleep 5; printf "."
  done
  echo " running"

  # The job writes connect.txt only once it has actually bound its ports, so
  # poll for the file rather than treating RUNNING as "serving".
  printf "Waiting for services to come up (the models take a few minutes to load)"
  waited=0
  while [ ! -f "$CONNECT_FILE" ] && [ "$waited" -lt 900 ]; do
    sleep 10; waited=$((waited + 10)); printf "."
  done
  echo
  if [ -f "$CONNECT_FILE" ]; then
    echo
    cat "$CONNECT_FILE"
  else
    echo "Services haven't reported in yet. Watch them with:"
    echo "  tail -f $HPC_LOG_ROOT/$JOB_ID/*.log"
  fi
  exit 0
fi

# ===========================================================================
# JOB MODE -- runs on the compute node, under Slurm
# ===========================================================================
LOG_DIR="$HPC_LOG_ROOT/$SLURM_JOB_ID"
mkdir -p "$LOG_DIR"
NODE_HOST="$(hostname -f 2>/dev/null || hostname)"

echo "=== SatQuery AI -- job $SLURM_JOB_ID on $NODE_HOST (LLM_BACKEND=$LLM_BACKEND) ==="
echo "  logs: $LOG_DIR"

load_modules
activate_conda "$CONDA_ENV_NAME" || exit 1

# GPU sanity check. EOCaptioner picks cuda automatically when it's visible and
# silently falls back to CPU when it isn't (server/serve.py's
# OfflineEOCaptioner.__init__), where a caption takes minutes instead of
# seconds -- so say plainly which one this job got.
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null \
    | sed 's/^/  GPU: /'
else
  echo "  WARNING: no nvidia-smi here -- EOCaptioner will fall back to CPU (very slow)." >&2
fi

# ---------------------------------------------------------------------------
# Ports. The whole block shifts together so the four services keep their fixed
# relative offsets, which is what makes the tunnel command predictable.
# ---------------------------------------------------------------------------
PORT_BASE="${SATQUERY_PORT_BASE:-$(default_port_base)}"
tries=0
while [ "$tries" -lt 64 ]; do
  if port_free "$PORT_BASE" && port_free $((PORT_BASE + 1)) \
     && port_free $((PORT_BASE + 2)) && port_free $((PORT_BASE + 3)); then
    break
  fi
  PORT_BASE=$((PORT_BASE + 4)); tries=$((tries + 1))
done
[ "$tries" -ge 64 ] && { echo "ERROR: no free 4-port block found on $NODE_HOST" >&2; exit 1; }
[ "$tries" -gt 0 ] && echo "  NOTE: preferred ports were busy; using base $PORT_BASE instead"

ORCHESTRATOR_PORT=$PORT_BASE
LITERT_SERVER_PORT=$((PORT_BASE + 1))
EOCAPTIONER_PORT=$((PORT_BASE + 2))
UI_PORT=$((PORT_BASE + 3))
echo "  ports: orchestrator=$ORCHESTRATOR_PORT litert=$LITERT_SERVER_PORT eocaptioner=$EOCAPTIONER_PORT ui=$UI_PORT"

# ---------------------------------------------------------------------------
# Environment for the services. All four are on this one node, so they reach
# each other over loopback -- only YOUR browser needs the tunnel.
# ---------------------------------------------------------------------------
export LLM_BACKEND
export LITERT_SERVER_URL="http://127.0.0.1:$LITERT_SERVER_PORT"
export EOCAPTIONER_URL="http://127.0.0.1:$EOCAPTIONER_PORT"
export ORCHESTRATOR_PORT
export BIGEARTHNET_DATA_ROOT="$DATA_ROOT"
export MODEL_DATA_ROOT="$DATA_ROOT"   # server/serve.py's own name for the same zips
export PATCH_FIXTURES_DIR="${PATCH_FIXTURES_DIR:-$REPO_ROOT/ui/src/mocks/fixtures/real-patches}"
export ORCHESTRATOR_CACHE_DIR="${ORCHESTRATOR_CACHE_DIR:-$REPO_ROOT/orchestrator/data_store/patch_cache}"
export ORCHESTRATOR_DB_PATH="${ORCHESTRATOR_DB_PATH:-$REPO_ROOT/orchestrator/data_store/orchestrator.db}"
export UPLOAD_STORE_DIR="${UPLOAD_STORE_DIR:-$REPO_ROOT/orchestrator/data_store/uploads}"
export REPORT_STORE_DIR="${REPORT_STORE_DIR:-$REPO_ROOT/orchestrator/data_store/reports}"
# The browser's origin is YOUR machine's end of the tunnel, not this node's.
export CORS_ALLOW_ORIGINS="http://localhost:$UI_PORT,http://127.0.0.1:$UI_PORT"
# The bundle is entirely local (serve.py loads it with local_files_only=True);
# saying so up front turns a compute node's dead outbound connection into a
# no-op instead of a multi-minute HuggingFace timeout at startup.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# ---------------------------------------------------------------------------
# Cleanup. Slurm sends SIGTERM at walltime and on scancel, so the trap gives
# the model servers a chance to exit properly before the job dies. Tracking
# PIDs is enough here (unlike run_pipeline.sh's port-based teardown) because
# these are direct children inside this job's own cgroup.
# ---------------------------------------------------------------------------
PIDS=()
cleanup() {
  echo
  echo "Stopping pipeline (job $SLURM_JOB_ID)..."
  local pid
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do
    kill "$pid" 2>/dev/null
  done
  sleep 3
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do
    kill -9 "$pid" 2>/dev/null
  done
  echo "Done."
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# 1. Local Gemma via litert_server
# ---------------------------------------------------------------------------
if [ "$LLM_BACKEND" = "litert" ]; then
  echo "[1/4] litert_server"
  PY_LITERT="$(venv_python "$ENV_ROOT/litert_server")"
  if [ ! -x "$PY_LITERT" ]; then
    echo "ERROR: $PY_LITERT missing -- run this script on the login node first," >&2
    echo "       which is what builds the envs (compute nodes have no internet)." >&2
    exit 1
  fi
  LITERT_SERVER_PORT="$LITERT_SERVER_PORT" \
  MODEL_PATH="$REPO_ROOT/orchestrator/gemma_models/gemma-4-E2B-it.litertlm" \
    "$PY_LITERT" "$REPO_ROOT/orchestrator/litert_server/server.py" \
    > "$LOG_DIR/litert_server.log" 2>&1 &
  PIDS+=("$!")
  echo "      started (pid $!, log: $LOG_DIR/litert_server.log)"
  # Staggered, exactly as in run_pipeline.sh: two multi-GB model loads at once
  # is the one thing reliably capable of taking a node's memory down.
  wait_healthy litert_server "http://127.0.0.1:$LITERT_SERVER_PORT/health" 300
else
  echo "[1/4] litert_server -- skipped (LLM_BACKEND=gemini)"
  echo "      NOTE: Gemini needs outbound HTTPS, which many compute nodes don't"
  echo "            have. If calls hang, use the default local-Gemma backend."
fi

# ---------------------------------------------------------------------------
# 2. EOCaptioner -- the reason this job asked for a GPU
# ---------------------------------------------------------------------------
if [ "$RUN_EOCAPTIONER" = true ]; then
  echo "[2/4] eocaptioner (server/serve.py) -- conda env '$CONDA_ENV_NAME', on the GPU"
  EOCAPTIONER_PORT="$EOCAPTIONER_PORT" \
    python "$REPO_ROOT/server/serve.py" \
      --bundle "$REPO_ROOT/server/offline_model" --host 0.0.0.0 --port "$EOCAPTIONER_PORT" \
    > "$LOG_DIR/eocaptioner.log" 2>&1 &
  PIDS+=("$!")
  echo "      started (pid $!, log: $LOG_DIR/eocaptioner.log)"
  wait_healthy eocaptioner "http://127.0.0.1:$EOCAPTIONER_PORT/health" 600
  # serve.py prints "Model loaded on cuda (torch.bfloat16)" -- worth echoing,
  # it's the definitive answer to "did it actually use the H100".
  grep -m1 "Model loaded on" "$LOG_DIR/eocaptioner.log" 2>/dev/null | sed 's/^/      /'
else
  echo "[2/4] eocaptioner -- skipped (--no-eocaptioner; EOCAPTIONER_URL must point somewhere real)"
fi

# ---------------------------------------------------------------------------
# 3. Orchestrator
# ---------------------------------------------------------------------------
echo "[3/4] orchestrator"
PY_ORCH="$(venv_python "$ENV_ROOT/orchestrator")"
if [ ! -x "$PY_ORCH" ]; then
  echo "ERROR: $PY_ORCH missing -- run this script on the login node first," >&2
  echo "       which is what builds the envs (compute nodes have no internet)." >&2
  exit 1
fi
# PYTHONPATH=orchestrator/ rather than `cd` into it, so every absolute path
# computed above stays valid regardless of the process's working directory.
PYTHONPATH="$REPO_ROOT/orchestrator" "$PY_ORCH" -m uvicorn app.main:app \
  --host 0.0.0.0 --port "$ORCHESTRATOR_PORT" > "$LOG_DIR/orchestrator.log" 2>&1 &
PIDS+=("$!")
echo "      started (pid $!, log: $LOG_DIR/orchestrator.log)"
wait_healthy orchestrator "http://127.0.0.1:$ORCHESTRATOR_PORT/health" 120

# ---------------------------------------------------------------------------
# 4. UI -- the prebuilt static bundle, served by Python's own http.server
# ---------------------------------------------------------------------------
if [ "$RUN_UI" = true ]; then
  echo "[4/4] ui (static production build)"
  WANT_API_BASE="http://localhost:$ORCHESTRATOR_PORT"
  HAVE_API_BASE="$(cat "$REPO_ROOT/ui/dist/.api-base" 2>/dev/null || echo "")"
  if [ "$HAVE_API_BASE" != "$WANT_API_BASE" ]; then
    # The port block shifted since setup baked the bundle, so the URL compiled
    # into it now points at nothing. Rebuild if we can -- serving the stale
    # bundle would look fine and then fail on every single API call.
    if command -v npm >/dev/null 2>&1 && [ -d "$REPO_ROOT/ui/node_modules" ]; then
      echo "      API base changed ('$HAVE_API_BASE' -> '$WANT_API_BASE'); rebuilding"
      if VITE_API_BASE_URL="$WANT_API_BASE" npm --prefix "$REPO_ROOT/ui" run build --silent \
           > "$LOG_DIR/ui_build.log" 2>&1; then
        echo "$WANT_API_BASE" > "$REPO_ROOT/ui/dist/.api-base"
      else
        echo "      WARNING: rebuild failed (see $LOG_DIR/ui_build.log)" >&2
      fi
    else
      echo "      WARNING: the bundle targets '$HAVE_API_BASE' but the orchestrator is" >&2
      echo "               on '$WANT_API_BASE', and npm isn't available here to rebuild." >&2
      echo "               Re-run setup on the login node with --port-base $PORT_BASE." >&2
    fi
  fi
  if [ -f "$REPO_ROOT/ui/dist/index.html" ]; then
    python -m http.server "$UI_PORT" --bind 0.0.0.0 --directory "$REPO_ROOT/ui/dist" \
      > "$LOG_DIR/ui.log" 2>&1 &
    PIDS+=("$!")
    echo "      started (pid $!, log: $LOG_DIR/ui.log)"
    wait_healthy ui "http://127.0.0.1:$UI_PORT" 30
  else
    echo "      WARNING: no ui/dist build found -- skipping the UI." >&2
    echo "               Build it on the login node: ./scripts/run_pipeline_hpc.sh --setup-only" >&2
    RUN_UI=false
  fi
else
  echo "[4/4] ui -- skipped (--no-ui)"
fi

# ---------------------------------------------------------------------------
# Connection details. Written to a file as well as printed, because by now the
# submitting shell is long gone (or was Ctrl+C'd while the job queued) and the
# batch output is somewhere you'd have to go hunting for.
# ---------------------------------------------------------------------------
LOGIN_HOST="${SATQUERY_LOGIN_HOST:-${SLURM_SUBMIT_HOST:-<login-node>}}"
TUNNEL="ssh -N -L $UI_PORT:$NODE_HOST:$UI_PORT -L $ORCHESTRATOR_PORT:$NODE_HOST:$ORCHESTRATOR_PORT $USER@$LOGIN_HOST"

{
  echo "=== SatQuery AI is up -- job $SLURM_JOB_ID on $NODE_HOST ==="
  echo
  echo "1. On YOUR machine, open a tunnel (leave it running):"
  echo
  echo "     $TUNNEL"
  echo
  echo "2. Then open:"
  [ "$RUN_UI" = true ] && echo "     UI:           http://localhost:$UI_PORT"
  echo "     Orchestrator: http://localhost:$ORCHESTRATOR_PORT/health"
  echo
  echo "   The tunnel maps identical port numbers on both ends on purpose --"
  echo "   the UI bundle has http://localhost:$ORCHESTRATOR_PORT compiled into it,"
  echo "   so changing the local port would break every API call."
  echo
  echo "Logs:  $LOG_DIR"
  echo "Stop:  scancel $SLURM_JOB_ID"
  echo "Ends automatically at the walltime limit ($SBATCH_TIME requested)."
} | tee "$LOG_DIR/connect.txt"

# Hold the allocation open. Every service is a background child; this blocks
# until they exit, the walltime runs out, or someone scancels -- and the EXIT
# trap tears things down in all three cases.
wait
