#!/usr/bin/env python3
"""封存 P14 歷史 dashboard 的輔助工具。

P14 已不再掛入 Odoo `電動車 > 基隆公益青年` 選單；若要清理
Metabase 內的歷史 dashboard，可用此腳本手動封存。

使用方式：
    python3 scripts/metabase_archive_dup.py            # dry-run：顯示目前狀態
    python3 scripts/metabase_archive_dup.py --force    # 實際封存

封存動作可逆：Metabase 後台 -> 已封存 -> 還原。
"""
import sys
import requests
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()
DUP_DASHBOARD_ID = 22  # "P14 基隆公益青年統計（複本）"


def login():
    r = requests.post(f"{BASE}/session", json={"username": EMAIL, "password": PASSWORD})
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
        print("\n[dry-run] P14 已不在 Odoo 選單中。若你要封存這張歷史 dashboard，請改用 --force。")
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
