#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT_DIR=${DMIS_NEXT_PROJECT_DIR:-/home/audi/project/DMIS-next}
DATA_ROOT=${DMIS_DATA_ROOT:-/srv/dmis-data/dmis-next}
COMPOSE_FILE=${DMIS_COMPOSE_FILE:-${PROJECT_DIR}/docker-compose.django.yml}
MEDIA_DIR=${DJANGO_MEDIA_PATH:-${DATA_ROOT}/media}
BACKUP_ROOT=${DMIS_BACKUP_ROOT:-${DATA_ROOT}/backups}
LOCK_FILE=${DMIS_BACKUP_LOCK_FILE:-${DATA_ROOT}/.backup.lock}
# 部署前備份只建立新備份；過期清理只由每日排程（root）執行，避免部署帳號刪不掉 root 檔案而中止部署。
SKIP_PRUNE=${DMIS_BACKUP_SKIP_PRUNE:-0}

log() {
    printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "已有備份程序執行中，本輪略過"
    exit 0
fi

[[ -d "$PROJECT_DIR/.git" ]] || {
    log "ERROR: 找不到專案：$PROJECT_DIR"
    exit 1
}
[[ -d "$MEDIA_DIR" ]] || {
    log "ERROR: 找不到媒體目錄：$MEDIA_DIR"
    exit 1
}

mkdir -p \
    "$BACKUP_ROOT/postgres/daily" \
    "$BACKUP_ROOT/postgres/weekly" \
    "$BACKUP_ROOT/postgres/monthly" \
    "$BACKUP_ROOT/media/weekly" \
    "$BACKUP_ROOT/media/monthly" \
    "$BACKUP_ROOT/media-current"

cd "$PROJECT_DIR"
timestamp=$(date +%Y%m%d_%H%M%S)
daily_db="$BACKUP_ROOT/postgres/daily/dmis_${timestamp}.sql.gz"
log "建立 PostgreSQL 每日備份"
docker compose -f "$COMPOSE_FILE" exec -T db sh -c \
    'pg_dump --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"' |
    gzip -c >"${daily_db}.partial"
gzip -t "${daily_db}.partial"
mv "${daily_db}.partial" "$daily_db"
[[ -s "$daily_db" ]] || {
    rm -f "$daily_db"
    log "ERROR: PostgreSQL 備份檔為空"
    exit 1
}

log "同步目前媒體鏡像"
rsync -a --delete "$MEDIA_DIR/" "$BACKUP_ROOT/media-current/"

# 週／月封存每期只建立一次：已存在（例如凌晨排程以 root 建立）就保留原檔，
# 避免同一天部署時覆寫被拒而中止部署。
archive_db() {
    local target=$1
    if [[ -e "$target" ]]; then
        log "封存已存在，保留原檔：$target"
        return 0
    fi
    cp "$daily_db" "${target}.partial"
    mv "${target}.partial" "$target"
}

archive_media() {
    local target=$1
    if [[ -e "$target" ]]; then
        log "封存已存在，保留原檔：$target"
        return 0
    fi
    tar -C "$MEDIA_DIR" -czf "${target}.partial" .
    mv "${target}.partial" "$target"
}

if [[ "$(date +%u)" == "7" ]]; then
    archive_db "$BACKUP_ROOT/postgres/weekly/dmis_$(date +%G-W%V).sql.gz"
    log "建立每週媒體封存"
    archive_media "$BACKUP_ROOT/media/weekly/media_$(date +%G-W%V).tar.gz"
fi

if [[ "$(date +%d)" == "01" ]]; then
    archive_db "$BACKUP_ROOT/postgres/monthly/dmis_$(date +%Y-%m).sql.gz"
    log "建立每月媒體封存"
    archive_media "$BACKUP_ROOT/media/monthly/media_$(date +%Y-%m).tar.gz"
fi
if [[ "$SKIP_PRUNE" == "1" ]]; then
    log "略過過期備份清理，交由每日備份排程執行"
else
    find "$BACKUP_ROOT/postgres/daily" -type f -name '*.sql.gz' -mtime +14 -delete
    find "$BACKUP_ROOT/postgres/weekly" -type f -name '*.sql.gz' -mtime +56 -delete
    find "$BACKUP_ROOT/postgres/monthly" -type f -name '*.sql.gz' -mtime +370 -delete
    find "$BACKUP_ROOT/media/weekly" -type f -name '*.tar.gz' -mtime +56 -delete
    find "$BACKUP_ROOT/media/monthly" -type f -name '*.tar.gz' -mtime +370 -delete
fi

log "備份完成：$daily_db"
