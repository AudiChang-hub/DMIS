#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=${DMIS_NEXT_PROJECT_DIR:-/home/audi/project/DMIS-next}
DEPLOY_BRANCH=${DMIS_NEXT_DEPLOY_BRANCH:-main}
PUBLIC_HEALTH_URL=${DMIS_PUBLIC_HEALTH_URL:-https://dmis.moto-core.com/health/}
LOCK_FILE=${DMIS_NEXT_DEPLOY_LOCK_FILE:-/tmp/dmis-next-deploy.lock}
DEPLOY_STATE_FILE=${DMIS_NEXT_DEPLOY_STATE_FILE:-/srv/dmis-data/dmis-next/deployed-sha}
TUNNEL_TOKEN_FILE=${DMIS_NEXT_TUNNEL_TOKEN_FILE:-$PROJECT_DIR/secrets/cloudflare-tunnel.token}

log() {
    printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

command -v git >/dev/null || fail "找不到 git"
command -v docker >/dev/null || fail "找不到 docker"
command -v curl >/dev/null || fail "找不到 curl"
command -v flock >/dev/null || fail "找不到 flock"
[[ -d "$PROJECT_DIR/.git" ]] || fail "找不到 Django 專案：$PROJECT_DIR"
[[ -f "$TUNNEL_TOKEN_FILE" && -s "$TUNNEL_TOKEN_FILE" ]] ||
    fail "找不到 Cloudflare Tunnel token 檔案：$TUNNEL_TOKEN_FILE"

exec 9>"$LOCK_FILE"
flock -n 9 || fail "已有 DMIS Next 部署程序執行中"

cd "$PROJECT_DIR"
compose=(docker compose -f docker-compose.django.yml -f docker-compose.django.prod.yml)

[[ "$(git branch --show-current)" == "$DEPLOY_BRANCH" ]] ||
    fail "目前 branch 不是 $DEPLOY_BRANCH"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] ||
    fail "工作樹有已追蹤但未提交的變更，停止部署"

log "取得 origin/$DEPLOY_BRANCH"
git fetch --quiet origin "$DEPLOY_BRANCH"
local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse "origin/$DEPLOY_BRANCH")

deployed_sha=$(cat "$DEPLOY_STATE_FILE" 2>/dev/null || true)
if [[ "$local_sha" == "$remote_sha" && "$deployed_sha" == "$remote_sha" ]]; then
    if ./scripts/verify_django_public_route.sh; then
        log "已是完整部署版本：${local_sha:0:12}"
        exit 0
    fi
    log "版本相同但正式入口驗證失敗，重新套用部署"
elif [[ "$local_sha" == "$remote_sha" ]]; then
    log "Git 已更新但缺少成功部署標記，續跑部署：${local_sha:0:12}"
else
    git merge-base --is-ancestor "$local_sha" "$remote_sha" ||
        fail "遠端更新不是 fast-forward，需人工確認"

    log "先備份 PostgreSQL 與媒體檔"
    ./scripts/backup_django_data.sh

    log "更新程式：${local_sha:0:12} -> ${remote_sha:0:12}"
    git merge --ff-only "origin/$DEPLOY_BRANCH"
fi

log "重建 Django web 與背景工作 image"
"${compose[@]}" build web ocr-worker search-worker import-worker

log "只重啟 DMIS 應用服務；資料庫與 Redis 保持運作"
"${compose[@]}" up -d --no-deps web ocr-worker search-worker import-worker

web_id=$("${compose[@]}" ps -q web)
[[ -n "$web_id" ]] || fail "找不到 web container"
for attempt in $(seq 1 36); do
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$web_id")
    [[ "$health" == "healthy" ]] && break
    sleep 5
done
[[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$web_id")" == "healthy" ]] ||
    fail "web 未在期限內恢復健康"

# nginx 會解析並記住 web container IP；web 重建後必須重新建立代理。
# 使用 up 而不是 restart，確保 network alias 等 Compose 設定異動也會生效。
log "重新建立 DMIS tunnel proxy"
"${compose[@]}" up -d --no-deps --force-recreate tunnel-proxy

log "啟動由 DMIS Next 管理的 Cloudflare Tunnel connector（HTTP/2）"
"${compose[@]}" up -d --no-deps cloudflared
cloudflared_id=$("${compose[@]}" ps -q cloudflared)
[[ -n "$cloudflared_id" ]] || fail "找不到 cloudflared container"
for attempt in $(seq 1 30); do
    if docker logs "$cloudflared_id" 2>&1 | grep -q 'protocol=http2'; then
        break
    fi
    sleep 2
done
docker logs "$cloudflared_id" 2>&1 | grep -q 'protocol=http2' ||
    fail "Cloudflare Tunnel 未以 HTTP/2 完成連線"

for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 10 "$PUBLIC_HEALTH_URL" >/dev/null; then
        log "正式網域健康檢查通過"
        ./scripts/verify_django_public_route.sh
        install -d "$(dirname "$DEPLOY_STATE_FILE")"
        state_tmp="${DEPLOY_STATE_FILE}.tmp.$$"
        printf '%s\n' "$remote_sha" >"$state_tmp"
        mv "$state_tmp" "$DEPLOY_STATE_FILE"
        "${compose[@]}" ps
        exit 0
    fi
    sleep 2
done

fail "正式網域健康檢查未通過"
