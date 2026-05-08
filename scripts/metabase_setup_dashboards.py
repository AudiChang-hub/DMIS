#!/usr/bin/env python3
"""
Metabase Dashboard 自動建立腳本 — 復刻 DataStudio SUZUKI銷售統計 22 頁
使用 Metabase REST API 建立 Questions + Dashboards
"""
import json
import requests
import sys
import time

BASE = "http://localhost:3000/api"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"
DB_ID = 2
TABLE_ID = 229  # ds_sales_report

# Field IDs mapping
F = {
    "id": 1625, "order_name": 1626, "state": 1627, "order_date": 1628,
    "license_date": 1629, "license_ym": 1630, "sort_license_date": 1631,
    "model": 1632, "car_color": 1633, "model_color": 1634, "dealer": 1635,
    "dealer_not_null": 1636, "vin_or_en": 1637, "license_plate": 1638,
    "energy_type": 1639, "motor_type": 1640, "owner_name": 1641,
    "sex": 1642, "age": 1643, "age_group": 1644, "region": 1645,
    "region_district": 1646, "sales_source": 1647, "sales_type": 1648,
    "brand_type": 1649, "receipt_price": 1650, "cost": 1651,
    "net_profit": 1652, "dealer_comm_out": 1653, "friendly_bonus_out": 1654,
    "first_sale_bonus": 1655, "basic_bonus": 1656, "dealer_receipt": 1657,
    "company_gift": 1658, "platform_gift": 1659, "gift_card": 1660,
    "subsidy_plan": 1661, "settle_date": 1662, "apply_date": 1663,
    "volume_bonus": 1664, "total_commission": 1665,
}

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

def field_ref(name):
    return ["field", F[name], {"base-type": "type/Text" if name not in ("id","age","receipt_price","cost","net_profit","dealer_comm_out","friendly_bonus_out","first_sale_bonus","basic_bonus","dealer_receipt","gift_card","volume_bonus","total_commission","license_date","order_date","sort_license_date","settle_date","apply_date") else ("type/Integer" if name in ("id","age") else ("type/Date" if name in ("license_date","order_date","sort_license_date","settle_date","apply_date") else "type/Decimal"))}]

def count_agg():
    return ["count"]

def sum_agg(name):
    return ["sum", field_ref(name)]

def filter_eq(name, value):
    return ["=", field_ref(name), value]

def filter_confirmed():
    return filter_eq("state", "confirmed")

def filter_electric():
    return filter_eq("energy_type", "電車")

def filter_oil():
    return filter_eq("energy_type", "油車")

def filter_platform():
    return filter_eq("sales_source", "網路平台")

def filter_dealer_source():
    return filter_eq("sales_source", "車行")

def combined_filter(*filters):
    if len(filters) == 1:
        return filters[0]
    return ["and"] + list(filters)


def create_native_question(token, name, sql, display="bar", collection_id=None):
    """建立 Native SQL question"""
    payload = {
        "name": name,
        "dataset_query": {
            "type": "native",
            "native": {"query": sql},
            "database": DB_ID,
        },
        "display": display,
        "visualization_settings": {
            "graph.show_values": True,
            "graph.label_values_size": 12,
        },
    }
    if collection_id:
        payload["collection_id"] = collection_id
    return api(token, "post", "/card", payload)


def create_question(token, name, breakouts, aggregations, filters=None, display="bar",
                    order_by=None, collection_id=None, viz_settings=None):
    """建立 MBQL question"""
    query = {
        "source-table": TABLE_ID,
        "aggregation": aggregations,
        "breakout": breakouts,
    }
    if filters:
        query["filter"] = filters
    if order_by:
        query["order-by"] = order_by

    default_viz = {
        "graph.show_values": True,
        "graph.label_values_size": 12,
    }
    if display == "pie":
        default_viz = {
            "pie.show_legend": True,
            "pie.show_data_labels": True,
            "pie.percent_visibility": "inside",
        }
    elif display == "table":
        default_viz = {}

    if viz_settings:
        default_viz.update(viz_settings)

    payload = {
        "name": name,
        "dataset_query": {
            "type": "query",
            "query": query,
            "database": DB_ID,
        },
        "display": display,
        "visualization_settings": default_viz,
    }
    if collection_id:
        payload["collection_id"] = collection_id
    return api(token, "post", "/card", payload)


def create_dashboard(token, name, collection_id=None):
    payload = {"name": name}
    if collection_id:
        payload["collection_id"] = collection_id
    return api(token, "post", "/dashboard", payload)


