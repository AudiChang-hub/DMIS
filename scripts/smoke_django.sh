#!/usr/bin/env sh
set -eu

BASE_URL="${1:-${DMIS_DJANGO_URL:-http://127.0.0.1:19999}}"
TIMEOUT_SECONDS="${DMIS_DJANGO_SMOKE_TIMEOUT:-90}"
started="$(date +%s)"

while :; do
  if curl --fail --silent --show-error --max-time 5 "${BASE_URL}/health/" \
    | grep -q '"ok": true'; then
    echo "Django smoke OK: ${BASE_URL}/health/"
    exit 0
  fi
  now="$(date +%s)"
  if [ $((now - started)) -ge "$TIMEOUT_SECONDS" ]; then
    echo "ERROR: Django 未在 ${TIMEOUT_SECONDS} 秒內通過健康檢查" >&2
    exit 1
  fi
  sleep 3
done
