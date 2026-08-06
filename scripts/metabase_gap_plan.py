#!/usr/bin/env python3
"""Phase 2 落差補齊計畫產生器（dry-run）

基於 `specs/021-datastudio-report/05-gap-analysis.md` §3 落差清單，對 Metabase 所有
Dashboard 逐卡產生「要補哪些 filter」的變更計畫，輸出為 JSON。不直接修改資料，只列出預期動作。

使用方式：
    docker compose exec -T odoo python /mnt/extra-addons/../scripts/metabase_gap_plan.py

或本機直接執行（需能連 Metabase API http://localhost:3000）：
    python scripts/metabase_gap_plan.py > /tmp/metabase_plan.json
"""
from __future__ import annotations
import json
import sys
import requests
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()


# ── 頁別 → 必要 SQL 條件（對應 05-gap-analysis §2）──────────────────
PAGE_RULES: dict[str, dict] = {
    # 電動車系列
    "P3":  {"energy_type": "電車"},
    "P5":  {"energy_type": "電車", "sales_source": "網路平台"},
    "P6":  {"energy_type": "電車", "sales_source": "車行"},
    "P7":  {"energy_type": "電車", "sales_source": "車行"},
    "P8":  {"energy_type": "電車", "sales_source": "車行"},
    # 汽油車系列
    "P9":  {"energy_type": "油車"},
    "P10": {"energy_type": "油車", "sales_source": "網路平台"},
    "P11": {"energy_type": "油車", "sales_source": "車行"},
    "P12": {"energy_type": "油車", "sales_source": "車行"},
    "P13": {"energy_type": "油車", "sales_source": "車行"},
    # 基隆公益青年系列
    "P4":  {"subsidy_plan_like": "%基隆公益%"},
    "P14": {"subsidy_plan_like": "%基隆公益%"},
    "P15": {"subsidy_plan_like": "%基隆公益%", "energy_type": "電車"},
    "P20": {"_suspected_deprecated": True},
    "P21": {"subsidy_plan_like": "%基隆公益%"},
    # 車型/性別/顏色
    "P16": {"_model_by_card": True},   # FUN/RUN/70B/76B 視 card name
    "P17": {"_model_by_card": True},
    "P18": {"_model_by_card": True},
}

# 全站共用：model IS NOT NULL（落差 I）
GLOBAL_RULE_MODEL_NOT_NULL = True


def login() -> str:
    r = requests.post(f"{BASE}/session", json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def api_get(tok: str, path: str):
    return requests.get(f"{BASE}{path}", headers={"X-Metabase-Session": tok}).json()


def card_page(card_name: str) -> str | None:
    """從 card name 開頭（P1-x / P10-y / P21 …）萃取頁別代號。"""
    if not card_name:
        return None
    head = card_name.split()[0]  # e.g. 'P1-1' or 'P21'
    if not head.startswith("P"):
        return None
    num = head[1:].split("-")[0]
    if num.isdigit():
        return f"P{int(num)}"
    return None


def card_model_filter(card_name: str) -> str | None:
    """P16/17/18 的 cards 名稱通常含 FUN/RUN/70B/76B 文字。"""
    name = card_name or ""
    if "FUN" in name:
        return "model LIKE '%EV060L%'"
    if "RUN" in name:
        return "model LIKE 'EV076%' AND model <> 'EV076SZV'"
    if "70B" in name:
        return "model LIKE '%EV070%'"
    if "76B" in name:
        return "model = 'EV076SZV'"
    return None


def plan_card(card: dict) -> list[str]:
    name = card.get("name") or ""
    page = card_page(name)
    rules = PAGE_RULES.get(page or "", {})
    actions: list[str] = []

    if GLOBAL_RULE_MODEL_NOT_NULL:
        actions.append("ADD: model IS NOT NULL （全站，落差 I）")

    if rules.get("_suspected_deprecated"):
        actions.append(f"REVIEW: 疑為廢頁（P20 複本）— 停用或刪除")
        return actions

    if "energy_type" in rules:
        actions.append(f"ADD: energy_type = '{rules['energy_type']}' （落差 F）")
    if "sales_source" in rules:
        actions.append(f"ADD: sales_source = '{rules['sales_source']}' （落差 G）")
    if "subsidy_plan_like" in rules:
        actions.append(f"ADD: subsidy_plan LIKE '{rules['subsidy_plan_like']}' （落差 H）")
    if rules.get("_model_by_card"):
        cond = card_model_filter(name)
        if cond:
            actions.append(f"ADD: {cond} （落差 A/B/C）")
        else:
            actions.append("REVIEW: 無法從 card name 推測 Model 區段（FUN/RUN/70B/76B）")

    # 空 dataset_query 偵測（落差 E）
    return actions


def main():
    tok = login()
    dashes = api_get(tok, "/dashboard")
    plan = []
    for d in dashes:
        if d.get("name") == "E-commerce Insights":
            continue
        det = api_get(tok, f"/dashboard/{d['id']}")
        for dc in det.get("dashcards") or []:
            c = dc.get("card") or {}
            cid = dc.get("card_id")
            name = c.get("name") or "?"
            dq = c.get("dataset_query") or {}
            stages = dq.get("stages") or ([dq.get("query")] if dq.get("query") else [])
            empty_query = not any((s or {}).get("aggregation") or (s or {}).get("breakout") for s in stages)
            actions = plan_card(c)
            if empty_query:
                actions.insert(0, "REVIEW: dataset_query 為空 — 需重建（落差 E）")
            plan.append({
                "dashboard_id": d["id"],
                "dashboard_name": d.get("name"),
                "card_id": cid,
                "card_name": name,
                "display": c.get("display"),
                "actions": actions,
            })
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
