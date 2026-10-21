#!/usr/bin/env bash
# DMIS 藍綠部署：web-blue／web-green 輪流接流量，切換時使用者不會碰到中斷。
#
#   deploy    建置新版 → 檢查 migration 相容 → 先套用 migration（舊版照常服務）
#             → 閒置的那色啟動新版並等就緒 → nginx 平順切換 → 舊的那色排空後停止（保留供秒退）
#   rollback  把上一色（已停止、仍是舊版 image）重新啟動並切回去，同樣不中斷
#
# 由 deploy_django.sh 在核對 Git、備份與發布標籤之後呼叫；本腳本只動 Docker，不碰 Git、
# 不重啟 PostgreSQL／Redis，也不會 compose down。可用環境變數指定其他 compose 專案做演練。
set -Eeuo pipefail

PROJECT_DIR=${DMIS_NEXT_PROJECT_DIR:-/home/audi/project/DMIS-next}
STATE_DIR=${DMIS_PROXY_STATE_DIR:-/srv/dmis-data/dmis-next/proxy}
DRAIN_SECONDS=${DMIS_DEPLOY_DRAIN_SECONDS:-15}
MIGRATE_LOCK_TIMEOUT=${DMIS_MIGRATE_LOCK_TIMEOUT:-10s}
read -r -a COMPOSE_FILES <<<"${DMIS_COMPOSE_FILES:-docker-compose.django.yml docker-compose.django.prod.yml}"
ACTIVE_FILE="$STATE_DIR/active.conf"
read -r -a WORKERS <<<"${DMIS_DEPLOY_WORKERS:-ocr-worker search-worker import-worker}"

