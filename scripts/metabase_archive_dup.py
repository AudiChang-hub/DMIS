#!/usr/bin/env python3
"""Deprecated: 避免再次封存 Odoo 仍在使用的 P21 dashboard。

歷史上曾封存 Dashboard #22「P21 基隆公益青年統計（複本）」，
但目前 Odoo 選單 `電動車 > 基隆公益青年 > 統計表` 仍直接使用它的 public UUID。
若再次封存，前台會變成空白頁。

使用方式：
    python3 scripts/metabase_archive_dup.py            # 顯示保護訊息與目前狀態
    python3 scripts/metabase_archive_dup.py --force    # 真的要封存時才允許執行

封存動作可逆：Metabase 後台 -> 已封存 -> 還原。
"""
import sys
import requests

BASE = "http://localhost:3000/api"
DUP_DASHBOARD_ID = 22  # "P21 基隆公益青年統計（複本）"


def login():
    r = requests.post(f"{BASE}/session", json={"username": "admin@dmis.local", "password": "Dmis2026!"})
    r.raise_for_status()
    return r.json()["id"]


def main():
    force_mode = "--force" in sys.argv
    tok = login()
    h = {"X-Metabase-Session": tok}

    r = requests.get(f"{BASE}/dashboard/{DUP_DASHBOARD_ID}", headers=h)
    r.raise_for_status()
    d = r.json()
    print(f"Target dashboard id={d['id']} name={d['name']} archived={d.get('archived')}")
    cards = d.get("dashcards") or []
    print(f"  Dashcards: {len(cards)}")
    for dc in cards:
        c = dc.get("card") or {}
        print(f"    - card_id={dc.get('card_id')} name={c.get('name')}")

    if not force_mode:
        print("\n[guarded] P21 目前仍被 Odoo 選單使用，預設禁止封存。若你非常確定要封存，請改用 --force。")
        return

    if d.get("archived"):
        print("已封存，無需再次執行。")
        return

    r = requests.put(
        f"{BASE}/dashboard/{DUP_DASHBOARD_ID}",
        headers=h,
        json={"archived": True},
    )
    r.raise_for_status()
    print(f"[applied] archived=True 已寫入；可於 Metabase 『已封存』檢視還原。")


if __name__ == "__main__":
    main()
