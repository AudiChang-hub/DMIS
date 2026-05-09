#!/usr/bin/env python3
"""修復 P13 油車-台數統計的領牌年月篩選器。"""

from __future__ import annotations

import copy
import json
import uuid

import requests


BASE = "http://localhost:3000/api"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"

P13_DASHBOARD_ID = 13
P13_DETAIL_CARD_ID = 61
P13_SUMMARY_CARD_ID = 106

PID_DEALER = "ds_dealer"
PID_LICENSE_YM = "ds_license_ym"

FIELD_LICENSE_YM = 1630


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


def build_param(name: str, slug: str, param_type: str, section: str, param_id: str):
    return {
        "id": param_id,
        "slug": slug,
        "name": name,
        "type": param_type,
        "sectionId": section,
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


def ensure_sql_has_license_ym(native_sql: str) -> str:
    if "{{license_ym}}" in native_sql:
        return native_sql
    marker = "  [[AND dealer = {{dealer_filter}}]]"
    if marker in native_sql:
        return native_sql.replace(marker, "  [[AND {{license_ym}}]]\n" + marker)
    order_marker = "\nORDER BY"
    if order_marker in native_sql:
        return native_sql.replace(order_marker, "\n  [[AND {{license_ym}}]]" + order_marker)
    return native_sql + "\n  [[AND {{license_ym}}]]"


def patch_card(card: dict) -> dict:
    new_card = copy.deepcopy(card)
    stages = (new_card.get("dataset_query") or {}).get("stages") or []
    if not stages:
        raise RuntimeError(f"card {card.get('id')} missing stages")
    stage = stages[0]
    if stage.get("lib/type") != "mbql.stage/native":
        raise RuntimeError(f"card {card.get('id')} is not native")

    template_tags = copy.deepcopy(stage.get("template-tags") or {})
    if "license_ym" not in template_tags:
        template_tags["license_ym"] = build_dimension_tag("license_ym", "領牌年月", FIELD_LICENSE_YM)
    stage["template-tags"] = template_tags
    stage["native"] = ensure_sql_has_license_ym(stage.get("native") or "")
    return new_card


def main() -> None:
    token = login()
    api(token, "get", f"/dashboard/{P13_DASHBOARD_ID}")

    card_ids = {P13_DETAIL_CARD_ID, P13_SUMMARY_CARD_ID}
    for card_id in card_ids:
        card = api(token, "get", f"/card/{card_id}")
        patched_card = patch_card(card)
        api(token, "put", f"/card/{card_id}", {"dataset_query": patched_card["dataset_query"]})

    refreshed_dashboard = api(token, "get", f"/dashboard/{P13_DASHBOARD_ID}")
    dashcards_payload = []
    for dashcard in refreshed_dashboard.get("dashcards") or []:
        card_id = dashcard.get("card_id")
        mappings = []
        if card_id in card_ids:
            mappings.append({
                "parameter_id": PID_DEALER,
                "card_id": card_id,
                "target": ["dimension", ["template-tag", "dealer_filter"]],
            })
            mappings.append({
                "parameter_id": PID_LICENSE_YM,
                "card_id": card_id,
                "target": ["dimension", ["template-tag", "license_ym"]],
            })
        dashcards_payload.append({
            "id": dashcard["id"],
            "card_id": card_id,
            "row": dashcard.get("row", 0),
            "col": dashcard.get("col", 0),
            "size_x": dashcard.get("size_x", 12),
            "size_y": dashcard.get("size_y", 6),
            "parameter_mappings": mappings,
            "visualization_settings": dashcard.get("visualization_settings") or {},
            "series": dashcard.get("series") or [],
        })

    payload = {
        "parameters": [
            build_param("車行名稱", "dealer", "string/=", "string", PID_DEALER),
            build_param("領牌年月", "license_ym", "string/=", "string", PID_LICENSE_YM),
        ],
        "dashcards": dashcards_payload,
    }
    updated_dashboard = api(token, "put", f"/dashboard/{P13_DASHBOARD_ID}", payload)

    print(
        json.dumps(
            {
                "dashboard_id": updated_dashboard["id"],
                "dashboard_name": updated_dashboard.get("name"),
                "parameters": [
                    param.get("id") for param in (updated_dashboard.get("parameters") or [])
                ],
                "card_ids": sorted(card_ids),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()