log() {
    printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

cd "$PROJECT_DIR"
compose=(docker compose)
for file in "${COMPOSE_FILES[@]}"; do
    compose+=(-f "$file")
done
project=$("${compose[@]}" config 2>/dev/null | sed -n 's/^name: //p' | head -1)
[[ -n "$project" ]] || fail "讀不到 compose 專案名稱"
NETWORK="${project}_default"
BRIDGE="${project}-proxy-bridge"

other_color() {
    [[ "$1" == "web-blue" ]] && echo web-green || echo web-blue
}

# 目前接流量的顏色；空字串代表還是改版前的單一 web。
active_color() {
    # 沒有狀態檔時不能讓 sed 失敗：在 pipefail＋errexit 下整支腳本會無訊息結束。
    [[ -f "$ACTIVE_FILE" ]] || return 0
    sed -n 's/^set \$dmis_backend \(web-blue\|web-green\):8000;$/\1/p' "$ACTIVE_FILE" | head -1
}

write_active() {
    local tmp="$ACTIVE_FILE.tmp.$$"
    printf 'set $dmis_backend %s:8000;\n' "$1" >"$tmp"
    mv "$tmp" "$ACTIVE_FILE"
}

container_of() {
    "${compose[@]}" ps -a -q "$1" 2>/dev/null | head -1
}

# 等容器 healthcheck 變成 healthy；中途退出、重啟或 unhealthy 立即回報失敗，不浪費時間。
wait_healthy() {
    local id=$1 label=$2 limit=${3:-120} status state
    for _ in $(seq 1 "$limit"); do
        state=$(docker inspect --format '{{.State.Status}}' "$id")
        status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")
        [[ "$status" == "healthy" ]] && return 0
        if [[ "$state" =~ ^(exited|dead|restarting)$ || "$status" == "unhealthy" ]]; then
            log "$label 啟動失敗（$state／$status）"
            docker logs --tail 20 "$id" 2>&1 || true
            return 1
        fi
        sleep 1
    done
    log "$label 未在 ${limit} 秒內就緒"
    return 1
}

# 新版起不來：停掉它（避免 restart 迴圈），流量本來就還在原本那一色。
# $2：降級部署時已先停掉的舊版 container，重新啟動它讓服務恢復。
start_failed() {
    "${compose[@]}" stop "$1" >/dev/null 2>&1 || true
    if [[ -n "${2:-}" ]]; then
        docker start "$2" >/dev/null || true
        fail "$1 沒有就緒，已停止並重新啟動舊版；migration 已套用，請確認舊版是否正常"
    fi
    fail "$1 沒有就緒，已停止；流量維持在原本的版本"
}

proxy_reload() {
    "${compose[@]}" exec -T tunnel-proxy nginx -t -q &&
        "${compose[@]}" exec -T tunnel-proxy nginx -s reload
}

proxy_needs_recreate() {
    local id want have
    id=$("${compose[@]}" ps -q tunnel-proxy)
    [[ -n "$id" ]] || return 0
    want=$("${compose[@]}" config --hash tunnel-proxy | awk '{print $2}')
    have=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$id")
    [[ "$want" != "$have" ]]
}

local_health() {
    local address
    address=$("${compose[@]}" port tunnel-proxy 8069 2>/dev/null | tail -1)
    [[ -n "$address" ]] || return 1
    curl --fail --silent --max-time 5 "http://$address/health/" >/dev/null
}

# tunnel-proxy 設定（compose 層）有變時才重建。重建期間先起一個同設定、同 network alias（odoo）
# 的暫代 nginx，cloudflared 連不到正在停止的那台時會改連暫代的，使用者不會看到 502。
# $1：舊代理停下後、新代理啟動前要做的事（改版過渡時用來把 19999 從舊 web 讓出來）。
recreate_proxy_bridged() {
    local before_start=${1:-} image old
    image=$("${compose[@]}" config --images tunnel-proxy | head -1)
    docker rm -f "$BRIDGE" >/dev/null 2>&1 || true
    log "啟動暫代代理 $BRIDGE，接手重建 tunnel-proxy 的空檔"
    docker run -d --name "$BRIDGE" --network "$NETWORK" --network-alias odoo \
        --memory 96m --restart no \
        -v "$PROJECT_DIR/deployment/nginx:/etc/nginx/conf.d:ro" \
        -v "$STATE_DIR:/etc/nginx/dmis-upstream:ro" \
        "$image" >/dev/null
    for _ in $(seq 1 30); do
        docker exec "$BRIDGE" wget -qO- http://127.0.0.1:8069/health/ >/dev/null 2>&1 && break
        sleep 1
    done
    docker exec "$BRIDGE" wget -qO- http://127.0.0.1:8069/health/ >/dev/null 2>&1 || {
        docker rm -f "$BRIDGE" >/dev/null 2>&1 || true
        fail "暫代代理無法連到新版；tunnel-proxy 未變動"
    }
    old=$("${compose[@]}" ps -q tunnel-proxy)
    if [[ -n "$old" ]]; then
        # nginx image 的停止訊號是 SIGQUIT：處理完手上的請求才結束。
        docker stop --time 20 "$old" >/dev/null
    fi
    [[ -n "$before_start" ]] && "$before_start"
    "${compose[@]}" up -d --no-deps tunnel-proxy
    # 失敗時暫代代理繼續服務，不移除，留待人工處理。
    wait_healthy "$("${compose[@]}" ps -q tunnel-proxy)" "tunnel-proxy" 60 ||
        fail "tunnel-proxy 重建後未就緒；暫代代理 $BRIDGE 繼續服務，請依 log 修正後再部署"
    docker stop --time 20 "$BRIDGE" >/dev/null
    docker rm "$BRIDGE" >/dev/null
    log "tunnel-proxy 已重建，暫代代理已移除"
}

# 改版前的單一 web 佔著 127.0.0.1:19999；換成管理指令容器後新代理才綁得到。
replace_legacy_web() {
    log "舊的單一 web 改為管理指令容器（不接流量）"
    "${compose[@]}" up -d --no-deps --force-recreate web
}

# 把流量切到 $1。一般情況只改 active.conf 並 reload：既有連線由舊 worker 處理完，新請求進新版。
switch_to() {
    local target=$1 legacy=${2:-0} previous=""
    [[ -f "$ACTIVE_FILE" ]] && previous=$(cat "$ACTIVE_FILE")
    write_active "$target"
    if [[ "$legacy" == "1" ]]; then
        recreate_proxy_bridged replace_legacy_web
    elif proxy_needs_recreate; then
        recreate_proxy_bridged
    elif ! proxy_reload; then
        if [[ -n "$previous" ]]; then
            printf '%s\n' "$previous" >"$ACTIVE_FILE"
        else
            rm -f "$ACTIVE_FILE"
        fi
        fail "nginx 設定檢查失敗，已還原 active.conf；流量維持在原本的版本"
    fi
    for _ in $(seq 1 10); do
        local_health && break
        sleep 1
    done
    local_health || fail "切換到 $target 後本機健康檢查失敗"
    log "流量已切到 $target"
}

