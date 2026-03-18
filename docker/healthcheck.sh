#!/bin/sh
set -eu

QUIET=0
if [ "${1:-}" = "--quiet" ]; then
  QUIET=1
fi

PORT="${PORT:-7860}"
SERVER_PORT="${SERVER_PORT:-8000}"
CURL_TIMEOUT="${HEALTHCHECK_CURL_TIMEOUT_SECONDS:-5}"

log() {
  if [ "$QUIET" -eq 0 ]; then
    printf '%s\n' "$1"
  fi
}

probe() {
  curl --silent --show-error --fail --max-time "$CURL_TIMEOUT" "$1" >/dev/null
}

frontend_url="http://127.0.0.1:${PORT}/api/health"
backend_url="http://127.0.0.1:${SERVER_PORT}/api/health"

if probe "$frontend_url"; then
  exit 0
fi

if probe "$backend_url"; then
  log "[healthcheck] frontend probe failed: ${frontend_url}"
  log "[healthcheck] backend probe passed: ${backend_url}"
  log "[healthcheck] check nginx listen port or proxy configuration"
  exit 1
fi

log "[healthcheck] frontend probe failed: ${frontend_url}"
log "[healthcheck] backend probe failed: ${backend_url}"
log "[healthcheck] backend is not ready or crashed before nginx could proxy traffic"
exit 1
