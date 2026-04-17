#!/usr/bin/env python3
"""Phase 2：為 Metabase cards 注入硬編碼篩選器（MBQL v2 格式）。

用法：
    python3 scripts/metabase_apply_filters.py                # dry-run（預設）
    python3 scripts/metabase_apply_filters.py --apply        # 實際寫入

每張 card 的變更：
  1. 讀取 dataset_query.stages[0].filters（MBQL v2）
  2. 若缺少對應硬編碼條件，append 到 filters 列表（AND 語意）
  3. PUT /api/card/:id 寫回

欄位 ID：scripts/metabase_fetch_meta.py（db_id=2, ds_sales_report id=229）
頁別規則：依 Metabase dashboard_id（非 DataStudio 頁號），詳見 05-gap-analysis.md §6
"""
from __future__ import annotations
import copy
import sys
import uuid as _uuid
import requests

BASE = "http://localhost:3000/api"

# ── ds_sales_report 欄位 ID ──────────────────────────
F_MODEL = 1632
F_ENERGY_TYPE = 1639
F_SALES_SOURCE = 1647
F_SUBSIDY_PLAN = 1661


def uu():
    return str(_uuid.uuid4())


def field_ref(fid: int, base_type: str = "type/Text"):
    return ["field", {"lib/uuid": uu(), "base-type": base_type, "effective-type": base_type}, fid]


def eq(fid: int, value: str):
    return ["=", {"lib/uuid": uu()}, field_ref(fid), value]


def not_null(fid: int, base_type: str = "type/Text"):
    return ["not-null", {"lib/uuid": uu()}, field_ref(fid, base_type)]


def contains(fid: int, substring: str):
    return ["contains", {"lib/uuid": uu(), "case-sensitive": False}, field_ref(fid), substring]


def rule_signature(cond) -> str:
    """用於判定重複：op + field_id + value（忽略 uuid）。"""
    if not isinstance(cond, list) or not cond:
        return ""
    op = cond[0]
    field_id = None
    value = None
    for item in cond:
        if isinstance(item, list) and item and item[0] == "field":
            field_id = item[-1]
        elif isinstance(item, (str, int, float, bool)) and item != op:
            value = item
    return f"{op}|{field_id}|{value}"


def filter_signatures(filters_list):
    return {rule_signature(f) for f in (filters_list or []) if isinstance(f, list)}


def rules_for_dashboard(dash_id):
    mapping = {
        2:  lambda: [not_null(F_MODEL)],
        3:  lambda: [not_null(F_MODEL)],
        4:  lambda: [eq(F_ENERGY_TYPE, "電車"), not_null(F_MODEL)],
        18: lambda: [contains(F_SUBSIDY_PLAN, "基隆公益"), not_null(F_MODEL)],
        5:  lambda: [eq(F_ENERGY_TYPE, "電車"), eq(F_SALES_SOURCE, "網路平台"), not_null(F_MODEL)],
        6:  lambda: [eq(F_ENERGY_TYPE, "電車"), eq(F_SALES_SOURCE, "車行"), not_null(F_MODEL)],
        7:  lambda: [eq(F_ENERGY_TYPE, "電車"), eq(F_SALES_SOURCE, "車行"), not_null(F_MODEL)],
        8:  lambda: [eq(F_ENERGY_TYPE, "電車"), eq(F_SALES_SOURCE, "車行"), not_null(F_MODEL)],
        9:  lambda: [eq(F_ENERGY_TYPE, "油車"), not_null(F_MODEL)],
        10: lambda: [eq(F_ENERGY_TYPE, "油車"), eq(F_SALES_SOURCE, "網路平台"), not_null(F_MODEL)],
        11: lambda: [eq(F_ENERGY_TYPE, "油車"), eq(F_SALES_SOURCE, "車行"), not_null(F_MODEL)],
        12: lambda: [eq(F_ENERGY_TYPE, "油車"), eq(F_SALES_SOURCE, "車行"), not_null(F_MODEL)],
        13: lambda: [eq(F_ENERGY_TYPE, "油車"), eq(F_SALES_SOURCE, "車行"), not_null(F_MODEL)],
        14: lambda: [contains(F_SUBSIDY_PLAN, "基隆公益"), not_null(F_MODEL)],
        15: lambda: [contains(F_SUBSIDY_PLAN, "基隆公益"), eq(F_ENERGY_TYPE, "電車"), not_null(F_MODEL)],
        16: lambda: [not_null(F_MODEL)],
        19: lambda: [not_null(F_MODEL)],
        20: lambda: [not_null(F_MODEL)],
        21: lambda: [not_null(F_MODEL)],
        17: lambda: [not_null(F_MODEL)],
        23: lambda: [contains(F_SUBSIDY_PLAN, "基隆公益"), not_null(F_MODEL)],
    }
    return mapping[dash_id]() if dash_id in mapping else []


