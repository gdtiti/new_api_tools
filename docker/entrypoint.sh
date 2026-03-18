#!/bin/sh
set -eu

PORT="${PORT:-7860}"
SERVER_PORT="${SERVER_PORT:-8000}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT_SECONDS:-60}"

render_nginx_config() {
  sed \
    -e "s/__NGINX_PORT__/${PORT}/g" \
    -e "s/__BACKEND_PORT__/${SERVER_PORT}/g" \
    /etc/nginx/http.d/default.conf > /tmp/default.conf
  mv /tmp/default.conf /etc/nginx/http.d/default.conf
}

stop_supervisor() {
  if [ -n "${SUPERVISOR_PID:-}" ] && kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
    kill -TERM "$SUPERVISOR_PID" 2>/dev/null || true
    wait "$SUPERVISOR_PID" || true
  fi
}

on_term() {
  printf '%s\n' "[startup] received termination signal, forwarding to supervisord"
  stop_supervisor
  exit 143
}

trap on_term INT TERM

printf '%s\n' "[startup] HF app port: ${PORT}"
printf '%s\n' "[startup] backend port: ${SERVER_PORT}"

render_nginx_config
nginx -t

/usr/bin/supervisord -c /etc/supervisord.conf &
SUPERVISOR_PID=$!

elapsed=0
until /app/docker/healthcheck.sh --quiet; do
  if [ "$elapsed" -ge "$STARTUP_TIMEOUT" ]; then
    printf '%s\n' "[startup] readiness check failed after ${STARTUP_TIMEOUT}s"
    /app/docker/healthcheck.sh || true
    printf '%s\n' "[startup] rendered nginx configuration:"
    cat /etc/nginx/http.d/default.conf || true
    stop_supervisor
    exit 1
  fi

  elapsed=$((elapsed + 1))
  sleep 1
done

printf '%s\n' "[startup] readiness check passed: http://127.0.0.1:${PORT}/api/health"

wait "$SUPERVISOR_PID"
