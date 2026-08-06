#!/usr/bin/env python3
"""為 P2 銷售機種及車型統計補上一張依車型分類的月趨勢圖。"""

from __future__ import annotations

import copy
import json
import requests
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()

P2_DASHBOARD_NAME = "P2 銷售機種及車型統計"
SOURCE_CARD_NAME = "P2-1 銷售機種×領牌年月（長條圖）"
NEW_CARD_NAME = "P2-3 銷售車型×領牌年月（長條圖）"
MODEL_FIELD_ID = 1632


def clone_parameter_mappings(mappings: list[dict], new_card_id: int) -> list[dict]:
    cloned = copy.deepcopy(mappings or [])
    for mapping in cloned:
        mapping["card_id"] = new_card_id
    return cloned


def login() -> str:
    response = requests.post(
        f"{BASE}/session",
        json={"username": EMAIL, "password": PASSWORD},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["id"]


def get(session_id: str, path: str):
    response = requests.get(
        f"{BASE}{path}",
        headers={"X-Metabase-Session": session_id},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def post(session_id: str, path: str, payload: dict):
    response = requests.post(
        f"{BASE}{path}",
        headers={"X-Metabase-Session": session_id},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def put(session_id: str, path: str, payload: dict):
    response = requests.put(
        f"{BASE}{path}",
        headers={"X-Metabase-Session": session_id},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    session_id = login()
    dashboards = get(session_id, "/dashboard")
    dashboard = next(
        (item for item in dashboards if item.get("name") == P2_DASHBOARD_NAME),
        None,
    )
    if not dashboard:
        raise SystemExit(f"找不到 dashboard: {P2_DASHBOARD_NAME}")

    detail = get(session_id, f"/dashboard/{dashboard['id']}")
    dashcards = detail.get("dashcards") or []

    existing_new = next(
        (
            dashcard
            for dashcard in dashcards
            if (dashcard.get("card") or {}).get("name") == NEW_CARD_NAME
        ),
        None,
    )

    source_dashcard = next(
        (dashcard for dashcard in dashcards if (dashcard.get("card") or {}).get("name") == SOURCE_CARD_NAME),
        None,
    )
    if not source_dashcard:
        raise SystemExit(f"找不到來源卡片: {SOURCE_CARD_NAME}")

    source_card = get(session_id, f"/card/{source_dashcard['card_id']}")
    dataset_query = copy.deepcopy(source_card["dataset_query"])
    dataset_query["stages"][0]["breakout"][1][2] = MODEL_FIELD_ID

    if existing_new:
        new_card = get(session_id, f"/card/{existing_new['card_id']}")
    else:
        new_card = post(
            session_id,
            "/card",
            {
                "name": NEW_CARD_NAME,
                "dataset_query": dataset_query,
                "display": source_card.get("display") or "bar",
                "visualization_settings": source_card.get("visualization_settings") or {},
                "collection_id": source_card.get("collection_id"),
            },
        )

    new_parameter_mappings = clone_parameter_mappings(
        source_dashcard.get("parameter_mappings") or [],
        new_card["id"],
    )

    cards_payload = []
    for dashcard in dashcards:
        if existing_new and dashcard["id"] == existing_new["id"]:
            cards_payload.append(
                {
                    "id": dashcard["id"],
                    "card_id": new_card["id"],
                    "dashboard_id": dashcard.get("dashboard_id"),
                    "row": 16,
                    "col": 0,
                    "size_x": dashcard.get("size_x", source_dashcard.get("size_x", 24)),
                    "size_y": dashcard.get("size_y", 10),
                    "parameter_mappings": new_parameter_mappings,
                    "visualization_settings": dashcard.get("visualization_settings") or {},
                }
            )
            continue

        cards_payload.append(
            {
                "id": dashcard["id"],
                "card_id": dashcard.get("card_id"),
                "dashboard_id": dashcard.get("dashboard_id"),
                "row": dashcard.get("row", 0),
                "col": dashcard.get("col", 0),
                "size_x": dashcard.get("size_x", 24),
                "size_y": dashcard.get("size_y", 8),
                "parameter_mappings": dashcard.get("parameter_mappings") or [],
                "visualization_settings": dashcard.get("visualization_settings") or {},
            }
        )

    if not existing_new:
        cards_payload.append(
            {
                "id": -1,
                "card_id": new_card["id"],
                "dashboard_id": dashboard["id"],
                "row": 16,
                "col": 0,
                "size_x": source_dashcard.get("size_x", 24),
                "size_y": 10,
                "parameter_mappings": new_parameter_mappings,
                "visualization_settings": {},
            }
        )

    put(session_id, f"/dashboard/{dashboard['id']}/cards", {"cards": cards_payload})

    print(
        json.dumps(
            {
                "dashboard_id": dashboard["id"],
                "new_card_id": new_card["id"],
                "new_card_name": NEW_CARD_NAME,
                "updated_parameter_mappings": len(new_parameter_mappings),
                "dashcard_count": len(cards_payload),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
