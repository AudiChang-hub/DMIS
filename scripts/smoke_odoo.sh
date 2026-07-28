#!/usr/bin/env bash
set -euo pipefail

ODOO_PORT=${ODOO_PORT:-8069}
TIMEOUT=${TIMEOUT:-180}

END=$((SECONDS+TIMEOUT))
URL="http://localhost:${ODOO_PORT}/web/login"

while [ ${SECONDS} -lt ${END} ]; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$URL" || echo 000)
  if [ "$STATUS" = "200" ] || [ "$STATUS" = "302" ] || [ "$STATUS" = "303" ]; then
    echo "OK: received $STATUS from $URL"
    exit 0
  fi
  sleep 2
done

echo "ERROR: Odoo did not become ready within ${TIMEOUT}s"
exit 1
