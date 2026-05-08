#!/usr/bin/env python3
"""更新 P20 通路銷售統計 dashboard 的車行月銷量與累計銷量圖表。"""

from __future__ import annotations

import copy
import json
import sys
import uuid
from datetime import date

import requests

BASE = "http://localhost:3000/api"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"

DASHBOARD_NAME = "P20 通路銷售統計"
MONTHLY_CARD_NAME = "P20-1 車行月銷量（長條圖）"
CUMULATIVE_CARD_NAME = "P20-2 車行累計銷量（折線圖）"
DETAIL_CARD_NAME = "P20-3 車行月銷量明細（表格）"

DB_ID = 2
TABLE_ID = 229

FIELD_STATE = 1627
FIELD_LICENSE_DATE = 1629
FIELD_LICENSE_YM = 1630
FIELD_MODEL = 1632
FIELD_DEALER = 1635
FIELD_ENERGY_TYPE = 1639
FIELD_DEALER_REGION_DISTRICT = 4406
FIELD_SALES_SOURCE = 1647

PID_LICENSE_YM = "ds_license_ym"
PID_SALES_SOURCE = "ds_sales_source"
PID_ENERGY_TYPE = "ds_energy_type"
PID_DEALER_REGION_DISTRICT = "ds_dealer_region_district"
PID_DEALER = "ds_dealer"
DEFAULT_SALES_SOURCE = "車行"
MONTHLY_DASHCARD_HEIGHT = 12
CUMULATIVE_DASHCARD_HEIGHT = 8
DETAIL_DASHCARD_HEIGHT = 16
DETAIL_DASHCARD_COL = 0
DETAIL_DASHCARD_WIDTH = 18
CUMULATIVE_DASHCARD_ROW = MONTHLY_DASHCARD_HEIGHT
DETAIL_DASHCARD_ROW = CUMULATIVE_DASHCARD_ROW + CUMULATIVE_DASHCARD_HEIGHT