start_color() {
    local target=$1 fallback=${2:-} id
    log "在 $target 啟動新版（舊版持續服務）"
    "${compose[@]}" up -d --no-deps --force-recreate "$target"
    id=$(container_of "$target")
    [[ -n "$id" ]] || fail "找不到 $target container"
    wait_healthy "$id" "$target" || start_failed "$target" "$fallback"
}

migrate_with() {
    log "套用 migration（lock_timeout=$MIGRATE_LOCK_TIMEOUT）"
    "${compose[@]}" run --rm --no-deps -e "PGOPTIONS=-c lock_timeout=$MIGRATE_LOCK_TIMEOUT" \
        "$1" python manage.py migrate --noinput
}

finish_support_services() {
    log "更新管理指令容器與背景工作"
    "${compose[@]}" up -d --no-deps web "${WORKERS[@]}"
}

deploy() {
    local current target legacy=0 compat=0 sha=${DMIS_DEPLOY_SHA:-}
    install -d "$STATE_DIR"
    current=$(active_color)
    if [[ -z "$current" ]]; then
        legacy=1
        target=web-blue
        log "目前由改版前的單一 web 服務；這次改為藍綠部署，新版放在 $target"
    else
        target=$(other_color "$current")
        log "目前接流量：$current；新版放在 $target"
    fi

    log "建置新版 image（舊版持續服務）"
    "${compose[@]}" build "$target" web "${WORKERS[@]}"

    log "檢查待套用 migration 是否與線上舊版相容"
    "${compose[@]}" run --rm --no-deps "$target" python manage.py check_migration_compat || compat=$?
    case "$compat" in
        0)
            migrate_with "$target"
            start_color "$target"
            ;;
        3)
            # 刪除／改名欄位等會讓舊版出錯的 migration：先停舊版再遷移，畫面顯示「系統更新中」數秒。
            log "WARNING: 有與舊版不相容的 migration，這次改用短暫停機部署"
            local serving
            serving=$(container_of "${current:-web}")
            docker stop "$serving" >/dev/null
            migrate_with "$target" || { docker start "$serving" >/dev/null; fail "migration 失敗，已重新啟動舊版"; }
            start_color "$target" "$serving"
            ;;
        *)
            fail "migration 相容檢查無法執行（代碼 $compat）；流量維持在原本的版本"
            ;;
    esac

    switch_to "$target" "$legacy"
    [[ -n "$sha" ]] && printf '%s\n' "$sha" >"$STATE_DIR/$target.sha"

    if [[ "$legacy" == "0" && "$compat" == "0" ]]; then
        log "等候 ${DRAIN_SECONDS} 秒讓 $current 處理完手上的請求"
        sleep "$DRAIN_SECONDS"
        # 只停止不刪除：容器保留舊版 image，rollback 時直接啟動。
        "${compose[@]}" stop "$current"
        log "$current 已停止並保留，可用 deploy_django.sh --rollback 秒退"
    fi
    finish_support_services
    [[ "$compat" == "3" ]] && log "WARNING: 本次為短暫停機部署（不相容 migration）"
    return 0
}

rollback() {
    local current previous id
    current=$(active_color)
    [[ -n "$current" ]] || fail "尚未使用藍綠部署，沒有可切回的上一版"
    previous=$(other_color "$current")
    id=$(container_of "$previous")
    [[ -n "$id" ]] || fail "找不到上一版 $previous container"
    log "啟動上一版 $previous（$(cat "$STATE_DIR/$previous.sha" 2>/dev/null || echo '版本未記錄')）"
    # 用 docker start 而不是 compose up：compose 會以最新 image 重建，就不是上一版了。
    docker start "$id" >/dev/null
    wait_healthy "$id" "$previous" || start_failed "$previous"
    switch_to "$previous"
    log "等候 ${DRAIN_SECONDS} 秒讓 $current 處理完手上的請求"
    sleep "$DRAIN_SECONDS"
    "${compose[@]}" stop "$current"
    log "已切回 $previous；$current 停止並保留。管理指令容器與背景工作仍是新版，請盡快發修正版"
}

case "${1:-}" in
    deploy) deploy ;;
    rollback) rollback ;;
    active) active_color ;;
    *) fail "用法：$0 deploy|rollback|active" ;;
esac
