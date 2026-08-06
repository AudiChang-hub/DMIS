#!/usr/bin/env python3
"""
把所有自訂 Dashboard 的 dashcard 佈局從 18 欄比例擴展到 24 欄。

排版策略：
  - P1: 長條圖 16 + 圓餅圖 8，明細表 24
  - P16: 圓餅 8 + 長條 16
  - P17: 3 欄 → 每欄 8
  - P18/P19: 2 欄 → 每欄 12
  - P22: 3 欄 → 每欄 8
  - 其他單欄/雙欄: size_x → 24
"""
import argparse, json, requests, sys
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()
SKIP = {1}  # E-commerce

def get_session():
    r = requests.post(f"{BASE}/session",
                      json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return {"X-Metabase-Session": r.json()["id"]}


def widen_cards(cards, dash_name):
    """回傳已調整過 col/size_x 的 cards（in-place 修改）"""
    changed = 0
    max_right = max((c["col"] + c["size_x"] for c in cards), default=0)
    if max_right >= 23:
        return 0  # 已經接近 24 欄

    for c in cards:
        old_col, old_sx = c["col"], c["size_x"]

        # P1 等雙欄版面 (長條12 + 圓餅6  → 長條16 + 圓餅8)
        if old_sx == 12 and old_col == 0:
            c["size_x"] = 16
        elif old_sx == 6 and old_col == 12:
            c["col"] = 16
            c["size_x"] = 8
        # 單欄 18 → 24
        elif old_sx == 18 and old_col == 0:
            c["size_x"] = 24
        # P16 特殊 (8 + 10 → 8 + 16)
        elif old_sx == 10 and old_col == 8:
            c["size_x"] = 16
        elif old_sx == 8 and old_col == 0:
            pass  # 保持不變 (P16-1 圓餅, P17/P22 3欄)
        # P17/P22 三欄 (每欄6 → 每欄8)
        elif old_sx == 6 and old_col == 0:
            c["size_x"] = 8
        elif old_sx == 6 and old_col == 6:
            c["col"] = 8
            c["size_x"] = 8
        elif old_sx == 6 and old_col == 12:
            c["col"] = 16
            c["size_x"] = 8
        # P18/P19 雙欄 (每欄9 → 每欄12)
        elif old_sx == 9 and old_col == 0:
            c["size_x"] = 12
        elif old_sx == 9 and old_col == 9:
            c["col"] = 12
            c["size_x"] = 12

        if c["col"] != old_col or c["size_x"] != old_sx:
            changed += 1

    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    headers = get_session()

    resp = requests.get(f"{BASE}/dashboard", headers=headers)
    dashboards = [d for d in resp.json() if d["id"] not in SKIP]

    total_updated = 0
    for d in sorted(dashboards, key=lambda x: x["id"]):
        did = d["id"]
        detail = requests.get(f"{BASE}/dashboard/{did}", headers=headers).json()
        cards = detail.get("dashcards", [])
        if not cards:
            continue

        changed = widen_cards(cards, d["name"])
        if changed == 0:
            print(f"  SKIP  Dashboard #{did} {d['name']} (已全幅或無需調整)")
            continue

        max_right = max((c["col"] + c["size_x"] for c in cards), default=0)
        print(f"  {'APPLY' if args.apply else 'DRY'}  Dashboard #{did} {d['name']} "
              f"→ {changed} cards adjusted, max_right={max_right}")

        if args.apply:
            payload = {"cards": [
                {k: c[k] for k in ("id", "card_id", "dashboard_id", "size_x", "size_y",
                                    "row", "col", "parameter_mappings",
                                    "visualization_settings")
                 if k in c}
                for c in cards
            ]}
            r = requests.put(f"{BASE}/dashboard/{did}/cards",
                             headers=headers, json=payload)
            if r.status_code == 200:
                total_updated += 1
            else:
                print(f"    ERROR: {r.status_code} {r.text[:200]}")

    print(f"\n{'Applied' if args.apply else 'Would apply'}: {total_updated} dashboards")


if __name__ == "__main__":
    main()
