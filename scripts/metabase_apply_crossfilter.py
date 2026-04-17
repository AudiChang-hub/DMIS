#!/usr/bin/env python3
"""為所有 Metabase 儀表板的圖表 dashcard 設定 crossfilter click_behavior。

當使用者點擊圖表中的資料點（長條/圓餅），即自動更新同一 dashboard 的日期/銷售來源篩選，
其他卡片同步重新查詢 — 復刻 DataStudio「交叉篩選」行為。

用法：
    python3 scripts/metabase_apply_crossfilter.py             # dry-run
    python3 scripts/metabase_apply_crossfilter.py --apply     # 寫入
"""
from __future__ import annotations
import copy, sys, json
import requests

BASE = "http://localhost:3000/api"
SKIP_DASHBOARD_IDS = {1}  # E-commerce 範例，不動
SKIP_DISPLAY = {"table", "pivot", "smartscalar", "scalar", "text"}  # 不需要 click 的類型

# field_id → column_name (ds_sales_report 欄位)
FIELD_MAP = {
    1625: "id", 1626: "order_name", 1627: "state", 1628: "order_date",
    1629: "license_date", 1630: "license_ym", 1631: "sort_license_date",
    1632: "model", 1633: "car_color", 1634: "model_color",
    1635: "dealer", 1636: "dealer_not_null", 1637: "vin_or_en",
    1638: "license_plate", 1639: "energy_type", 1640: "motor_type",
    1641: "owner_name", 1642: "sex", 1643: "age", 1644: "age_group",
    1645: "region", 1646: "region_district", 1647: "sales_source",
    1648: "sales_type", 1649: "brand_type",
    1650: "receipt_price", 1651: "cost", 1652: "net_profit",
    1653: "dealer_comm_out", 1654: "friendly_bonus_out",
    1655: "first_sale_bonus", 1656: "basic_bonus", 1657: "dealer_receipt",
    1658: "company_gift", 1659: "platform_gift", 1660: "gift_card",
    1661: "subsidy_plan", 1662: "settle_date", 1663: "apply_date",
    1664: "volume_bonus", 1665: "total_commission", 4366: "remark",
}

DISPLAY_NAMES = {
    "license_date": "License Date", "license_ym": "License Ym",
    "sales_source": "Sales Source", "energy_type": "Energy Type",
    "motor_type": "Motor Type", "model": "Model", "car_color": "Car Color",
    "dealer": "Dealer", "sex": "Sex", "age_group": "Age Group",
    "region": "Region", "brand_type": "Brand Type",
    "subsidy_plan": "Subsidy Plan",
}


def login():
    r = requests.post(f"{BASE}/session",
                      json={"username": "admin@dmis.local", "password": "Dmis2026!"})
    r.raise_for_status()
    return r.json()["id"]


def build_click_behavior(parameter_mappings: list) -> dict | None:
    """依 dashcard.parameter_mappings 建立 click_behavior parameterMapping。"""
    param_map_out = {}
    for pm in parameter_mappings:
        pid = pm.get("parameter_id")
        target = pm.get("target", [])
        # target = ['dimension', ['field', <field_id>, {...}] , ...]
        if len(target) < 2:
            continue
        field_ref = target[1] if target[0] == "dimension" else None
        if not field_ref or not isinstance(field_ref, list) or field_ref[0] != "field":
            continue
        field_id = field_ref[1]
        col_name = FIELD_MAP.get(field_id)
        if not col_name:
            continue
        disp = DISPLAY_NAMES.get(col_name, col_name.replace("_", " ").title())
        param_map_out[pid] = {
            "id": pid,
            "source": {"id": col_name, "name": disp, "type": "column"},
            "target": {"id": pid, "type": "parameter"},
        }
    if not param_map_out:
        return None
    return {"type": "crossfilter", "parameterMapping": param_map_out}


def main():
    apply_mode = "--apply" in sys.argv
    tok = login()
    h = {"X-Metabase-Session": tok}

    dashboards = requests.get(f"{BASE}/dashboard", headers=h).json()
    total_updated = total_skipped = total_already = 0

    for db_meta in sorted(dashboards, key=lambda x: x["id"]):
        did = db_meta["id"]
        if did in SKIP_DASHBOARD_IDS:
            continue
        db = requests.get(f"{BASE}/dashboard/{did}", headers=h).json()
        dashcards = db.get("dashcards", [])
        if not dashcards:
            continue

        updated_in_db = []
        for dc in dashcards:
            card = dc.get("card")
            if not card:
                continue  # text card
            display = card.get("display", "")
            if display in SKIP_DISPLAY:
                total_skipped += 1
                continue

            param_maps = dc.get("parameter_mappings", [])
            if not param_maps:
                total_skipped += 1
                continue

            new_cb = build_click_behavior(param_maps)
            if not new_cb:
                total_skipped += 1
                continue

            existing_cb = dc.get("visualization_settings", {}).get("click_behavior")
            if existing_cb == new_cb:
                total_already += 1
                continue

            updated_in_db.append((dc, new_cb, card.get("name", "")))

        if not updated_in_db:
            continue

        print(f"\nD#{did} {db_meta['name']}:")
        for dc, cb, cname in updated_in_db:
            print(f"  dashcard#{dc['id']} '{cname}' display={dc.get('card',{}).get('display')}")

        if not apply_mode:
            total_updated += len(updated_in_db)
            continue

        # Build full payload for PUT /dashboard/{id}/cards
        new_cards = []
        cb_map = {dc["id"]: cb for dc, cb, _ in updated_in_db}
        for dc in dashcards:
            dc_copy = copy.deepcopy(dc)
            if dc_copy["id"] in cb_map:
                vs = dc_copy.setdefault("visualization_settings", {})
                vs["click_behavior"] = cb_map[dc_copy["id"]]
            new_cards.append(dc_copy)

        r = requests.put(f"{BASE}/dashboard/{did}/cards",
                         headers=h, json={"cards": new_cards})
        if r.status_code < 300:
            print(f"  [applied] {len(updated_in_db)} cards updated")
            total_updated += len(updated_in_db)
        else:
            print(f"  FAIL: {r.status_code} {r.text[:300]}")

    print(f"\n{'='*60}")
    print(f"{'DRY-RUN ' if not apply_mode else ''}Summary:")
    print(f"  Would update / updated: {total_updated}")
    print(f"  Already OK:            {total_already}")
    print(f"  Skipped (table/no-map):{total_skipped}")
    if not apply_mode:
        print("\n加 --apply 寫入")


if __name__ == "__main__":
    main()
