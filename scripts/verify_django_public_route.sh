#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL=${DMIS_PUBLIC_BASE_URL:-https://dmis.moto-core.com}
ATTEMPTS=${DMIS_ROUTE_VERIFY_ATTEMPTS:-12}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

command -v curl >/dev/null || fail "找不到 curl"

headers=""
body=""
cleanup() {
    rm -f "${headers:-}" "${body:-}"
}
trap cleanup EXIT

health_status=$(curl --silent --show-error --output /dev/null \
    --max-time 10 --write-out '%{http_code}' "$BASE_URL/health/")
[[ "$health_status" == "200" ]] || fail "健康檢查回傳 $health_status"

for attempt in $(seq 1 "$ATTEMPTS"); do
    headers=$(mktemp)
    body=$(mktemp)

    status=$(curl --silent --show-error --dump-header "$headers" --output "$body" \
        --max-time 10 --write-out '%{http_code}' \
        "$BASE_URL/?route_probe=$attempt")
    location=$(awk 'tolower($1)=="location:" {sub(/\r$/, "", $2); print $2; exit}' "$headers")

    [[ "$status" == "200" || "$status" == "302" ]] ||
        fail "第 $attempt 次首頁檢查回傳 $status"
    [[ "$location" != *"/web"* ]] ||
        fail "第 $attempt 次首頁仍被導向舊 Odoo：$location"
    ! grep -Eqi 'Odoo|Your logo|錯誤 404' "$body" ||
        fail "第 $attempt 次首頁仍出現舊 Odoo 內容"

    rm -f "$headers" "$body"
    headers=""
    body=""
done

headers=$(mktemp)
body=$(mktemp)
legacy_status=$(curl --silent --show-error --dump-header "$headers" --output "$body" \
    --max-time 10 --write-out '%{http_code}' "$BASE_URL/web")
legacy_location=$(awk 'tolower($1)=="location:" {sub(/\r$/, "", $2); print $2; exit}' "$headers")
[[ "$legacy_status" == "302" ]] ||
    fail "舊 /web 網址回傳 $legacy_status，預期導回新系統"
[[ "$legacy_location" != *"/web"* ]] ||
    fail "舊 /web 網址沒有導回新系統：$legacy_location"
! grep -Eqi 'Odoo|Your logo|錯誤 404' "$body" ||
    fail "舊 /web 網址仍出現 Odoo 內容"

printf 'OK: 正式網域連續 %s 次均由 Django 回應\n' "$ATTEMPTS"
