#!/usr/bin/env python3
"""
為 Metabase Dashboard 新增頂部篩選器（對齊 DataStudio 原設計）。

多數頁面使用：
    - 領牌年月（date/all-options → license_date）
    - 銷售來源（string/= → sales_source）

P4 基隆公益青年例外使用：
    - 領牌年月（date/all-options → license_date）
    - 品牌（string/= → brand_type）

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
FIELD_BRAND_TYPE = 1649

# P7 / P8 / P12 / P13 使用 native template-tag 篩選，改由專用修復腳本維護，
# 避免被通用 field-mapping 邏輯覆寫成錯誤的參數組合。
DASHBOARD_IDS = [2, 3, 4, 18, 5, 6, 9, 10, 11, 14, 15, 16, 17, 19, 20, 21, 22, 23]


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


def dashboard_param_config(dash_id, pid_ym, pid_src, pid_brand, brand_values_card_id=None):
    if dash_id == 18:
        brand_param = build_param("品牌", "brand", "string/=", "string", pid_brand)
        if brand_values_card_id:
            brand_param["values_source_type"] = "card"
            brand_param["values_source_config"] = {
                "card_id": brand_values_card_id,
                "value_field": ["field", FIELD_BRAND_TYPE, {"base-type": "type/Text"}],
            }
        return {
            "parameters": [
                build_param("領牌年月", "license_ym", "date/all-options", "date", pid_ym),
                brand_param,
            ],
            "mappings": [
                (pid_ym, FIELD_LICENSE_DATE, "type/Date"),
                (pid_brand, FIELD_BRAND_TYPE, "type/Text"),
            ],
        }
    return {
        "parameters": [
            build_param("領牌年月", "license_ym", "date/all-options", "date", pid_ym),
            build_param("銷售來源", "sales_source", "string/=", "string", pid_src),
        ],
        "mappings": [
            (pid_ym, FIELD_LICENSE_DATE, "type/Date"),
            (pid_src, FIELD_SALES_SOURCE, "type/Text"),
        ],
    }


def main():
    tok = login()
    print("[OK] Logged in")

    # 每個 dashboard 用固定 id 才能穩定對映；但同一組 param id 在 22 個 dashboard 上重複使用沒問題
    PID_YM = "ds_license_ym"
    PID_SRC = "ds_sales_source"
    PID_BRAND = "ds_brand"

    target_dashboards = DASHBOARD_IDS
    for arg in sys.argv[1:]:
        if arg.startswith("--dashboard-id="):
            target_dashboards = [int(arg.split("=", 1)[1])]

    changed = 0
    for dash_id in target_dashboards:
        try:
            d = api(tok, "get", f"/dashboard/{dash_id}")
        except requests.HTTPError as e:
            print(f"[SKIP] dashboard {dash_id}: {e}")
            continue

        dashcards = d.get("dashcards", [])
        brand_values_card_id = None
        if dash_id == 18:
            for dc in dashcards:
                card = dc.get("card") or {}
                if (card.get("name") or "").startswith("P4-1 "):
                    brand_values_card_id = dc.get("card_id")
                    break

        config = dashboard_param_config(dash_id, PID_YM, PID_SRC, PID_BRAND)
        if dash_id == 18:
            config = dashboard_param_config(
                dash_id,
                PID_YM,
                PID_SRC,
                PID_BRAND,
                brand_values_card_id=brand_values_card_id,
            )

        new_dashcards = []
        for dc in dashcards:
            card = dc.get("card") or {}
            mappings = []
            for parameter_id, field_id, base_type in config["mappings"]:
                if not card_uses_field(card, field_id) and field_id != FIELD_LICENSE_DATE:
                    continue
                mappings.append({
                    "parameter_id": parameter_id,
                    "card_id": dc.get("card_id"),
                    "target": ["dimension", ["field", field_id, {"base-type": base_type}]],
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
            "parameters": config["parameters"],
            "dashcards": new_dashcards,
        }
        try:
            api(tok, "put", f"/dashboard/{dash_id}", payload)
            print(f"[OK] dashboard {dash_id} '{d['name']}' — {len(config['parameters'])} filters, {len(new_dashcards)} cards mapped")
            changed += 1
        except requests.HTTPError as e:
            print(f"[FAIL] dashboard {dash_id}: {e} — {e.response.text[:300] if e.response else ''}")

    print(f"\n[DONE] Updated {changed}/{len(target_dashboards)} dashboards")


if __name__ == "__main__":
    main()
