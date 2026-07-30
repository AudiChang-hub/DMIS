#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=${DMIS_NEXT_PROJECT_DIR:-/home/audi/project/DMIS-next}
DATA_ROOT=${DMIS_DATA_ROOT:-/srv/dmis-data/dmis-next}
COMPOSE_FILE=${DMIS_COMPOSE_FILE:-${PROJECT_DIR}/docker-compose.django.yml}
MEDIA_DIR=${DJANGO_MEDIA_PATH:-${DATA_ROOT}/media}
BACKUP_ROOT=${DMIS_BACKUP_ROOT:-${DATA_ROOT}/backups}
LOCK_FILE=${DMIS_BACKUP_LOCK_FILE:-/tmp/dmis-next-backup.lock}

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
    'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' |
    gzip -c >"$daily_db"
[[ -s "$daily_db" ]] || {
    rm -f "$daily_db"
    log "ERROR: PostgreSQL 備份檔為空"
    exit 1
}

log "同步目前媒體鏡像"
rsync -a --delete "$MEDIA_DIR/" "$BACKUP_ROOT/media-current/"

if [[ "$(date +%u)" == "7" ]]; then
    cp -f "$daily_db" \
        "$BACKUP_ROOT/postgres/weekly/dmis_$(date +%G-W%V).sql.gz"
    log "建立每週媒體封存"
    tar -C "$MEDIA_DIR" -czf \
        "$BACKUP_ROOT/media/weekly/media_$(date +%G-W%V).tar.gz" .
fi

if [[ "$(date +%d)" == "01" ]]; then
    cp -f "$daily_db" \
        "$BACKUP_ROOT/postgres/monthly/dmis_$(date +%Y-%m).sql.gz"
    log "建立每月媒體封存"
    tar -C "$MEDIA_DIR" -czf \
        "$BACKUP_ROOT/media/monthly/media_$(date +%Y-%m).tar.gz" .
fi

find "$BACKUP_ROOT/postgres/daily" -type f -name '*.sql.gz' -mtime +14 -delete
find "$BACKUP_ROOT/postgres/weekly" -type f -name '*.sql.gz' -mtime +56 -delete
find "$BACKUP_ROOT/postgres/monthly" -type f -name '*.sql.gz' -mtime +370 -delete
find "$BACKUP_ROOT/media/weekly" -type f -name '*.tar.gz' -mtime +56 -delete
find "$BACKUP_ROOT/media/monthly" -type f -name '*.tar.gz' -mtime +370 -delete

log "備份完成：$daily_db"
