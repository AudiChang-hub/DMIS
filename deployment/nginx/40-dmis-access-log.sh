#!/bin/sh
# tunnel-proxy 啟動前執行（nginx 映像的 /docker-entrypoint.d）：上一段存取紀錄改名壓縮，保留 30 天（T-59）。
set -eu
dir=/var/log/dmis
mkdir -p "$dir"
if [ -s "$dir/access.log" ]; then
    stamp=$(date +%Y%m%d-%H%M%S)
    mv "$dir/access.log" "$dir/access-$stamp.log"
    gzip -f "$dir/access-$stamp.log" || true
fi
find "$dir" -name 'access-*.log.gz' -mtime +30 -delete || true
