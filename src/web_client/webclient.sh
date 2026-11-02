#!/usr/bin/env bash
# ==============================================================================
# Start / Stop / Status / Restart script for the Transaction Fraud Scorer WebUI
# Usage:
#   ./src/web_client/webclient.sh start [--host 127.0.0.1] [--port 3000]
#   ./src/web_client/webclient.sh stop
#   ./src/web_client/webclient.sh restart
#   ./src/web_client/webclient.sh status
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PID_FILE="${PROJECT_ROOT}/.webclient.pid"
LOG_FILE="${PROJECT_ROOT}/.webclient.log"

HOST="${WEBCLIENT_HOST:-127.0.0.1}"
PORT="${WEBCLIENT_PORT:-3000}"

ACTION="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

is_running() {
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(cat "${PID_FILE}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

start_server() {
  if is_running; then
    local pid
    pid="$(cat "${PID_FILE}")"
    echo "✅ Web Client is already running (PID: ${pid}) at http://${HOST}:${PORT}"
    return 0
  fi

  cd "${PROJECT_ROOT}"
  echo "🚀 Starting Transaction Fraud Scorer Web Client on http://${HOST}:${PORT} ..."

  if command -v uv >/dev/null 2>&1; then
    nohup uv run fraud-web-client --host "${HOST}" --port "${PORT}" >"${LOG_FILE}" 2>&1 &
  elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHONPATH="${PROJECT_ROOT}/src" nohup "${PROJECT_ROOT}/.venv/bin/python" -m web_client.server --host "${HOST}" --port "${PORT}" >"${LOG_FILE}" 2>&1 &
  else
    PYTHONPATH="${PROJECT_ROOT}/src" nohup python3 -m web_client.server --host "${HOST}" --port "${PORT}" >"${LOG_FILE}" 2>&1 &
  fi

  local pid=$!
  echo "${pid}" > "${PID_FILE}"
  sleep 1

  if is_running; then
    echo "✅ Web Client started (PID: ${pid})"
    echo "   • Submit Page : http://${HOST}:${PORT}/index.html"
    echo "   • Queue Page  : http://${HOST}:${PORT}/queue.html"
    echo "   • Log File    : ${LOG_FILE}"
  else
    echo "❌ Failed to start Web Client. Check logs at ${LOG_FILE}:"
    cat "${LOG_FILE}" || true
    rm -f "${PID_FILE}"
    exit 1
  fi
}

stop_server() {
  if ! is_running; then
    echo "ℹ️  Web Client is not running."
    rm -f "${PID_FILE}"
    return 0
  fi

  local pid
  pid="$(cat "${PID_FILE}")"
  echo "🛑 Stopping Web Client (PID: ${pid})..."
  kill "${pid}" 2>/dev/null || true

  for _ in {1..10}; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done

  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 "${pid}" 2>/dev/null || true
  fi

  rm -f "${PID_FILE}"
  echo "✅ Web Client stopped."
}

status_server() {
  if is_running; then
    local pid
    pid="$(cat "${PID_FILE}")"
    echo "✅ Web Client is RUNNING (PID: ${pid})"
    echo "   • Submit Page : http://${HOST}:${PORT}/index.html"
    echo "   • Queue Page  : http://${HOST}:${PORT}/queue.html"
    echo "   • Log File    : ${LOG_FILE}"
  else
    echo "⚪ Web Client is STOPPED."
  fi
}

case "${ACTION}" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    status_server
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status} [--host 127.0.0.1] [--port 3000]"
    exit 1
    ;;
esac
