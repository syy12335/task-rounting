#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
  cat <<'USAGE'
Usage: scripts/sglang/start.sh [options] [-- sglang.launch_server args...]

Options:
  --base-url URL          OpenAI-compatible base URL, e.g. http://127.0.0.1:30000/v1
  --model NAME           Served model name
  --api-key KEY          API key passed to SGLang
  --model-path PATH      Local model directory
  --conda-env NAME       Conda environment to activate
  --conda-activate PATH  Conda activate script
  --dry-run              Print resolved config and exit without starting
  -h, --help             Show this help
USAGE
}

require_value() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    echo "$option requires a value." >&2
    exit 2
  fi
}

trim_trailing_slashes() {
  local value="$1"
  while [[ "$value" == */ ]]; do
    value="${value%/}"
  done
  echo "$value"
}

normalize_openai_base_url() {
  local value
  value="$(trim_trailing_slashes "$1")"
  if [[ "$value" != */v1 ]]; then
    value="$value/v1"
  fi
  echo "$value"
}

server_base_url() {
  local value
  value="$(normalize_openai_base_url "$1")"
  echo "${value%/v1}"
}

parse_base_url_host_port() {
  local value="$1"
  local root scheme rest authority host port tail

  root="$(server_base_url "$value")"
  scheme="${root%%://*}"
  if [[ "$scheme" == "$root" ]]; then
    scheme="http"
    rest="$root"
  else
    rest="${root#*://}"
  fi

  authority="${rest%%/*}"
  if [[ "$authority" == \[*\]* ]]; then
    host="${authority%%]*}"
    host="${host#[}"
    tail="${authority#*\]}"
    if [[ "$tail" == :* ]]; then
      port="${tail#:}"
    fi
  elif [[ "$authority" == *:* ]]; then
    host="${authority%:*}"
    port="${authority##*:}"
  else
    host="$authority"
  fi

  if [[ -z "${host:-}" ]]; then
    echo "failed to parse host from SGLANG_BASE_URL=$value" >&2
    exit 2
  fi
  if [[ -z "${port:-}" ]]; then
    if [[ "$scheme" == "https" ]]; then
      port="443"
    else
      port="80"
    fi
  fi
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    echo "failed to parse numeric port from SGLANG_BASE_URL=$value" >&2
    exit 2
  fi

  HOST="$host"
  PORT="$port"
}

detect_conda_activate() {
  local candidate
  if [[ -n "${CONDA_EXE:-}" ]]; then
    candidate="$(dirname "$CONDA_EXE")/activate"
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return
    fi
  fi
  if command -v conda >/dev/null 2>&1; then
    candidate="$(dirname "$(command -v conda)")/activate"
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return
    fi
  fi
  echo "/opt/conda/bin/activate"
}

CLI_BASE_URL=""
CLI_MODEL=""
CLI_API_KEY=""
CLI_MODEL_PATH=""
CLI_CONDA_ENV=""
CLI_CONDA_ACTIVATE=""
DRY_RUN=0
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      require_value "$1" "${2:-}"
      CLI_BASE_URL="$2"
      shift 2
      ;;
    --base-url=*)
      CLI_BASE_URL="${1#*=}"
      shift
      ;;
    --model)
      require_value "$1" "${2:-}"
      CLI_MODEL="$2"
      shift 2
      ;;
    --model=*)
      CLI_MODEL="${1#*=}"
      shift
      ;;
    --api-key)
      require_value "$1" "${2:-}"
      CLI_API_KEY="$2"
      shift 2
      ;;
    --api-key=*)
      CLI_API_KEY="${1#*=}"
      shift
      ;;
    --model-path)
      require_value "$1" "${2:-}"
      CLI_MODEL_PATH="$2"
      shift 2
      ;;
    --model-path=*)
      CLI_MODEL_PATH="${1#*=}"
      shift
      ;;
    --conda-env)
      require_value "$1" "${2:-}"
      CLI_CONDA_ENV="$2"
      shift 2
      ;;
    --conda-env=*)
      CLI_CONDA_ENV="${1#*=}"
      shift
      ;;
    --conda-activate)
      require_value "$1" "${2:-}"
      CLI_CONDA_ACTIVATE="$2"
      shift 2
      ;;
    --conda-activate=*)
      CLI_CONDA_ACTIVATE="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      PASSTHROUGH_ARGS+=("$@")
      break
      ;;
    *)
      PASSTHROUGH_ARGS+=("$1")
      shift
      ;;
  esac
done

LOG_DIR="${SGLANG_LOG_DIR:-$ROOT_DIR/var/logs}"
LOG_FILE="${SGLANG_LOG_FILE:-$LOG_DIR/sglang.log}"
PID_FILE="${SGLANG_PID_FILE:-$ROOT_DIR/var/sglang.pid}"

