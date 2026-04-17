#!/usr/bin/env python3
"""Phase 3 輔助：封存 (archive) Metabase Dashboard #22「P21 基隆公益青年統計（複本）」。

使用方式：
    python3 scripts/metabase_archive_dup.py            # dry-run：只顯示將要封存的 dashboard
    python3 scripts/metabase_archive_dup.py --apply    # 實際寫入

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
    apply_mode = "--apply" in sys.argv
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

    if not apply_mode:
        print("\n[dry-run] 未實際封存。加 --apply 以執行。")
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