def login():
    r = requests.post(f"{BASE}/session", json={"username": "admin@dmis.local", "password": "Dmis2026!"})
    r.raise_for_status()
    return r.json()["id"]


def get(tok, path):
    r = requests.get(f"{BASE}{path}", headers={"X-Metabase-Session": tok})
    r.raise_for_status()
    return r.json()


def put(tok, path, body):
    r = requests.put(f"{BASE}{path}", headers={"X-Metabase-Session": tok}, json=body)
    r.raise_for_status()
    return r.json()


def plan_card(card, new_rules):
    notes = []
    dq = card.get("dataset_query") or {}
    if dq.get("lib/type") != "mbql/query":
        notes.append(f"SKIP: 非 MBQL v2 (lib/type={dq.get('lib/type')})")
        return None, notes
    stages = dq.get("stages") or []
    if not stages:
        notes.append("SKIP: 無 stages")
        return None, notes
    stage0 = stages[0]
    if not stage0.get("source-table"):
        notes.append("SKIP: stage[0].source-table 為空（empty query card，需手動重建）")
        return None, notes

    existing = stage0.get("filters") or []
    exist_sigs = filter_signatures(existing)
    missing = [r for r in new_rules if rule_signature(r) not in exist_sigs]
    if not missing:
        notes.append("OK: 所有條件皆已存在")
        return None, notes

    new_dq = copy.deepcopy(dq)
    new_dq["stages"][0]["filters"] = list(existing) + missing
    notes.append(f"UPDATE: 注入 {len(missing)} 個新條件")
    for m in missing:
        notes.append(f"  + {rule_signature(m)}")
    return new_dq, notes


def main():
    apply_mode = "--apply" in sys.argv
    tok = login()

    summary = {"total": 0, "updated": 0, "ok": 0, "skipped": 0}
    log = []
    processed_cards = set()

    dashes = get(tok, "/dashboard")
    for d in dashes:
        dash_id = d["id"]
        if d.get("archived"):
            continue
        rules = rules_for_dashboard(dash_id)
        if not rules:
            continue
        det = get(tok, f"/dashboard/{dash_id}")
        log.append(f"\n## Dashboard #{dash_id}: {det.get('name')}")
        for dc in det.get("dashcards") or []:
            cid = dc.get("card_id")
            if not cid or cid in processed_cards:
                continue
            processed_cards.add(cid)
            summary["total"] += 1
            card = get(tok, f"/card/{cid}")
            name = card.get("name")
            new_dq, notes = plan_card(card, rules)
            log.append(f"  card#{cid} {name}")
            for n in notes:
                log.append(f"    {n}")
            if new_dq is None:
                if any(n.startswith("OK") for n in notes):
                    summary["ok"] += 1
                else:
                    summary["skipped"] += 1
                continue
            if apply_mode:
                put(tok, f"/card/{cid}", {"dataset_query": new_dq})
                log.append("    [applied]")
            summary["updated"] += 1

    print("\n".join(log))
    print("\n=== Summary ===")
    print(f"Total cards processed: {summary['total']}")
    print(f"Would update / updated: {summary['updated']}")
    print(f"Already OK (no change): {summary['ok']}")
    print(f"Skipped (empty/unsupported): {summary['skipped']}")
    if not apply_mode:
        print("\n[dry-run] 未實際寫入。確認計畫後加 --apply 執行。")


if __name__ == "__main__":
    main()
