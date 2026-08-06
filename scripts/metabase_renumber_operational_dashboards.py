#!/usr/bin/env python3
"""依目前 Odoo 選單順序，重編 Metabase operational dashboard / card 名稱。"""

from __future__ import annotations

import json
import sys

import requests
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()

# 使用固定 id 與精確舊名 -> 新名映射，避免重跑時再次錯轉。
DASHBOARD_RENAMES = {
    4: ("P3 電動車銷售統計", "P4 電動車銷售統計"),
    9: ("P9 油車銷售統計", "P18 油車銷售統計"),
    10: ("P10 油車-網路平台銷售統計", "P19 油車-網路平台銷售統計"),
    11: ("P11 油車-車行銷售統計", "P20 油車-車行銷售統計"),
    12: ("P12 油車-佣金明細表", "P21 油車-佣金明細表"),
    13: ("P13 油車-台數統計", "P22 油車-台數統計"),
    14: ("P14 地區×銷量（基隆公益）", "P15 地區×銷量（基隆公益）"),
    15: ("P15 區域×車型（基隆公益）", "P16 區域×車型（基隆公益）"),
    16: ("P16 性別×年齡", "P9 性別×年齡"),
    17: ("P20 通路銷售統計", "P3 通路銷售統計"),
    18: ("P4 基隆公益青年", "P13 基隆公益青年"),
    19: ("P17 車型X性別", "P10 車型X性別"),
    20: ("P18 車型X顏色", "P11 車型X顏色"),
    21: ("P19 性別X車型顏色", "P12 性別X車型顏色"),
    22: ("P21 基隆公益青年統計（複本）", "P14 基隆公益青年統計（複本）"),
    23: ("P22 客群×車型分析（基隆公益）", "P17 客群×車型分析（基隆公益）"),
}

