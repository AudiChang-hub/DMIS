#!/usr/bin/env python3
"""
修正 Metabase Questions，讓 P1/P3/P4/P5/P6/P9/P10/P14/P15 等頁面
的長條圖從垂直 (bar) 改為水平 (row)，對齊 DataStudio 原設計。
也同步更新 visualization_settings 顯示資料標籤。
"""
import requests

BASE = "http://localhost:3000/api"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"


def login():
    r = requests.post(f"{BASE}/session", json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def api(token, method, path, data=None):
    headers = {"X-Metabase-Session": token, "Content-Type": "application/json"}
    fn = getattr(requests, method)
    r = fn(f"{BASE}{path}", headers=headers, json=data) if data else fn(f"{BASE}{path}", headers=headers)
    r.raise_for_status()
    return r.json() if r.text else {}


# 規格中 P1/P3/P4/P5/P6/P9/P10/P14/P15 為「水平堆疊」的 Question 名稱關鍵字
# 以 name 開頭比對
HORIZONTAL_PREFIXES = [
    "P1-1 ", "P1-3 ",          # P1 兩張水平堆疊
    "P3-1 ", "P3-2 ",          # P3 兩張水平堆疊
    "P4-1 ",                   # P4 水平堆疊
    "P5-1 ",                   # P5 水平堆疊
    "P6-1 ",                   # P6 水平堆疊
    "P9-1 ", "P9-2 ",          # P9 兩張水平堆疊
    "P10-1 ",                  # P10 水平堆疊
    "P11-1 ",                  # P11 水平堆疊
    "P14 ",                    # P14 水平堆疊（無序號）
    "P15 ",                    # P15 水平堆疊（無序號）
    "P16-2 ",                  # P16 水平堆疊（性別×年齡 另有 pie）
    "P20 ",                    # P20 水平堆疊（無序號）
]


def main():
    token = login()
    print("[OK] Logged in")

    # 取得 SUZUKI銷售統計 collection
    cards = api(token, "get", "/card?f=mine")
    # 或列出全部
    all_cards = api(token, "get", "/card")
    print(f"Total cards: {len(all_cards)}")

    changed = 0
    for card in all_cards:
        name = card.get("name", "")
        if not any(name.startswith(p) for p in HORIZONTAL_PREFIXES):
            continue
        if card.get("display") == "row":
            continue
        if card.get("display") != "bar":
            continue

        # 保留原 viz_settings，追加資料標籤
        viz = dict(card.get("visualization_settings") or {})
        viz.setdefault("stackable.stack_type", "stacked")
        viz.setdefault("graph.show_values", True)

        card_id = card["id"]
        print(f"  [UPDATE] card {card_id} '{name}' bar → row")
        api(token, "put", f"/card/{card_id}", {
            "display": "row",
            "visualization_settings": viz,
        })
        changed += 1

    print(f"\n[OK] Changed {changed} cards to horizontal (row)")


if __name__ == "__main__":
    main()