def login() -> str:
    response = requests.post(
        f"{BASE}/session",
        json={"username": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["id"]


def api(token: str, method: str, path: str, data=None):
    headers = {"X-Metabase-Session": token, "Content-Type": "application/json"}
    request_fn = getattr(requests, method)
    if data is None:
        response = request_fn(f"{BASE}{path}", headers=headers, timeout=30)
    else:
        response = request_fn(
            f"{BASE}{path}", headers=headers, json=data, timeout=30
        )
    response.raise_for_status()
    return response.json() if response.text else {}


def build_param(
    name: str,
    slug: str,
    param_type: str,
    section: str,
    param_id: str,
    default=None,
):
    param = {
        "id": param_id,
        "slug": slug,
        "name": name,
        "type": param_type,
        "sectionId": section,
    }
    if default is not None:
        param["default"] = default
    return param


def default_license_ym_values(today: date | None = None) -> list[str]:
    current = today or date.today()
    year = current.year
    month = current.month
    values = []
    for offset in range(5, -1, -1):
        calc_month = month - offset
        calc_year = year
        while calc_month <= 0:
            calc_month += 12
            calc_year -= 1
        values.append(f"{calc_year:04d}-{calc_month:02d}")
    return values


def text_field(field_id: int):
    return ["field", field_id, {"base-type": "type/Text"}]


def date_field_month(field_id: int):
    return ["field", field_id, {"temporal-unit": "month", "base-type": "type/Date"}]


def date_field(field_id: int):
    return ["field", field_id, {"base-type": "type/Date"}]


def filter_confirmed():
    return ["=", text_field(FIELD_STATE), "confirmed"]


def filter_not_null(field_id: int):
    return ["not-null", text_field(field_id)]


def filter_not_null_date(field_id: int):
    return ["not-null", date_field(field_id)]


def build_monthly_dataset_query():
    return {
        "type": "query",
        "database": DB_ID,
        "query": {
            "source-table": TABLE_ID,
            "aggregation": [["count"]],
            "breakout": [
                date_field_month(FIELD_LICENSE_DATE),
                text_field(FIELD_DEALER),
            ],
            "filter": [
                "and",
                filter_confirmed(),
                filter_not_null_date(FIELD_LICENSE_DATE),
                filter_not_null(FIELD_MODEL),
                filter_not_null(FIELD_DEALER),
            ],
            "order-by": [["desc", date_field_month(FIELD_LICENSE_DATE)]],
        },
    }


def build_monthly_visualization():
    return {
        "stackable.stack_type": "stacked",
        "graph.show_values": True,
        "graph.label_values_size": 12,
        "graph.max_categories_enabled": False,
        "graph.max_categories": 0,
        "graph.x_axis.title_text": "台數",
        "graph.y_axis.title_text": "領牌月份",
    }


def build_dimension_tag(name: str, display_name: str, field_id: int):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "display-name": display_name,
        "type": "dimension",
        "dimension": ["field", field_id, None],
        "widget-type": "category",
    }


def build_cumulative_dataset_query():
    query = """
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', license_date)::date AS license_month,
        COUNT(*) AS monthly_sales
    FROM ds_sales_report
    WHERE state = 'confirmed'
            AND license_date IS NOT NULL
      AND model IS NOT NULL
      AND dealer IS NOT NULL
      AND dealer <> ''
      [[AND {{license_ym}}]]
            [[AND {{energy_type}}]]
            [[AND {{dealer_region_district}}]]
      [[AND {{dealer}}]]
      [[AND {{sales_source}}]]
    GROUP BY 1
)
SELECT
    license_month AS "領牌月份",
    SUM(monthly_sales) OVER (
        ORDER BY license_month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS "累計銷量"
FROM monthly
ORDER BY license_month ASC
""".strip()
    return {
        "type": "native",
        "database": DB_ID,
        "native": {
            "query": query,
            "template-tags": {
                "license_ym": build_dimension_tag("license_ym", "領牌年月", FIELD_LICENSE_YM),
                "energy_type": build_dimension_tag(
                    "energy_type", "能源類型", FIELD_ENERGY_TYPE
                ),
                "dealer_region_district": build_dimension_tag(
                    "dealer_region_district", "車行區域", FIELD_DEALER_REGION_DISTRICT
                ),
                "dealer": build_dimension_tag("dealer", "車行名稱", FIELD_DEALER),
                "sales_source": build_dimension_tag(
                    "sales_source", "銷售來源", FIELD_SALES_SOURCE
                ),
            },
        },
    }


def build_cumulative_visualization():
    return {
        "graph.dimensions": ["領牌月份"],
        "graph.metrics": ["累計銷量"],
        "graph.show_values": False,
        "graph.x_axis.title_text": "領牌月份",
        "graph.y_axis.title_text": "累計銷量",
    }


def build_detail_dataset_query():
    query = """
WITH monthly AS (
    SELECT
        license_ym,
        DATE_TRUNC('month', license_date)::date AS license_month,
        dealer,
        COUNT(*) AS monthly_sales
    FROM ds_sales_report
    WHERE state = 'confirmed'
      AND license_date IS NOT NULL
      AND model IS NOT NULL
      AND dealer IS NOT NULL
      AND dealer <> ''
      [[AND {{license_ym}}]]
            [[AND {{energy_type}}]]
            [[AND {{dealer_region_district}}]]
      [[AND {{dealer}}]]
      [[AND {{sales_source}}]]
    GROUP BY 1, 2, 3
), ranked AS (
    SELECT
        ROW_NUMBER() OVER (
            PARTITION BY license_month
            ORDER BY monthly_sales DESC, dealer ASC
        ) AS month_seq,
        license_month,
        license_ym,
        CONCAT(license_ym, ' / ', dealer) AS dealer_label,
        monthly_sales
    FROM monthly
), matrix AS (
    SELECT
        license_month,
        license_ym,
        ((month_seq - 1) / 3) + 1 AS matrix_row,
        ((month_seq - 1) % 3) + 1 AS matrix_col,
        dealer_label,
        monthly_sales
    FROM ranked
)
SELECT
    MAX(CASE WHEN matrix_col = 1 THEN dealer_label END) AS "年月 / 車行 A",
    MAX(CASE WHEN matrix_col = 1 THEN monthly_sales END) AS "月銷量 A",
    MAX(CASE WHEN matrix_col = 2 THEN dealer_label END) AS "年月 / 車行 B",
    MAX(CASE WHEN matrix_col = 2 THEN monthly_sales END) AS "月銷量 B",
    MAX(CASE WHEN matrix_col = 3 THEN dealer_label END) AS "年月 / 車行 C",
    MAX(CASE WHEN matrix_col = 3 THEN monthly_sales END) AS "月銷量 C"
FROM matrix
GROUP BY license_month, license_ym, matrix_row
ORDER BY license_month DESC, matrix_row ASC
""".strip()
    return {
        "type": "native",
        "database": DB_ID,
        "native": {
            "query": query,
            "template-tags": {
                "license_ym": build_dimension_tag("license_ym", "領牌年月", FIELD_LICENSE_YM),
                "energy_type": build_dimension_tag(
                    "energy_type", "能源類型", FIELD_ENERGY_TYPE
                ),
                "dealer_region_district": build_dimension_tag(
                    "dealer_region_district", "車行區域", FIELD_DEALER_REGION_DISTRICT
                ),
                "dealer": build_dimension_tag("dealer", "車行名稱", FIELD_DEALER),
                "sales_source": build_dimension_tag(
                    "sales_source", "銷售來源", FIELD_SALES_SOURCE
                ),
            },
        },
    }


def build_detail_visualization():
    return {
        "table.freeze_rows": True,
        "table.freeze_rows_count": 1,
        "table.column_widths": [148, 56, 148, 56, 148, 56],
        "table.columns": [
            {"name": "年月 / 車行 A", "enabled": True},
            {"name": "月銷量 A", "enabled": True},
            {"name": "年月 / 車行 B", "enabled": True},
            {"name": "月銷量 B", "enabled": True},
            {"name": "年月 / 車行 C", "enabled": True},
            {"name": "月銷量 C", "enabled": True},
        ],
        "column_settings": {
            '["name","年月 / 車行 A"]': {"column_title": "年月 / 車行"},
            '["name","月銷量 A"]': {"column_title": "月銷量"},
            '["name","年月 / 車行 B"]': {"column_title": "年月 / 車行"},
            '["name","月銷量 B"]': {"column_title": "月銷量"},
            '["name","年月 / 車行 C"]': {"column_title": "年月 / 車行"},
            '["name","月銷量 C"]': {"column_title": "月銷量"},
        },
        "table.column_formatting": [
            {
                "columns": ["月銷量 A", "月銷量 B", "月銷量 C"],
                "type": "range",
                "colors": ["#FBE6C8", "#F3A65A", "#CC5A16"],
                "min_type": None,
                "max_type": None,
                "min_value": 1,
                "max_value": 5,
            }
        ],
    }


def find_dashboard(token: str):
    dashboards = api(token, "get", "/dashboard")
    for dashboard in dashboards:
        if dashboard.get("name") == DASHBOARD_NAME:
            return api(token, "get", f"/dashboard/{dashboard['id']}")
    raise RuntimeError(f"找不到 dashboard: {DASHBOARD_NAME}")


def upsert_card(token: str, name: str, dataset_query, display: str, visualization_settings, collection_id=None):
    cards = api(token, "get", "/card")
    for card in cards:
        if card.get("name") != name:
            continue
        payload = {
            "name": name,
            "dataset_query": dataset_query,
            "display": display,
            "visualization_settings": visualization_settings,
        }
        if collection_id is not None:
            payload["collection_id"] = collection_id
        api(token, "put", f"/card/{card['id']}", payload)
        return card["id"], False

    payload = {
        "name": name,
        "dataset_query": dataset_query,
        "display": display,
        "visualization_settings": visualization_settings,
    }
    if collection_id is not None:
        payload["collection_id"] = collection_id
    card = api(token, "post", "/card", payload)
    return card["id"], True


def build_dashboard_payload(
    dashboard: dict,
    monthly_card_id: int,
    cumulative_card_id: int,
    detail_card_id: int,
):
    parameters = [
        build_param(
            "領牌年月",
            "license_ym",
            "string/=",
            "string",
            PID_LICENSE_YM,
            default=default_license_ym_values(),
        ),
        build_param(
            "銷售來源",
            "sales_source",
            "string/=",
            "string",
            PID_SALES_SOURCE,
            default=DEFAULT_SALES_SOURCE,
        ),
        build_param("能源類型", "energy_type", "string/=", "string", PID_ENERGY_TYPE),
        build_param(
            "車行區域",
            "dealer_region_district",
            "string/=",
            "string",
            PID_DEALER_REGION_DISTRICT,
        ),
        build_param("車行名稱", "dealer", "string/=", "string", PID_DEALER),
    ]

    dashcards = []
    cumulative_dashcard_present = False
    detail_dashcard_present = False
    existing_dashcards = dashboard.get("dashcards") or []
    for dashcard in existing_dashcards:
        card = dashcard.get("card") or {}
        card_id = dashcard.get("card_id")
        card_name = card.get("name")

        if card_id == monthly_card_id or card_name == MONTHLY_CARD_NAME:
            parameter_mappings = [
                {
                    "parameter_id": PID_LICENSE_YM,
                    "card_id": monthly_card_id,
                    "target": ["dimension", ["field", FIELD_LICENSE_YM, {"base-type": "type/Text"}]],
                },
                {
                    "parameter_id": PID_SALES_SOURCE,
                    "card_id": monthly_card_id,
                    "target": ["dimension", ["field", FIELD_SALES_SOURCE, {"base-type": "type/Text"}]],
                },
                {
                    "parameter_id": PID_ENERGY_TYPE,
                    "card_id": monthly_card_id,
                    "target": ["dimension", ["field", FIELD_ENERGY_TYPE, {"base-type": "type/Text"}]],
                },
                {
                    "parameter_id": PID_DEALER_REGION_DISTRICT,
                    "card_id": monthly_card_id,
                    "target": ["dimension", ["field", FIELD_DEALER_REGION_DISTRICT, {"base-type": "type/Text"}]],
                },
                {
                    "parameter_id": PID_DEALER,
                    "card_id": monthly_card_id,
                    "target": ["dimension", ["field", FIELD_DEALER, {"base-type": "type/Text"}]],
                },
            ]
            new_dashcard = {
                "id": dashcard["id"],
                "card_id": monthly_card_id,
                "row": 0,
                "col": 0,
                "size_x": 18,
                "size_y": MONTHLY_DASHCARD_HEIGHT,
                "parameter_mappings": parameter_mappings,
                "visualization_settings": dashcard.get("visualization_settings") or {},
                "series": dashcard.get("series") or [],
            }
            dashcards.append(new_dashcard)
            continue

        if card_id == cumulative_card_id or card_name == CUMULATIVE_CARD_NAME:
            cumulative_dashcard_present = True
            parameter_mappings = [
                {
                    "parameter_id": PID_LICENSE_YM,
                    "card_id": cumulative_card_id,
                    "target": ["dimension", ["template-tag", "license_ym"]],
                },
                {
                    "parameter_id": PID_SALES_SOURCE,
                    "card_id": cumulative_card_id,
                    "target": ["dimension", ["template-tag", "sales_source"]],
                },
                {
                    "parameter_id": PID_ENERGY_TYPE,
                    "card_id": cumulative_card_id,
                    "target": ["dimension", ["template-tag", "energy_type"]],
                },
                {
                    "parameter_id": PID_DEALER_REGION_DISTRICT,
                    "card_id": cumulative_card_id,
                    "target": ["dimension", ["template-tag", "dealer_region_district"]],
                },
                {
                    "parameter_id": PID_DEALER,
                    "card_id": cumulative_card_id,
                    "target": ["dimension", ["template-tag", "dealer"]],
                },
            ]
            new_dashcard = {
                "id": dashcard["id"],
                "card_id": cumulative_card_id,
                "row": CUMULATIVE_DASHCARD_ROW,
                "col": 0,
                "size_x": 18,
                "size_y": CUMULATIVE_DASHCARD_HEIGHT,
                "parameter_mappings": parameter_mappings,
                "visualization_settings": dashcard.get("visualization_settings") or {},
                "series": dashcard.get("series") or [],
            }
            dashcards.append(new_dashcard)
            continue

        if card_id == detail_card_id or card_name == DETAIL_CARD_NAME:
            detail_dashcard_present = True
            parameter_mappings = [
                {
                    "parameter_id": PID_LICENSE_YM,
                    "card_id": detail_card_id,
                    "target": ["dimension", ["template-tag", "license_ym"]],
                },
                {
                    "parameter_id": PID_SALES_SOURCE,
                    "card_id": detail_card_id,
                    "target": ["dimension", ["template-tag", "sales_source"]],
                },
                {
                    "parameter_id": PID_ENERGY_TYPE,
                    "card_id": detail_card_id,
                    "target": ["dimension", ["template-tag", "energy_type"]],
                },
                {
                    "parameter_id": PID_DEALER_REGION_DISTRICT,
                    "card_id": detail_card_id,
                    "target": ["dimension", ["template-tag", "dealer_region_district"]],
                },
                {
                    "parameter_id": PID_DEALER,
                    "card_id": detail_card_id,
                    "target": ["dimension", ["template-tag", "dealer"]],
                },
            ]
            new_dashcard = {
                "id": dashcard["id"],
                "card_id": detail_card_id,
                "row": DETAIL_DASHCARD_ROW,
                "col": DETAIL_DASHCARD_COL,
                "size_x": DETAIL_DASHCARD_WIDTH,
                "size_y": DETAIL_DASHCARD_HEIGHT,
                "parameter_mappings": parameter_mappings,
                "visualization_settings": dashcard.get("visualization_settings") or {},
                "series": dashcard.get("series") or [],
            }
            dashcards.append(new_dashcard)
            continue

        dashcards.append(
            {
                "id": dashcard["id"],
                "card_id": card_id,
                "row": dashcard.get("row", 0),
                "col": dashcard.get("col", 0),
                "size_x": dashcard.get("size_x", 12),
                "size_y": dashcard.get("size_y", 6),
                "parameter_mappings": dashcard.get("parameter_mappings") or [],
                "visualization_settings": dashcard.get("visualization_settings") or {},
                "series": dashcard.get("series") or [],
            }
        )

    if not cumulative_dashcard_present:
        dashcards.append(
            {
                "id": -1,
                "card_id": cumulative_card_id,
                "row": CUMULATIVE_DASHCARD_ROW,
                "col": 0,
                "size_x": 18,
                "size_y": CUMULATIVE_DASHCARD_HEIGHT,
                "parameter_mappings": [
                    {
                        "parameter_id": PID_LICENSE_YM,
                        "card_id": cumulative_card_id,
                        "target": ["dimension", ["template-tag", "license_ym"]],
                    },
                    {
                        "parameter_id": PID_SALES_SOURCE,
                        "card_id": cumulative_card_id,
                        "target": ["dimension", ["template-tag", "sales_source"]],
                    },
                    {
                        "parameter_id": PID_ENERGY_TYPE,
                        "card_id": cumulative_card_id,
                        "target": ["dimension", ["template-tag", "energy_type"]],
                    },
                    {
                        "parameter_id": PID_DEALER_REGION_DISTRICT,
                        "card_id": cumulative_card_id,
                        "target": ["dimension", ["template-tag", "dealer_region_district"]],
                    },
                    {
                        "parameter_id": PID_DEALER,
                        "card_id": cumulative_card_id,
                        "target": ["dimension", ["template-tag", "dealer"]],
                    },
                ],
                "visualization_settings": {},
                "series": [],
            }
        )

    if not detail_dashcard_present:
        dashcards.append(
            {
                "id": -2,
                "card_id": detail_card_id,
                "row": DETAIL_DASHCARD_ROW,
                "col": DETAIL_DASHCARD_COL,
                "size_x": DETAIL_DASHCARD_WIDTH,
                "size_y": DETAIL_DASHCARD_HEIGHT,
                "parameter_mappings": [
                    {
                        "parameter_id": PID_LICENSE_YM,
                        "card_id": detail_card_id,
                        "target": ["dimension", ["template-tag", "license_ym"]],
                    },
                    {
                        "parameter_id": PID_SALES_SOURCE,
                        "card_id": detail_card_id,
                        "target": ["dimension", ["template-tag", "sales_source"]],
                    },
                    {
                        "parameter_id": PID_ENERGY_TYPE,
                        "card_id": detail_card_id,
                        "target": ["dimension", ["template-tag", "energy_type"]],
                    },
                    {
                        "parameter_id": PID_DEALER_REGION_DISTRICT,
                        "card_id": detail_card_id,
                        "target": ["dimension", ["template-tag", "dealer_region_district"]],
                    },
                    {
                        "parameter_id": PID_DEALER,
                        "card_id": detail_card_id,
                        "target": ["dimension", ["template-tag", "dealer"]],
                    },
                ],
                "visualization_settings": {},
                "series": [],
            }
        )

    return {"parameters": parameters, "dashcards": dashcards}


def main():
    apply_changes = "--apply" in sys.argv
    token = login()
    dashboard = find_dashboard(token)

    collection_id = dashboard.get("collection_id")
    monthly_card_id = None
    for dashcard in dashboard.get("dashcards") or []:
        card = dashcard.get("card") or {}
        if card.get("name") in {MONTHLY_CARD_NAME, "P20 通路×領牌年月（長條圖）"}:
            monthly_card_id = dashcard.get("card_id")
            break
    if monthly_card_id is None:
        raise RuntimeError("找不到 P20 既有月銷量 card")

    actions = [
        f"dashboard #{dashboard['id']} {dashboard['name']}",
        f"update card #{monthly_card_id} -> {MONTHLY_CARD_NAME}",
        f"upsert card -> {CUMULATIVE_CARD_NAME}",
        f"upsert card -> {DETAIL_CARD_NAME}",
        "replace dashboard parameters with 領牌年月 / 銷售來源 / 能源類型 / 車行區域 / 車行名稱",
        f"set default license_ym -> {', '.join(default_license_ym_values())}",
        f"set default sales_source -> {DEFAULT_SALES_SOURCE}",
        "map all cards to dashboard filters",
    ]

    if not apply_changes:
        print("[DRY-RUN]")
        for action in actions:
            print(f" - {action}")
        return

    api(
        token,
        "put",
        f"/card/{monthly_card_id}",
        {
            "name": MONTHLY_CARD_NAME,
            "dataset_query": build_monthly_dataset_query(),
            "display": "row",
            "visualization_settings": build_monthly_visualization(),
        },
    )

    cumulative_card_id, created = upsert_card(
        token,
        CUMULATIVE_CARD_NAME,
        build_cumulative_dataset_query(),
        "line",
        build_cumulative_visualization(),
        collection_id=collection_id,
    )

    detail_card_id, detail_created = upsert_card(
        token,
        DETAIL_CARD_NAME,
        build_detail_dataset_query(),
        "table",
        build_detail_visualization(),
        collection_id=collection_id,
    )

    payload = build_dashboard_payload(
        dashboard,
        monthly_card_id,
        cumulative_card_id,
        detail_card_id,
    )
    api(token, "put", f"/dashboard/{dashboard['id']}", payload)

    updated_dashboard = api(token, "get", f"/dashboard/{dashboard['id']}")
    print("[OK] 已更新 P20 dashboard")
    print(f" - dashboard_id: {updated_dashboard['id']}")
    print(f" - public_uuid: {updated_dashboard.get('public_uuid')}")
    print(f" - monthly_card_id: {monthly_card_id}")
    print(f" - cumulative_card_id: {cumulative_card_id} ({'created' if created else 'updated'})")
    print(f" - detail_card_id: {detail_card_id} ({'created' if detail_created else 'updated'})")
    print(f" - parameter_count: {len(updated_dashboard.get('parameters') or [])}")
    print(f" - dashcard_count: {len(updated_dashboard.get('dashcards') or [])}")


if __name__ == "__main__":
    main()