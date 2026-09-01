#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=${DMIS_NEXT_PROJECT_DIR:-/home/audi/project/DMIS-next}
SYSTEMD_DIR=/etc/systemd/system

if [[ ${EUID} -ne 0 ]]; then
    echo "ERROR: 請使用 sudo 執行。" >&2
    exit 1
fi

install -m 0644 "$PROJECT_DIR/deployment/systemd/dmis-next-price-list-distribution.service" "$SYSTEMD_DIR/dmis-next-price-list-distribution.service"
install -m 0644 "$PROJECT_DIR/deployment/systemd/dmis-next-price-list-distribution.timer" "$SYSTEMD_DIR/dmis-next-price-list-distribution.timer"
systemctl daemon-reload
systemctl enable --now dmis-next-price-list-distribution.timer
systemctl status dmis-next-price-list-distribution.timer --no-pager
