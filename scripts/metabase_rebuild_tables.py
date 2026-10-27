#!/usr/bin/env python3
"""Phase 2c：重建 10 張 empty-query 明細表卡片。

依 `specs/021-datastudio-report/04-chart-details.md` 對應頁面表格欄位，
建立 source-table=229 + fields list + 合併 dashboard 硬編碼篩選。

用法：
    python3 scripts/metabase_rebuild_tables.py             # dry-run
    python3 scripts/metabase_rebuild_tables.py --apply     # 寫入
"""
from __future__ import annotations
import copy
import sys
import uuid as _uuid
import requests

BASE = "http://localhost:3000/api"
DB_ID = 2
TABLE_ID = 229

# ── 欄位 ID（dms_report_ds.ds_sales_report）─────────
F = {
    "id": 1625,
    "order_name": 1626,
    "state": 1627,
    "order_date": 1628,
    "license_date": 1629,
    "license_ym": 1630,
    "sort_license_date": 1631,
    "model": 1632,
    "car_color": 1633,
    "model_color": 1634,
    "dealer": 1635,
    "dealer_not_null": 1636,
    "vin_or_en": 1637,
    "license_plate": 1638,
    "energy_type": 1639,
    "motor_type": 1640,
    "owner_name": 1641,
    "sex": 1642,
    "age": 1643,
    "age_group": 1644,
    "region": 1645,
    "region_district": 1646,
    "sales_source": 1647,
    "sales_type": 1648,
    "brand_type": 1649,
    "receipt_price": 1650,
    "cost": 1651,
    "net_profit": 1652,
    "dealer_comm_out": 1653,
    "friendly_bonus_out": 1654,
    "first_sale_bonus": 1655,
    "basic_bonus": 1656,
    "dealer_receipt": 1657,
    "company_gift": 1658,
    "platform_gift": 1659,
    "gift_card": 1660,
    "subsidy_plan": 1661,
    "settle_date": 1662,
    "apply_date": 1663,
    "volume_bonus": 1664,
    "total_commission": 1665,
    "remark": None,  # 尚未在 Metabase sync 到，先 None 略過
}

BT_TEXT = "type/Text"
BT_DATE = "type/Date"
BT_DEC = "type/Decimal"
BT_INT = "type/Integer"

BASE_TYPES = {
    "license_date": BT_DATE, "order_date": BT_DATE, "settle_date": BT_DATE,
    "apply_date": BT_DATE, "sort_license_date": BT_DATE,
    "receipt_price": BT_DEC, "cost": BT_DEC, "net_profit": BT_DEC,
    "dealer_comm_out": BT_DEC, "friendly_bonus_out": BT_DEC,
    "first_sale_bonus": BT_DEC, "basic_bonus": BT_DEC,
    "dealer_receipt": BT_DEC, "gift_card": BT_DEC,
    "volume_bonus": BT_DEC, "total_commission": BT_DEC,
    "age": BT_INT, "id": BT_INT,
}


def uu():
    return str(_uuid.uuid4())


def fref(name: str):
    fid = F[name]
    if fid is None:
        return None
    bt = BASE_TYPES.get(name, BT_TEXT)
    return ["field", {"lib/uuid": uu(), "base-type": bt, "effective-type": bt}, fid]


def eq(fname, val):
    return ["=", {"lib/uuid": uu()}, fref(fname), val]


def starts_with(fname, val):
    return ["starts-with", {"lib/uuid": uu(), "case-sensitive": False}, fref(fname), val]


def not_null(fname):
    return ["not-null", {"lib/uuid": uu()}, fref(fname)]


def contains(fname, val):
    return ["contains", {"lib/uuid": uu(), "case-sensitive": False}, fref(fname), val]


