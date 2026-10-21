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

# 秒退：把流量切回上一色（已停止、仍是上一版 image），不動 Git、不重新部署。
if [[ "${1:-}" == "--rollback" ]]; then
    ./scripts/deploy_web_bluegreen.sh rollback
    ./scripts/verify_django_public_route.sh
    rolled_back_sha=$(cat "${DMIS_PROXY_STATE_DIR:-/srv/dmis-data/dmis-next/proxy}/$(./scripts/deploy_web_bluegreen.sh active).sha" 2>/dev/null || true)
    # 部署標記改成上一版，下次執行部署會重新套用 main 最新版（應為修正版）。
    if [[ -n "$rolled_back_sha" ]]; then
        printf '%s\n' "$rolled_back_sha" >"$DEPLOY_STATE_FILE"
    else
        rm -f "$DEPLOY_STATE_FILE"
    fi
    exit 0
fi
script_before=$(sha256sum scripts/deploy_django.sh)

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

    log "先備份 PostgreSQL 與媒體檔（不清理過期備份）"
    DMIS_BACKUP_SKIP_PRUNE=1 ./scripts/backup_django_data.sh

    log "更新程式：${local_sha:0:12} -> ${remote_sha:0:12}"
    git merge --ff-only "origin/$DEPLOY_BRANCH"
    # 部署腳本本身有更新時改用新版接著跑（已備份、已合併，會走「續跑部署」）。
    if [[ "$(sha256sum scripts/deploy_django.sh)" != "$script_before" ]]; then
        log "部署腳本已更新，改用新版繼續"
        exec ./scripts/deploy_django.sh "$@"
    fi
fi

log "核對正式版號與已發布標籤；未標記版本不得部署"
release_version=$(python3 -c 'from config.release_notes import CURRENT_VERSION; print(CURRENT_VERSION)')
git fetch --quiet origin "refs/tags/v${release_version}:refs/tags/v${release_version}" ||
    fail "找不到正式發布標籤 v${release_version}"
python3 scripts/check_release.py --tag "v${release_version}" ||
    fail "正式版號或標籤提交核對失敗；不重啟應用服務"

# 藍綠部署：新版在閒置的那色就緒後才切換，舊版排空後停止並保留供秒退。
# 資料庫與 Redis 不會因應用更新而重啟。
DMIS_DEPLOY_SHA="$remote_sha" DMIS_NEXT_PROJECT_DIR="$PROJECT_DIR" \
    ./scripts/deploy_web_bluegreen.sh deploy

log "啟動由 DMIS Next 管理的 Cloudflare Tunnel connector（HTTP/2）"
"${compose[@]}" up -d --no-deps cloudflared
cloudflared_id=$("${compose[@]}" ps -q cloudflared)
[[ -n "$cloudflared_id" ]] || fail "找不到 cloudflared container"
for attempt in $(seq 1 30); do
    # 在 pipefail 下不可用 grep -q 提早關閉管線，否則 docker logs 可能因
    # SIGPIPE 回傳非零，造成已連線的 tunnel 被誤判為失敗。
    if docker logs "$cloudflared_id" 2>&1 | grep 'protocol=http2' >/dev/null; then
        break
    fi
    sleep 2
done
docker logs "$cloudflared_id" 2>&1 | grep 'protocol=http2' >/dev/null ||
    fail "Cloudflare Tunnel 未以 HTTP/2 完成連線"

for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 10 "$PUBLIC_HEALTH_URL" >/dev/null; then
        log "正式網域健康檢查通過"
        ./scripts/verify_django_public_route.sh
        "${compose[@]}" exec -T web python manage.py record_release
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
