#!/usr/bin/env python3
"""修復 P7 / P12 佣金頁的 dashboard 篩選器設定。"""

from __future__ import annotations

import json

import requests
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()

PID_DEALER = "ds_dealer"
PID_LICENSE_YM = "ds_license_ym"

DASHBOARD_CONFIG = {
    7: {"card_ids": {53, 98}},
    12: {"card_ids": {60, 99}},
}


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


def build_mappings(card_id: int):
    return [
        {
            "parameter_id": PID_DEALER,
            "card_id": card_id,
            "target": ["variable", ["template-tag", "dealer_filter"]],
        },
        {
            "parameter_id": PID_LICENSE_YM,
            "card_id": card_id,
            "target": ["variable", ["template-tag", "ym_filter"]],
        },
    ]


def main() -> None:
    token = login()
    for dashboard_id, config in DASHBOARD_CONFIG.items():
        dashboard = api(token, "get", f"/dashboard/{dashboard_id}")
        dashcards_payload = []
        for dashcard in dashboard.get("dashcards") or []:
            card_id = dashcard.get("card_id")
            parameter_mappings = dashcard.get("parameter_mappings") or []
            if card_id in config["card_ids"]:
                parameter_mappings = build_mappings(card_id)
            dashcards_payload.append({
                "id": dashcard["id"],
                "card_id": card_id,
                "row": dashcard.get("row", 0),
                "col": dashcard.get("col", 0),
                "size_x": dashcard.get("size_x", 12),
                "size_y": dashcard.get("size_y", 6),
                "parameter_mappings": parameter_mappings,
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
        updated_dashboard = api(token, "put", f"/dashboard/{dashboard_id}", payload)
        print(
            json.dumps(
                {
                    "dashboard_id": updated_dashboard["id"],
                    "dashboard_name": updated_dashboard.get("name"),
                    "parameters": [
                        param.get("id")
                        for param in (updated_dashboard.get("parameters") or [])
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
