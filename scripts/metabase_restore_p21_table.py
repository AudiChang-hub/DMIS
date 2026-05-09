#!/usr/bin/env python3
"""還原 P21 歷史統計表，並改掛正確的 table card。"""

from __future__ import annotations

import json
import requests


BASE = "http://localhost:3000/api"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"

P21_DASHBOARD_ID = 22
P21_DASHCARD_ID = 88
P21_PUBLIC_UUID = "cfade0d2-6dbe-4db8-adb6-1bedc4e36560"
SOURCE_CARD_ID = 68  # P4-2 基隆公益青年明細


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
    dashboard = get(session_id, f"/dashboard/{P21_DASHBOARD_ID}")

    dashcards = dashboard.get("dashcards") or []
    matching_dashcard = next(
        (dashcard for dashcard in dashcards if dashcard.get("id") == P21_DASHCARD_ID),
        None,
    )
    if not matching_dashcard:
        matching_dashcard = next(
            (dashcard for dashcard in dashcards if (dashcard.get("card") or {}).get("id") == SOURCE_CARD_ID),
            None,
        )
    if not matching_dashcard and dashcards:
        matching_dashcard = dashcards[0]

    put(
        session_id,
        f"/dashboard/{dashboard['id']}",
        {
            "archived": False,
            "name": dashboard.get("name") or "P14 基隆公益青年統計（複本）",
        },
    )

    cards_payload = [
        {
            "id": matching_dashcard["id"] if matching_dashcard else -1,
            "card_id": SOURCE_CARD_ID,
            "dashboard_id": dashboard["id"],
            "row": matching_dashcard.get("row", 0) if matching_dashcard else 0,
            "col": matching_dashcard.get("col", 0) if matching_dashcard else 0,
            "size_x": matching_dashcard.get("size_x", 18) if matching_dashcard else 18,
            "size_y": matching_dashcard.get("size_y", 12) if matching_dashcard else 12,
            "parameter_mappings": matching_dashcard.get("parameter_mappings") if matching_dashcard else [],
            "visualization_settings": matching_dashcard.get("visualization_settings") if matching_dashcard else {},
        }
    ]
    put(session_id, f"/dashboard/{dashboard['id']}/cards", {"cards": cards_payload})
    updated_dashboard = get(session_id, f"/dashboard/{dashboard['id']}")
    updated_dashcard = next(
        (
            dashcard
            for dashcard in (updated_dashboard.get("dashcards") or [])
            if (dashcard.get("card") or {}).get("id") == SOURCE_CARD_ID
        ),
        None,
    )

    print(
        json.dumps(
            {
                "dashboard_id": updated_dashboard["id"],
                "dashboard_name": updated_dashboard.get("name"),
                "archived": updated_dashboard.get("archived"),
                "public_uuid": updated_dashboard.get("public_uuid") or P21_PUBLIC_UUID,
                "dashcard_id": updated_dashcard.get("id") if updated_dashcard else None,
                "card_id": SOURCE_CARD_ID,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()