# ── 每張 card 的重建規格 ──────────────────────────────
# fields: ds_sales_report 欄位名（依 04-chart-details.md 表格順序）
# filters: 硬編碼條件
# order: [(field_name, 'asc'|'desc')]
REBUILD: dict[int, dict] = {
    # card#44 P1-5 總車輛銷售明細
    44: {
        "fields": ["license_ym", "dealer", "model", "vin_or_en", "energy_type",
                   "car_color", "owner_name", "subsidy_plan", "receipt_price"],
        "filters": [not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#46 P2-2 銷售機種明細（彙總：license_ym × model × motor_type count）
    46: {
        "fields": ["license_ym", "model", "motor_type"],
        "aggregation": "count",
        "filters": [not_null("model")],
        "order": [("license_ym", "desc")],
    },
    # card#68 P4-2 基隆公益青年明細
    68: {
        "fields": ["license_date", "brand_type", "dealer", "model", "vin_or_en",
                   "owner_name", "subsidy_plan", "apply_date", "settle_date", "basic_bonus"],
        "filters": [contains("subsidy_plan", "基隆公益"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#50 P5-2 電動車-網路平台明細
    50: {
        "fields": ["license_date", "dealer", "model", "vin_or_en", "car_color",
                   "owner_name", "gift_card", "platform_gift", "company_gift",
                   "settle_date", "receipt_price"],
        "filters": [eq("energy_type", "電車"), eq("sales_source", "網路平台"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#52 P6-2 電動車-車行明細
    52: {
        "fields": ["license_date", "dealer", "model", "vin_or_en", "car_color",
                   "owner_name", "gift_card", "company_gift", "settle_date", "receipt_price"],
        "filters": [eq("energy_type", "電車"), eq("sales_source", "車行"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#53 P7 電動車-佣金明細（明細表，非彙總）
    53: {
        "fields": ["license_date", "dealer", "model", "car_color", "owner_name",
                   "license_plate", "settle_date", "receipt_price"],
        "filters": [eq("energy_type", "電車"), eq("sales_source", "車行"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#54 P8 電動車-台數統計（明細表）
    54: {
        "fields": ["license_date", "dealer", "owner_name", "model", "car_color",
                   "license_plate", "basic_bonus"],
        "filters": [eq("energy_type", "電車"), eq("sales_source", "車行"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#59 P11-2 油車-車行明細
    59: {
        "fields": ["license_date", "dealer", "model", "vin_or_en", "car_color",
                   "owner_name", "gift_card", "company_gift", "settle_date", "receipt_price"],
        "filters": [eq("energy_type", "油車"), eq("sales_source", "車行"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#60 P12 油車-佣金明細
    60: {
        "fields": ["license_date", "dealer", "model", "car_color", "owner_name",
                   "license_plate", "settle_date", "receipt_price"],
        "filters": [eq("energy_type", "油車"), eq("sales_source", "車行"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
    # card#61 P13 油車-台數統計（明細）
    61: {
        "fields": ["license_date", "dealer", "owner_name", "model", "car_color",
                   "license_plate", "basic_bonus"],
        "filters": [eq("energy_type", "油車"), eq("sales_source", "車行"), not_null("model")],
        "order": [("sort_license_date", "desc")],
    },
}


def build_dataset_query(spec: dict) -> dict:
    """產生一份 MBQL v2 dataset_query。有 aggregation 時轉為群組查詢，否則為原始列出。"""
    stage = {
        "lib/type": "mbql.stage/mbql",
        "source-table": TABLE_ID,
        "filters": spec["filters"],
    }

    if spec.get("aggregation") == "count":
        stage["breakout"] = [fref(fn) for fn in spec["fields"] if fref(fn)]
        stage["aggregation"] = [["count", {"lib/uuid": uu()}]]
    else:
        stage["fields"] = [fref(fn) for fn in spec["fields"] if fref(fn)]

    if spec.get("order"):
        stage["order-by"] = [
            [direction, {"lib/uuid": uu()}, fref(fn)]
            for fn, direction in spec["order"] if fref(fn)
        ]

    return {
        "lib/type": "mbql/query",
        "database": DB_ID,
        "stages": [stage],
    }


def login():
    r = requests.post(f"{BASE}/session", json={"username": "admin@dmis.local", "password": "Dmis2026!"})
    r.raise_for_status()
    return r.json()["id"]


def main():
    apply_mode = "--apply" in sys.argv
    tok = login()
    h = {"X-Metabase-Session": tok}

    for cid, spec in REBUILD.items():
        card = requests.get(f"{BASE}/card/{cid}", headers=h).json()
        name = card.get("name")
        print(f"\n== card#{cid} {name} ==")
        print(f"   fields: {spec['fields']}")
        if spec.get("aggregation"):
            print(f"   aggregation: {spec['aggregation']}")
        new_dq = build_dataset_query(spec)

        if not apply_mode:
            continue

        r = requests.put(f"{BASE}/card/{cid}", headers=h, json={"dataset_query": new_dq})
        if r.status_code >= 300:
            print(f"   FAIL: {r.status_code} {r.text[:300]}")
        else:
            print(f"   [applied]")
            # test query
            q = requests.post(f"{BASE}/card/{cid}/query", headers=h)
            if q.status_code < 300:
                data = (q.json() or {}).get("data") or {}
                rows = data.get("rows") or []
                print(f"   query OK: {len(rows)} rows")
            else:
                print(f"   query FAIL: {q.status_code} {q.text[:300]}")

    if not apply_mode:
        print("\n[dry-run] 加 --apply 寫入")


if __name__ == "__main__":
    main()
