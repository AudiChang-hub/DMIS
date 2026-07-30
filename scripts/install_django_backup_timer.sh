#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=${DMIS_NEXT_PROJECT_DIR:-/home/audi/project/DMIS-next}
USER_SYSTEMD_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user

mkdir -p "$USER_SYSTEMD_DIR"
install -m 0644 \
    "$PROJECT_DIR/deployment/systemd/dmis-next-backup.service" \
    "$USER_SYSTEMD_DIR/dmis-next-backup.service"
install -m 0644 \
    "$PROJECT_DIR/deployment/systemd/dmis-next-backup.timer" \
    "$USER_SYSTEMD_DIR/dmis-next-backup.timer"
systemctl --user daemon-reload
systemctl --user enable --now dmis-next-backup.timer
systemctl --user status dmis-next-backup.timer --no-pager
