#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=${DMIS_NEXT_PROJECT_DIR:-/home/audi/project/DMIS-next}
SYSTEMD_DIR=/etc/systemd/system

if [[ ${EUID} -ne 0 ]]; then
    echo "ERROR: 請使用 sudo 執行。" >&2
    exit 1
fi

install -m 0644 \
    "$PROJECT_DIR/deployment/systemd/dmis-next-order-archive-sync.service" \
    "$SYSTEMD_DIR/dmis-next-order-archive-sync.service"
install -m 0644 \
    "$PROJECT_DIR/deployment/systemd/dmis-next-order-archive-sync.timer" \
    "$SYSTEMD_DIR/dmis-next-order-archive-sync.timer"
systemctl daemon-reload
systemctl enable --now dmis-next-order-archive-sync.timer
systemctl status dmis-next-order-archive-sync.timer --no-pager