MODEL_PATH="${CLI_MODEL_PATH:-${SGLANG_MODEL_PATH:-}}"
SERVED_MODEL_NAME="${CLI_MODEL:-${SGLANG_MODEL:-${SGLANG_SERVED_MODEL_NAME:-qwen3-4b}}}"
API_KEY="${CLI_API_KEY:-${SGLANG_API_KEY:-EMPTY}}"

BASE_URL="${CLI_BASE_URL:-${SGLANG_BASE_URL:-}}"
if [[ -n "$BASE_URL" ]]; then
  BASE_URL="$(normalize_openai_base_url "$BASE_URL")"
  parse_base_url_host_port "$BASE_URL"
else
  HOST="${SGLANG_HOST:-127.0.0.1}"
  PORT="${SGLANG_PORT:-30000}"
  BASE_URL="http://$HOST:$PORT/v1"
fi

CONDA_ACTIVATE="${CLI_CONDA_ACTIVATE:-${SGLANG_CONDA_ACTIVATE:-}}"
if [[ -z "$CONDA_ACTIVATE" ]]; then
  CONDA_ACTIVATE="$(detect_conda_activate)"
fi
CONDA_ENV="${CLI_CONDA_ENV:-${SGLANG_CONDA_ENV:-${CONDA_DEFAULT_ENV:-task-routing-online}}}"
CPU_CORES="${SGLANG_CPU_CORES:-}"
NICE_LEVEL="${SGLANG_NICE_LEVEL:-10}"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "model_path=$MODEL_PATH"
  echo "model=$SERVED_MODEL_NAME"
  echo "base_url=$BASE_URL"
  echo "host=$HOST"
  echo "port=$PORT"
  echo "api_key=$([[ -n "$API_KEY" && "$API_KEY" != "EMPTY" ]] && echo "<set>" || echo "$API_KEY")"
  echo "conda_activate=$CONDA_ACTIVATE"
  echo "conda_env=$CONDA_ENV"
  echo "log_file=$LOG_FILE"
  echo "pid_file=$PID_FILE"
  printf "passthrough_args="
  if [[ "${#PASSTHROUGH_ARGS[@]}" -gt 0 ]]; then
    printf "%q " "${PASSTHROUGH_ARGS[@]}"
  fi
  echo
  exit 0
fi

mkdir -p "$LOG_DIR" "$(dirname "$PID_FILE")"

if [[ -z "$MODEL_PATH" ]]; then
  echo "SGLANG_MODEL_PATH is required; set it to a local model directory." >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "sglang already running: pid=$OLD_PID"
    echo "log: $LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if ! command -v nice >/dev/null 2>&1; then
  echo "nice not found; cannot lower process priority." >&2
  exit 1
fi

if [[ ! -f "$CONDA_ACTIVATE" ]]; then
  echo "conda activate script not found: $CONDA_ACTIVATE" >&2
  exit 1
fi

if [[ -n "$CPU_CORES" ]]; then
  if ! command -v taskset >/dev/null 2>&1; then
    echo "taskset not found; cannot pin CPU cores." >&2
    exit 1
  fi
  if ! taskset -c "$CPU_CORES" true >/dev/null 2>&1; then
    echo "invalid SGLANG_CPU_CORES=$CPU_CORES for current cpuset; run \`taskset -pc \$\$\` to inspect allowed CPUs" >&2
    exit 1
  fi
fi

(
  source "$CONDA_ACTIVATE" "$CONDA_ENV"
  export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
  export TASK_ROUTER_SGLANG_CHAT_TEMPLATE_FIX="${TASK_ROUTER_SGLANG_CHAT_TEMPLATE_FIX:-1}"

  if [[ -n "$CPU_CORES" ]]; then
    exec nice -n "$NICE_LEVEL" taskset -c "$CPU_CORES" \
      python -m sglang.launch_server \
        --model-path "$MODEL_PATH" \
        --served-model-name "$SERVED_MODEL_NAME" \
        --host "$HOST" \
        --port "$PORT" \
        --api-key "$API_KEY" \
        "${PASSTHROUGH_ARGS[@]}"
  else
    exec nice -n "$NICE_LEVEL" \
      python -m sglang.launch_server \
        --model-path "$MODEL_PATH" \
        --served-model-name "$SERVED_MODEL_NAME" \
        --host "$HOST" \
        --port "$PORT" \
        --api-key "$API_KEY" \
        "${PASSTHROUGH_ARGS[@]}"
  fi
) >>"$LOG_FILE" 2>&1 &

PID=$!
echo "$PID" > "$PID_FILE"

sleep 1
if kill -0 "$PID" 2>/dev/null; then
  echo "sglang started: pid=$PID"
  echo "base_url: $BASE_URL"
  echo "model: $SERVED_MODEL_NAME"
  echo "log: $LOG_FILE"
  echo "pid file: $PID_FILE"
  exit 0
fi

rm -f "$PID_FILE"
echo "sglang failed to start; check log: $LOG_FILE" >&2
exit 1
