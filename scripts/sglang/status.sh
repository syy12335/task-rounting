#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_FILE="${SGLANG_PID_FILE:-$ROOT_DIR/var/sglang.pid}"
API_KEY="${SGLANG_API_KEY:-EMPTY}"

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

API_BASE_URL="${SGLANG_BASE_URL:-}"
if [[ -n "$API_BASE_URL" ]]; then
  API_BASE_URL="$(normalize_openai_base_url "$API_BASE_URL")"
else
  HOST="${SGLANG_HOST:-127.0.0.1}"
  PORT="${SGLANG_PORT:-30000}"
  API_BASE_URL="http://$HOST:$PORT/v1"
fi
SERVER_BASE_URL="${API_BASE_URL%/v1}"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    echo "status: RUNNING (pid=$PID)"
  else
    echo "status: NOT_RUNNING (stale pid file)"
  fi
else
  echo "status: NOT_RUNNING"
fi

echo "base_url: $API_BASE_URL"

echo "processes:"
pgrep -af "sglang.launch_server|sglang::scheduler|sglang::detokenizer" || true

echo
printf "/model_info status: "
STATUS_INFO="$(curl -s -o /tmp/sglang_model_info.out -w "%{http_code}" "$SERVER_BASE_URL/model_info" -H "Authorization: Bearer $API_KEY" || true)"
echo "$STATUS_INFO"
cat /tmp/sglang_model_info.out 2>/dev/null || true

echo
printf "/v1/models status: "
STATUS_MODELS="$(curl -s -o /tmp/sglang_models.out -w "%{http_code}" "$API_BASE_URL/models" -H "Authorization: Bearer $API_KEY" || true)"
echo "$STATUS_MODELS"
cat /tmp/sglang_models.out 2>/dev/null || true

rm -f /tmp/sglang_model_info.out /tmp/sglang_models.out
