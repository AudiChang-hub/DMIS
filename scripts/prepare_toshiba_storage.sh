#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_CONFIRMATION="67EFCNQHT"
DISK=/dev/disk/by-id/ata-TOSHIBA_MQ01ACF050_67EFCNQHT
PARTITION=/dev/disk/by-id/ata-TOSHIBA_MQ01ACF050_67EFCNQHT-part2
MOUNT_POINT=/srv/dmis-data
OWNER_USER=${SUDO_USER:-audi}

if [[ ${EUID} -ne 0 ]]; then
    echo "ERROR: 請使用 sudo 執行。" >&2
    exit 1
fi
if [[ ${1:-} != "--confirm-erase=${EXPECTED_CONFIRMATION}" ]]; then
    echo "ERROR: 必須明確帶入 --confirm-erase=${EXPECTED_CONFIRMATION}" >&2
    exit 1
fi
[[ -b "$DISK" && -b "$PARTITION" ]] || {
    echo "ERROR: 找不到指定 Toshiba 磁碟或第二分割區。" >&2
    exit 1
}

model=$(lsblk -dn -o MODEL "$DISK" | xargs)
serial=$(lsblk -dn -o SERIAL "$DISK" | xargs)
[[ "$model" == "TOSHIBA MQ01ACF050" && "$serial" == "$EXPECTED_CONFIRMATION" ]] || {
    echo "ERROR: 磁碟身分不符：model=$model serial=$serial" >&2
    exit 1
}
if findmnt --source "$PARTITION" >/dev/null; then
    echo "ERROR: 目標分割區目前已掛載，拒絕格式化。" >&2
    exit 1
fi

if ! command -v smartctl >/dev/null; then
    apt-get update
    apt-get install -y smartmontools
fi
smart_output=$(smartctl -H -A "$DISK")
printf '%s\n' "$smart_output"
grep -Eq 'SMART overall-health self-assessment test result:[[:space:]]+PASSED|SMART Health Status:[[:space:]]+OK' \
    <<<"$smart_output" || {
    echo "ERROR: SMART 健康檢查未通過，拒絕格式化。" >&2
    exit 1
}
for attribute_id in 5 197 198; do
    raw_value=$(awk -v id="$attribute_id" '$1 == id {print $10}' <<<"$smart_output")
    if [[ -n "$raw_value" && "$raw_value" != "0" ]]; then
        echo "ERROR: SMART attribute $attribute_id=$raw_value，拒絕格式化。" >&2
        exit 1
    fi
done

backup_dir=/home/audi/project/DMIS-next/backups/storage-migration
mkdir -p "$backup_dir"
sfdisk --dump "$DISK" >"$backup_dir/partition-table-before-$(date +%Y%m%d_%H%M%S).sfdisk"
cp -a /etc/fstab "$backup_dir/fstab-before-$(date +%Y%m%d_%H%M%S)"
echo "格式化前偵測到的 signatures："
wipefs -n "$PARTITION" || true

mkfs.ext4 -F -L DMIS_DATA "$PARTITION"
uuid=$(blkid -s UUID -o value "$PARTITION")
[[ -n "$uuid" ]] || {
    echo "ERROR: 無法取得新檔案系統 UUID。" >&2
    exit 1
}
mkdir -p "$MOUNT_POINT"
if ! grep -qF "UUID=$uuid " /etc/fstab; then
    printf 'UUID=%s %s ext4 defaults,nofail 0 2\n' "$uuid" "$MOUNT_POINT" >>/etc/fstab
fi
mount "$MOUNT_POINT"
install -d -o "$OWNER_USER" -g "$OWNER_USER" -m 0750 \
    "$MOUNT_POINT/dmis-next" \
    "$MOUNT_POINT/dmis-next/media" \
    "$MOUNT_POINT/dmis-next/backups"

findmnt "$MOUNT_POINT"
df -hT "$MOUNT_POINT"
echo "Toshiba 儲存空間準備完成。"
