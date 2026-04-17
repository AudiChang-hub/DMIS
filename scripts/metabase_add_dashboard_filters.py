#!/usr/bin/env python3
"""
為 22 個 Dashboard 新增頂部篩選器（對齊 DataStudio 原設計）：
  - 領牌年月（date/all-options → license_date）
  - 銷售來源（string/= → sales_source）

Metabase 參數透過 parameter_mappings 對映到每張卡片的欄位。
"""
import json
import uuid
import requests
import sys

BASE = "http://localhost:3000/api"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"

FIELD_LICENSE_DATE = 1629
FIELD_SALES_SOURCE = 1647

DASHBOARD_IDS = [2, 3, 4, 18, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22, 23]


def login():
    r = requests.post(f"{BASE}/session", json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def api(token, method, path, data=None):
    h = {"X-Metabase-Session": token, "Content-Type": "application/json"}
    fn = getattr(requests, method)
    r = fn(f"{BASE}{path}", headers=h, json=data) if data else fn(f"{BASE}{path}", headers=h)
    r.raise_for_status()
    return r.json() if r.text else {}


def card_uses_field(card, field_id):
    """檢查 card 的 dataset_query 是否引用某 field_id。"""
    dq = card.get("dataset_query") or {}
    s = json.dumps(dq)
    return f"{field_id}" in s


def build_param(name, slug, ptype, section, pid):
    return {
        "name": name,
        "slug": slug,
        "id": pid,
        "type": ptype,
        "sectionId": section,
    }


def main():
    tok = login()
    print("[OK] Logged in")

    # 每個 dashboard 用固定 id 才能穩定對映；但同一組 param id 在 22 個 dashboard 上重複使用沒問題
    PID_YM = "ds_license_ym"
    PID_SRC = "ds_sales_source"

    params = [
        build_param("領牌年月", "license_ym", "date/all-options", "date", PID_YM),
        build_param("銷售來源", "sales_source", "string/=", "string", PID_SRC),
    ]

    changed = 0
    for dash_id in DASHBOARD_IDS:
        try:
            d = api(tok, "get", f"/dashboard/{dash_id}")
        except requests.HTTPError as e:
            print(f"[SKIP] dashboard {dash_id}: {e}")
            continue

        dashcards = d.get("dashcards", [])
        new_dashcards = []
        for dc in dashcards:
            card = dc.get("card") or {}
            mappings = []
            if card_uses_field(card, FIELD_LICENSE_DATE) or True:
                # license_date 是所有卡片都有的主要日期欄
                mappings.append({
                    "parameter_id": PID_YM,
                    "card_id": dc.get("card_id"),
                    "target": ["dimension", ["field", FIELD_LICENSE_DATE, {"base-type": "type/Date"}]],
                })
            if card_uses_field(card, FIELD_SALES_SOURCE) or True:
                mappings.append({
                    "parameter_id": PID_SRC,
                    "card_id": dc.get("card_id"),
                    "target": ["dimension", ["field", FIELD_SALES_SOURCE, {"base-type": "type/Text"}]],
                })
            new_dc = {
                "id": dc["id"],
                "card_id": dc.get("card_id"),
                "row": dc.get("row", 0),
                "col": dc.get("col", 0),
                "size_x": dc.get("size_x", 12),
                "size_y": dc.get("size_y", 6),
                "parameter_mappings": mappings,
                "visualization_settings": dc.get("visualization_settings", {}),
                "series": dc.get("series", []),
            }
            new_dashcards.append(new_dc)

        payload = {
            "parameters": params,
            "dashcards": new_dashcards,
        }
        try:
            api(tok, "put", f"/dashboard/{dash_id}", payload)
            print(f"[OK] dashboard {dash_id} '{d['name']}' — +2 filters, {len(new_dashcards)} cards mapped")
            changed += 1
        except requests.HTTPError as e:
            print(f"[FAIL] dashboard {dash_id}: {e} — {e.response.text[:300] if e.response else ''}")

    print(f"\n[DONE] Updated {changed}/{len(DASHBOARD_IDS)} dashboards")


if __name__ == "__main__":
    main()