def add_card_to_dashboard(token, dash_id, card_id, row, col, size_x, size_y):
    payload = {
        "dashcards": [{
            "id": -1,
            "card_id": card_id,
            "row": row,
            "col": col,
            "size_x": size_x,
            "size_y": size_y,
        }]
    }
    return api(token, "put", f"/dashboard/{dash_id}", payload)


def main():
    token = login()
    print(f"[OK] 登入成功")

    # 建立 Collection
    coll = api(token, "post", "/collection", {"name": "SUZUKI銷售統計", "color": "#509EE3"})
    coll_id = coll["id"]
    print(f"[OK] Collection id={coll_id}")

    questions = {}  # name -> card_id
    dashboards = {}  # name -> dash_id

    # ──────────────────────────────────────────────
    # P1 — 總車輛銷售
    # ──────────────────────────────────────────────
    print("\n=== P1: 總車輛銷售 ===")

    # P1-1: 堆疊長條圖 — 領牌年月 × 銷售來源 × 台數
    q = create_question(token, "P1-1 銷售來源×領牌年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("sales_source"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p1_bar_source"] = q["id"]
    print(f"  [OK] P1-1 bar id={q['id']}")

    # P1-2: 圓餅圖 — 銷售來源
    q = create_question(token, "P1-2 銷售來源（圓餅圖）",
        breakouts=[field_ref("sales_source")],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="pie",
        collection_id=coll_id)
    questions["p1_pie_source"] = q["id"]
    print(f"  [OK] P1-2 pie id={q['id']}")

    # P1-3: 堆疊長條圖 — 領牌年月 × 車種類型
    q = create_question(token, "P1-3 車種類型×領牌年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("motor_type"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p1_bar_motor"] = q["id"]
    print(f"  [OK] P1-3 bar id={q['id']}")

    # P1-4: 圓餅圖 — 車種類型
    q = create_question(token, "P1-4 車種類型（圓餅圖）",
        breakouts=[field_ref("motor_type")],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="pie",
        collection_id=coll_id)
    questions["p1_pie_motor"] = q["id"]
    print(f"  [OK] P1-4 pie id={q['id']}")

    # P1-5: 表格 — 明細
    q = create_native_question(token, "P1-5 總車輛銷售明細",
        f"""SELECT license_date AS "領牌日期", license_ym AS "領牌年月",
               dealer AS "車行", model AS "車型", vin_or_en AS "引擎號碼",
               energy_type AS "能源", car_color AS "車色", owner_name AS "車主",
               subsidy_plan AS "補助方案", receipt_price AS "收款價"
        FROM ds_sales_report WHERE state='confirmed'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p1_table"] = q["id"]
    print(f"  [OK] P1-5 table id={q['id']}")

    # Create P1 Dashboard
    dash = create_dashboard(token, "P1 總車輛銷售", coll_id)
    dashboards["p1"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P2 — 銷售機種統計
    # ──────────────────────────────────────────────
    print("\n=== P2: 銷售機種統計 ===")

    q = create_question(token, "P2-1 銷售機種×領牌年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("motor_type"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p2_bar"] = q["id"]
    print(f"  [OK] P2-1 bar id={q['id']}")

    q = create_native_question(token, "P2-2 銷售機種明細",
        f"""SELECT license_ym AS "領牌年月", model AS "車種型號",
               motor_type AS "車種類型", count(*) AS "總台數"
        FROM ds_sales_report WHERE state='confirmed'
        GROUP BY license_ym, model, motor_type
        ORDER BY license_ym DESC, motor_type, model""",
        display="table", collection_id=coll_id)
    questions["p2_table"] = q["id"]
    print(f"  [OK] P2-2 table id={q['id']}")

    q = create_question(token, "P2-3 銷售車型×領牌年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("model"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p2_bar_model"] = q["id"]
    print(f"  [OK] P2-3 bar id={q['id']}")

    dash = create_dashboard(token, "P2 銷售機種統計", coll_id)
    dashboards["p2"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P3 — 電動車銷售統計
    # ──────────────────────────────────────────────
    print("\n=== P3: 電動車銷售統計 ===")

    q = create_question(token, "P3-1 電動車×銷售來源×年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("sales_source"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_electric()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p3_bar_source"] = q["id"]
    print(f"  [OK] P3-1 bar id={q['id']}")

    q = create_question(token, "P3-2 電動車×車型×年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("model"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_electric()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p3_bar_model"] = q["id"]
    print(f"  [OK] P3-2 bar id={q['id']}")

    dash = create_dashboard(token, "P3 電動車銷售統計", coll_id)
    dashboards["p3"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P5 — 電動車 - 網路平台銷售統計
    # ──────────────────────────────────────────────
    print("\n=== P5: 電動車 - 網路平台 ===")

    q = create_question(token, "P5-1 電動車-網路平台×年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("dealer"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_electric(), filter_platform()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p5_bar"] = q["id"]
    print(f"  [OK] P5-1 bar id={q['id']}")

    q = create_native_question(token, "P5-2 電動車-網路平台明細",
        """SELECT license_date AS "領牌日期", dealer AS "車行", model AS "車型",
               vin_or_en AS "引擎號碼", car_color AS "車色", owner_name AS "車主",
               company_gift AS "公司禮券", platform_gift AS "平台贈品",
               settle_date AS "訖", receipt_price AS "收款價"
        FROM ds_sales_report
        WHERE state='confirmed' AND energy_type='電車' AND sales_source='網路平台'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p5_table"] = q["id"]
    print(f"  [OK] P5-2 table id={q['id']}")

    dash = create_dashboard(token, "P5 電動車-網路平台銷售統計", coll_id)
    dashboards["p5"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P6 — 電動車 - 車行銷售統計
    # ──────────────────────────────────────────────
    print("\n=== P6: 電動車 - 車行 ===")

    q = create_question(token, "P6-1 電動車-車行×年月（長條圖）",
        breakouts=[
            field_ref("dealer"),
            ["field", F["license_date"], {"temporal-unit": "month"}],
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_electric(), filter_dealer_source()),
        display="bar",
        order_by=[["desc", ["aggregation", 0]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p6_bar"] = q["id"]
    print(f"  [OK] P6-1 bar id={q['id']}")

    q = create_native_question(token, "P6-2 電動車-車行明細",
        """SELECT license_date AS "領牌日期", dealer AS "車行", model AS "車型",
               vin_or_en AS "引擎號碼", car_color AS "車色", owner_name AS "車主",
               company_gift AS "公司禮券", settle_date AS "訖", receipt_price AS "收款價"
        FROM ds_sales_report
        WHERE state='confirmed' AND energy_type='電車' AND sales_source='車行'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p6_table"] = q["id"]
    print(f"  [OK] P6-2 table id={q['id']}")

    dash = create_dashboard(token, "P6 電動車-車行銷售統計", coll_id)
    dashboards["p6"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P7 — 電動車 - 佣金明細表
    # ──────────────────────────────────────────────
    print("\n=== P7: 電動車 - 佣金明細 ===")

    q = create_native_question(token, "P7 電動車-佣金明細",
        """SELECT license_date AS "領牌日期", dealer AS "車行", model AS "車型",
               car_color AS "車色", owner_name AS "車主", license_plate AS "車牌",
               settle_date AS "訖", receipt_price AS "收款價"
        FROM ds_sales_report
        WHERE state='confirmed' AND energy_type='電車' AND sales_source='車行'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p7_table"] = q["id"]
    print(f"  [OK] P7 table id={q['id']}")

    dash = create_dashboard(token, "P7 電動車-佣金明細表", coll_id)
    dashboards["p7"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P8 — 電動車 - 台數統計
    # ──────────────────────────────────────────────
    print("\n=== P8: 電動車 - 台數統計 ===")

    q = create_native_question(token, "P8 電動車-台數統計",
        """SELECT license_date AS "領牌日期", dealer AS "車行", owner_name AS "車主",
               model AS "車型", car_color AS "顏色", license_plate AS "車牌",
               basic_bonus AS "獎勵金"
        FROM ds_sales_report
        WHERE state='confirmed' AND energy_type='電車' AND sales_source='車行'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p8_table"] = q["id"]
    print(f"  [OK] P8 table id={q['id']}")

    dash = create_dashboard(token, "P8 電動車-台數統計", coll_id)
    dashboards["p8"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P9 — 油車銷售統計 (對稱 P3)
    # ──────────────────────────────────────────────
    print("\n=== P9: 油車銷售統計 ===")

    q = create_question(token, "P9-1 油車×銷售來源×年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("sales_source"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_oil()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p9_bar_source"] = q["id"]
    print(f"  [OK] P9-1 bar id={q['id']}")

    q = create_question(token, "P9-2 油車×車型×年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("model"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_oil()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p9_bar_model"] = q["id"]
    print(f"  [OK] P9-2 bar id={q['id']}")

    dash = create_dashboard(token, "P9 油車銷售統計", coll_id)
    dashboards["p9"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P10 — 油車 - 網路平台 (對稱 P5)
    # ──────────────────────────────────────────────
    print("\n=== P10: 油車 - 網路平台 ===")

    q = create_question(token, "P10-1 油車-網路平台×年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("dealer"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_oil(), filter_platform()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p10_bar"] = q["id"]
    print(f"  [OK] P10-1 bar id={q['id']}")

    dash = create_dashboard(token, "P10 油車-網路平台銷售統計", coll_id)
    dashboards["p10"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P11 — 油車 - 車行 (對稱 P6)
    # ──────────────────────────────────────────────
    print("\n=== P11: 油車 - 車行 ===")

    q = create_question(token, "P11-1 油車-車行×年月（長條圖）",
        breakouts=[
            field_ref("dealer"),
            ["field", F["license_date"], {"temporal-unit": "month"}],
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_oil(), filter_dealer_source()),
        display="bar",
        order_by=[["desc", ["aggregation", 0]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p11_bar"] = q["id"]
    print(f"  [OK] P11-1 bar id={q['id']}")

    q = create_native_question(token, "P11-2 油車-車行明細",
        """SELECT license_date AS "領牌日期", dealer AS "車行", model AS "車型",
               vin_or_en AS "引擎號碼", car_color AS "車色", owner_name AS "車主",
               company_gift AS "公司禮券", settle_date AS "訖", receipt_price AS "收款價"
        FROM ds_sales_report
        WHERE state='confirmed' AND energy_type='油車' AND sales_source='車行'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p11_table"] = q["id"]
    print(f"  [OK] P11-2 table id={q['id']}")

    dash = create_dashboard(token, "P11 油車-車行銷售統計", coll_id)
    dashboards["p11"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P12 — 油車 - 佣金明細 (對稱 P7)
    # ──────────────────────────────────────────────
    print("\n=== P12: 油車 - 佣金明細 ===")

    q = create_native_question(token, "P12 油車-佣金明細",
        """SELECT license_date AS "領牌日期", dealer AS "車行", model AS "車型",
               car_color AS "車色", owner_name AS "車主", license_plate AS "車牌",
               settle_date AS "訖", receipt_price AS "收款價"
        FROM ds_sales_report
        WHERE state='confirmed' AND energy_type='油車' AND sales_source='車行'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p12_table"] = q["id"]
    print(f"  [OK] P12 table id={q['id']}")

    dash = create_dashboard(token, "P12 油車-佣金明細表", coll_id)
    dashboards["p12"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P13 — 油車 - 台數統計 (對稱 P8)
    # ──────────────────────────────────────────────
    print("\n=== P13: 油車 - 台數統計 ===")

    q = create_native_question(token, "P13 油車-台數統計",
        """SELECT license_date AS "領牌日期", dealer AS "車行", owner_name AS "車主",
               model AS "車型", car_color AS "顏色", license_plate AS "車牌",
               basic_bonus AS "獎勵金"
        FROM ds_sales_report
        WHERE state='confirmed' AND energy_type='油車' AND sales_source='車行'
        ORDER BY COALESCE(license_date, '9999-12-31') DESC""",
        display="table", collection_id=coll_id)
    questions["p13_table"] = q["id"]
    print(f"  [OK] P13 table id={q['id']}")

    dash = create_dashboard(token, "P13 油車-台數統計", coll_id)
    dashboards["p13"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P14 — 地區×銷量（基隆公益）
    # ──────────────────────────────────────────────
    print("\n=== P14: 地區×銷量（基隆公益） ===")

    q = create_question(token, "P14 地區×領牌年月（長條圖）",
        breakouts=[
            field_ref("region"),
            ["field", F["license_date"], {"temporal-unit": "month"}],
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="bar",
        order_by=[["desc", ["aggregation", 0]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p14_bar"] = q["id"]
    print(f"  [OK] P14 bar id={q['id']}")

    dash = create_dashboard(token, "P14 地區×銷量（基隆公益）", coll_id)
    dashboards["p14"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P15 — 區域×車型（基隆公益）
    # ──────────────────────────────────────────────
    print("\n=== P15: 區域×車型（基隆公益） ===")

    q = create_question(token, "P15 區域×車型（長條圖）",
        breakouts=[
            field_ref("region"),
            field_ref("model"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_electric()),
        display="bar",
        order_by=[["desc", ["aggregation", 0]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p15_bar"] = q["id"]
    print(f"  [OK] P15 bar id={q['id']}")

    dash = create_dashboard(token, "P15 區域×車型（基隆公益）", coll_id)
    dashboards["p15"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P16 — 性別×年齡
    # ──────────────────────────────────────────────
    print("\n=== P16: 性別×年齡 ===")

    q = create_question(token, "P16-1 性別（圓餅圖）",
        breakouts=[field_ref("sex")],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="pie",
        collection_id=coll_id)
    questions["p16_pie_sex"] = q["id"]
    print(f"  [OK] P16-1 pie id={q['id']}")

    q = create_question(token, "P16-2 年齡組×性別（長條圖）",
        breakouts=[field_ref("age_group"), field_ref("sex")],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed(), filter_electric()),
        display="bar",
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p16_bar_age"] = q["id"]
    print(f"  [OK] P16-2 bar id={q['id']}")

    dash = create_dashboard(token, "P16 性別×年齡", coll_id)
    dashboards["p16"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # P20 — 通路銷售統計
    # ──────────────────────────────────────────────
    print("\n=== P20: 通路銷售統計 ===")

    q = create_question(token, "P20 通路×領牌年月（長條圖）",
        breakouts=[
            ["field", F["license_date"], {"temporal-unit": "month"}],
            field_ref("dealer_not_null"),
        ],
        aggregations=[count_agg()],
        filters=combined_filter(filter_confirmed()),
        display="bar",
        order_by=[["asc", ["field", F["license_date"], {"temporal-unit": "month"}]]],
        collection_id=coll_id,
        viz_settings={"stackable.stack_type": "stacked", "graph.show_values": True})
    questions["p20_bar"] = q["id"]
    print(f"  [OK] P20 bar id={q['id']}")

    dash = create_dashboard(token, "P20 通路銷售統計", coll_id)
    dashboards["p20"] = dash["id"]
    print(f"  [OK] Dashboard id={dash['id']}")

    # ──────────────────────────────────────────────
    # 把所有 questions 放入各自的 Dashboard
    # ──────────────────────────────────────────────
    print("\n=== 排列 Dashboard Cards ===")

    dash_layout = {
        "p1": [("p1_bar_source", 0, 0, 12, 6), ("p1_pie_source", 12, 0, 6, 6),
               ("p1_bar_motor", 0, 6, 12, 6), ("p1_pie_motor", 12, 6, 6, 6),
               ("p1_table", 0, 12, 18, 8)],
         "p2": [("p2_bar", 0, 0, 18, 8), ("p2_table", 0, 8, 18, 8),
             ("p2_bar_model", 0, 16, 18, 8)],
        "p3": [("p3_bar_source", 0, 0, 18, 8), ("p3_bar_model", 0, 8, 18, 8)],
        "p5": [("p5_bar", 0, 0, 18, 8), ("p5_table", 0, 8, 18, 8)],
        "p6": [("p6_bar", 0, 0, 18, 8), ("p6_table", 0, 8, 18, 8)],
        "p7": [("p7_table", 0, 0, 18, 12)],
        "p8": [("p8_table", 0, 0, 18, 12)],
        "p9": [("p9_bar_source", 0, 0, 18, 8), ("p9_bar_model", 0, 8, 18, 8)],
        "p10": [("p10_bar", 0, 0, 18, 8)],
        "p11": [("p11_bar", 0, 0, 18, 8), ("p11_table", 0, 8, 18, 8)],
        "p12": [("p12_table", 0, 0, 18, 12)],
        "p13": [("p13_table", 0, 0, 18, 12)],
        "p14": [("p14_bar", 0, 0, 18, 8)],
        "p15": [("p15_bar", 0, 0, 18, 8)],
        "p16": [("p16_pie_sex", 0, 0, 8, 6), ("p16_bar_age", 8, 0, 10, 6)],
        "p20": [("p20_bar", 0, 0, 18, 8)],
    }

    for dash_key, cards in dash_layout.items():
        dash_id = dashboards[dash_key]
        dashcards = []
        for i, (q_key, col, row, sx, sy) in enumerate(cards):
            dashcards.append({
                "id": -(i + 1),
                "card_id": questions[q_key],
                "row": row,
                "col": col,
                "size_x": sx,
                "size_y": sy,
            })
        api(token, "put", f"/dashboard/{dash_id}", {"dashcards": dashcards})
        print(f"  [OK] {dash_key}: {len(cards)} cards placed")

    # ──────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"完成！共建立：")
    print(f"  - {len(questions)} 個 Questions")
    print(f"  - {len(dashboards)} 個 Dashboards")
    print(f"  - 所有圖表已啟用「顯示數值」(show_values)")
    print(f"\nMetabase URL: http://localhost:3000")
    print(f"Collection: SUZUKI銷售統計")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
