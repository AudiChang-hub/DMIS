#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=${DMIS_PROJECT_DIR:-/home/audi/project/DMIS}
DEPLOY_BRANCH=${DMIS_DEPLOY_BRANCH:-feat/015-dms-product-rebuild}
ODOO_DB=${DMIS_ODOO_DB:-dmis_dev}
BACKUP_DIR=${DMIS_BACKUP_DIR:-${PROJECT_DIR}/backups/auto-deploy}
BACKUP_RETENTION_DAYS=${DMIS_BACKUP_RETENTION_DAYS:-14}
LOCK_FILE=${DMIS_DEPLOY_LOCK_FILE:-/tmp/dmis-auto-deploy.lock}
DRY_RUN=${DMIS_DEPLOY_DRY_RUN:-0}

log() {
    printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf 'DRY-RUN:'
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi
    "$@"
}

command -v git >/dev/null || fail "找不到 git"
command -v docker >/dev/null || fail "找不到 docker"
command -v curl >/dev/null || fail "找不到 curl"
command -v flock >/dev/null || fail "找不到 flock"
[[ -d "$PROJECT_DIR/.git" ]] || fail "找不到 Git repository：$PROJECT_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "已有部署程序執行中，本輪略過"
    exit 0
fi

cd "$PROJECT_DIR"

current_branch=$(git branch --show-current)
[[ "$current_branch" == "$DEPLOY_BRANCH" ]] ||
    fail "目前 branch 為 $current_branch，預期為 $DEPLOY_BRANCH"

log "檢查 origin/$DEPLOY_BRANCH"
git fetch --quiet origin "$DEPLOY_BRANCH"

local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse "origin/$DEPLOY_BRANCH")

if [[ "$local_sha" == "$remote_sha" ]]; then
    log "已是最新版本：${local_sha:0:12}"
    exit 0
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    fail "工作樹有未提交變更，為避免覆蓋資料，本輪不部署"
fi

git merge-base --is-ancestor "$local_sha" "$remote_sha" ||
    fail "遠端不是 fast-forward 更新，需要人工處理"

mapfile -t changed_modules < <(
    git diff --name-only "$local_sha" "$remote_sha" |
        awk -F/ '/^addons\/[^/]+\// {print $2}' |
        sort -u |
        while read -r module; do
            [[ -f "addons/${module}/__manifest__.py" ]] && printf '%s\n' "$module"
        done
)

runtime_changed=0
if git diff --name-only "$local_sha" "$remote_sha" |
    grep -Eq '^(addons/|Dockerfile$|docker-compose\.yml$)'; then
    runtime_changed=1
fi

if [[ "$runtime_changed" == "0" ]]; then
    log "本次只有文件或部署工具變更，僅更新 Git，不重啟服務"
    run git merge --ff-only "origin/$DEPLOY_BRANCH"
    log "程式同步成功：${local_sha:0:12} -> ${remote_sha:0:12}"
    exit 0
fi

mkdir -p "$BACKUP_DIR"
backup_file="${BACKUP_DIR}/${ODOO_DB}_$(date +%Y%m%d_%H%M%S)_${local_sha:0:12}.sql.gz"
log "備份資料庫至 $backup_file"
if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY-RUN: docker compose exec db pg_dump | gzip"
else
    docker compose exec -T db sh -c \
        'pg_dump -U "$POSTGRES_USER" "$1"' sh "$ODOO_DB" |
        gzip -c >"$backup_file"
    [[ -s "$backup_file" ]] || fail "資料庫備份檔為空"
fi

log "更新程式至 ${remote_sha:0:12}"
run git merge --ff-only "origin/$DEPLOY_BRANCH"

log "重建 Odoo image"
run docker compose build odoo

if ((${#changed_modules[@]} > 0)); then
    modules_csv=$(IFS=,; echo "${changed_modules[*]}")
    log "升級 Odoo modules：$modules_csv"
    run docker compose stop odoo
    run docker compose run --rm odoo \
        -d "$ODOO_DB" -u "$modules_csv" --stop-after-init --no-http
fi

log "啟動服務"
run docker compose up -d odoo cloudflared

if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY-RUN 完成"
    exit 0
fi

TIMEOUT=${DMIS_SMOKE_TIMEOUT:-180} ./scripts/smoke_odoo.sh
docker compose ps

find "$BACKUP_DIR" -maxdepth 1 -type f -name "${ODOO_DB}_*.sql.gz" \
    -mtime "+$BACKUP_RETENTION_DAYS" -delete

log "部署成功：${local_sha:0:12} -> ${remote_sha:0:12}"
