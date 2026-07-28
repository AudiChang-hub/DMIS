#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=${DMIS_PROJECT_DIR:-/home/audi/project/DMIS}
USER_SYSTEMD_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user

[[ -f "$PROJECT_DIR/deployment/systemd/dmis-auto-deploy.service" ]] ||
    { echo "找不到 systemd service 檔案"; exit 1; }

mkdir -p "$USER_SYSTEMD_DIR"
install -m 0644 \
    "$PROJECT_DIR/deployment/systemd/dmis-auto-deploy.service" \
    "$USER_SYSTEMD_DIR/dmis-auto-deploy.service"
install -m 0644 \
    "$PROJECT_DIR/deployment/systemd/dmis-auto-deploy.timer" \
    "$USER_SYSTEMD_DIR/dmis-auto-deploy.timer"
chmod +x "$PROJECT_DIR/scripts/auto_deploy.sh"

systemctl --user daemon-reload
systemctl --user enable --now dmis-auto-deploy.timer
systemctl --user status dmis-auto-deploy.timer --no-pager

echo "安裝完成。查看部署日誌："
echo "journalctl --user -u dmis-auto-deploy.service -n 100 --no-pager"
