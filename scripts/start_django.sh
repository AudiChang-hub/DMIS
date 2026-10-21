#!/usr/bin/env sh
set -eu

# 靜態檔已在建置 image 時整理好（Dockerfile.django）。
# 正式站藍綠部署由部署腳本先套用 migration，再啟動新版，所以設 DMIS_RUN_MIGRATIONS=0 略過。
if [ "${DMIS_RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi
exec daphne   --bind 0.0.0.0   --port 8000   --proxy-headers   config.asgi:application