CARD_RENAMES = {
    47: ("P3-1 電動車×銷售來源×年月（長條圖）", "P4-1 電動車×銷售來源×年月（長條圖）"),
    48: ("P3-2 電動車×車型×年月（長條圖）", "P4-2 電動車×車型×年月（長條圖）"),
    55: ("P9-1 油車×銷售來源×年月（長條圖）", "P18-1 油車×銷售來源×年月（長條圖）"),
    56: ("P9-2 油車×車型×年月（長條圖）", "P18-2 油車×車型×年月（長條圖）"),
    57: ("P10-1 油車-網路平台×年月（長條圖）", "P19-1 油車-網路平台×年月（長條圖）"),
    58: ("P11-1 油車-車行×年月（長條圖）", "P20-1 油車-車行×年月（長條圖）"),
    59: ("P11-2 油車-車行明細", "P20-2 油車-車行明細"),
    60: ("P12 油車-佣金明細", "P21 油車-佣金明細"),
    61: ("P13 油車-台數統計", "P22 油車-台數統計"),
    62: ("P14 地區×領牌年月（長條圖）", "P15 地區×領牌年月（長條圖）"),
    63: ("P15 區域×車型（長條圖）", "P16 區域×車型（長條圖）"),
    64: ("P16-1 性別（圓餅圖）", "P9-1 性別（圓餅圖）"),
    65: ("P16-2 年齡組×性別（長條圖）", "P9-2 年齡組×性別（長條圖）"),
    66: ("P20-1 車行月銷量（長條圖）", "P3-1 車行月銷量（長條圖）"),
    67: ("P4-1 基隆公益青年×品牌×年月（長條圖）", "P13-1 基隆公益青年×品牌×年月（長條圖）"),
    68: ("P4-2 基隆公益青年明細", "P13-2 基隆公益青年明細"),
    69: ("P17 EV062-性別", "P10 EV062-性別"),
    70: ("P17 EV060L-性別", "P10 EV060L-性別"),
    71: ("P17 EV076-性別", "P10 EV076-性別"),
    72: ("P17 EV070V-性別", "P10 EV070V-性別"),
    73: ("P17 EV076S-性別", "P10 EV076S-性別"),
    74: ("P17 JEGO-性別", "P10 JEGO-性別"),
    75: ("P17 VIVA-性別", "P10 VIVA-性別"),
    76: ("P17 EZ1-性別", "P10 EZ1-性別"),
    77: ("P17 BOBE-性別", "P10 BOBE-性別"),
    78: ("P17 SHINE-性別", "P10 SHINE-性別"),
    79: ("P18 EV062-顏色", "P11 EV062-顏色"),
    80: ("P18 EV060L-顏色", "P11 EV060L-顏色"),
    81: ("P18 EV076-顏色", "P11 EV076-顏色"),
    82: ("P18 EV070V-顏色", "P11 EV070V-顏色"),
    83: ("P18 EV076S-顏色", "P11 EV076S-顏色"),
    84: ("P18 JEGO-顏色", "P11 JEGO-顏色"),
    85: ("P19 EV062-顏色×性別", "P12 EV062-顏色×性別"),
    86: ("P19 EV060L-顏色×性別", "P12 EV060L-顏色×性別"),
    87: ("P19 EV076-顏色×性別", "P12 EV076-顏色×性別"),
    88: ("P19 EV070V-顏色×性別", "P12 EV070V-顏色×性別"),
    89: ("P19 EV076S-顏色×性別", "P12 EV076S-顏色×性別"),
    90: ("P19 JEGO-顏色×性別", "P12 JEGO-顏色×性別"),
    91: ("P21 基隆公益青年統計", "P14 基隆公益青年統計"),
    92: ("P22 20-29歲男性", "P17 20-29歲男性"),
    93: ("P22 30-39歲男性", "P17 30-39歲男性"),
    94: ("P22 40-49歲男性", "P17 40-49歲男性"),
    95: ("P22 20-29歲女性", "P17 20-29歲女性"),
    96: ("P22 30-39歲女性", "P17 30-39歲女性"),
    97: ("P22 40-49歲女性", "P17 40-49歲女性"),
    99: ("P12 油車-佣金匯總", "P21 油車-佣金匯總"),
    100: ("P3-3 電動車明細", "P4-3 電動車明細"),
    101: ("P3-4 電動車車型分布（圓餅圖）", "P4-4 電動車車型分布（圓餅圖）"),
    102: ("P9-3 油車明細", "P18-3 油車明細"),
    103: ("P9-4 油車車型分布（圓餅圖）", "P18-4 油車車型分布（圓餅圖）"),
    104: ("P10-2 油車-網路平台明細", "P19-2 油車-網路平台明細"),
    106: ("P13-1 油車-車行台數匯總", "P22-1 油車-車行台數匯總"),
    107: ("P14-2 基隆公益青年車型明細", "P15-2 基隆公益青年車型明細"),
    108: ("P15-2 區域×車型(色)明細", "P16-2 區域×車型(色)明細"),
    111: ("P20-2 車行累計銷量（折線圖）", "P3-2 車行累計銷量（折線圖）"),
    112: ("P20-3 車行月銷量明細（表格）", "P3-3 車行月銷量明細（表格）"),
    113: ("P20-4 車行區域銷量排行（長條圖）", "P3-4 車行區域銷量排行（長條圖）"),
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


def collect_changes(items: list[dict], rename_map: dict[int, tuple[str, str]]):
    changes = []
    unexpected = []
    for item in items:
        item_id = item.get("id")
        if item_id not in rename_map:
            continue
        old_name, new_name = rename_map[item_id]
        current_name = item.get("name") or ""
        if current_name == old_name:
            changes.append((item_id, current_name, new_name))
            continue
        if current_name != new_name:
            unexpected.append((item_id, current_name, old_name, new_name))
    return changes, unexpected


def main() -> None:
    apply_changes = "--apply" in sys.argv
    token = login()

    dashboards = api(token, "get", "/dashboard")
    cards = api(token, "get", "/card")

    dashboard_changes, dashboard_unexpected = collect_changes(
        dashboards, DASHBOARD_RENAMES
    )
    card_changes, card_unexpected = collect_changes(cards, CARD_RENAMES)

    print(
        json.dumps(
            {
                "dashboard_changes": dashboard_changes,
                "card_changes": card_changes,
                "dashboard_unexpected": dashboard_unexpected,
                "card_unexpected": card_unexpected,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if dashboard_unexpected or card_unexpected:
        raise RuntimeError("發現與預期不符的 live 名稱，請先人工確認後再套用")

    if not apply_changes:
        return

    for dashboard_id, _, new_name in dashboard_changes:
        api(token, "put", f"/dashboard/{dashboard_id}", {"name": new_name})

    for card_id, _, new_name in card_changes:
        api(token, "put", f"/card/{card_id}", {"name": new_name})

    print("[OK] 已完成 operational dashboard / card 名稱重編")


if __name__ == "__main__":
    main()
