#!/usr/bin/env python3
"""一次處理兩件事：

1. 將 ds_sales_report 表中欄位 display_name 由「經銷商」改為「車行」，
   並把每張 P 系列 card 的 visualization_settings column_title / 軸標籤同步更新。
2. 對於以「領牌年月（月份）」為類別軸的水平長條圖（row chart）：
   - 將查詢 order-by 由 asc 改為 desc，讓最新的月份排在最上面。
   - 設定 graph.max_categories = 12 + show_other_category，
     讓最多顯示 12 個月份 + 「其他」共 13 條資料；被合併進「其他」的會是最舊的月份。
   - 將儀表板上對應 dashcard 的 size_y 拉高到 13，避免被壓縮。
"""
import argparse
import json

import requests

BASE = "http://localhost:3000/api"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"

# 需要從「經銷商」改為「車行」的欄位顯示名稱
FIELD_RENAME = {
    "dealer":          "車行",
    "dealer_not_null": "車行(含馭盛)",
    "dealer_receipt":  "車行收款",
}

# 軸/欄位標籤替換（card 層級 visualization_settings）
LABEL_RENAME = {
    "經銷商":         "車行",
    "經銷商(含馭盛)": "車行(含馭盛)",
    "經銷商收款":     "車行收款",
    "Dealer":         "車行",
    "Dealer Not Null":"車行(含馭盛)",
    "Dealer Receipt": "車行收款",
}

# 卡片名稱中含有「經銷」也一併改為「車行」
CARD_NAME_RENAME = {
    "經銷商": "車行",
    "經銷":   "車行",
}

# 需要套用「最新顯示+其他壓縮最舊」的 row chart card name 前綴。
# 同時接受舊編號與 2026-05-09 起的新 operational 編號，避免重編前後腳本失效。
DATE_ROW_PREFIXES = (
    "P1-1 ", "P1-3 ", "P2-1 ",
    "P3 ", "P3-1 ", "P3-2 ",
    "P4-1 ", "P4-2 ", "P5-1 ", "P6-1 ",
    "P9-1 ", "P9-2 ", "P10-1 ", "P11-1 ",
    "P13 ", "P14 ", "P15 ", "P16-2 ",
    "P18-1 ", "P18-2 ", "P19-1 ", "P20-1 ",
    "P20 ",
)
# license_date 欄位 id（ds_sales_report.license_date）
LICENSE_DATE_FIELD_ID = 1629
MAX_CATEGORIES = 13  # 與 past12months~ (13 個月) 對齊，全部顯示
TARGET_SIZE_Y = 13   # dashcard 高度


def login():
    r = requests.post(f"{BASE}/session",
                      json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return {"X-Metabase-Session": r.json()["id"]}


def rename_fields(headers, apply):
    tables = requests.get(f"{BASE}/table", headers=headers).json()
    tbl = next((t for t in tables if t.get("name") == "ds_sales_report"), None)
    if not tbl:
        print("[WARN] ds_sales_report table not found"); return
    fields = requests.get(f"{BASE}/table/{tbl['id']}/query_metadata",
                          headers=headers).json().get("fields", [])
    for f in fields:
        new = FIELD_RENAME.get(f.get("name"))
        if new and f.get("display_name") != new:
            print(f"  field#{f['id']} {f['name']}: '{f.get('display_name')}' -> '{new}'")
            if apply:
                requests.put(f"{BASE}/field/{f['id']}", headers=headers,
                             json={"display_name": new}).raise_for_status()


def rename_card_labels(headers, apply):
    cards = requests.get(f"{BASE}/card/", headers=headers).json()
    for c in cards:
        cid = c["id"]; name = c.get("name") or ""
        if not name.startswith("P"):
            continue
        new_name = name
        for k, v in CARD_NAME_RENAME.items():
            new_name = new_name.replace(k, v)
        vs = dict(c.get("visualization_settings") or {})
        changed = (new_name != name)

        col_settings = vs.get("column_settings") or {}
        for key, val in col_settings.items():
            t = val.get("column_title")
            if t in LABEL_RENAME:
                val["column_title"] = LABEL_RENAME[t]
                changed = True
        for axis_key in ("graph.x_axis.title_text", "graph.y_axis.title_text"):
            v = vs.get(axis_key)
            if v in LABEL_RENAME:
                vs[axis_key] = LABEL_RENAME[v]; changed = True
        ss = vs.get("series_settings") or {}
        for skey, sval in ss.items():
            t = sval.get("title")
            if t in LABEL_RENAME:
                sval["title"] = LABEL_RENAME[t]; changed = True

        if changed:
            print(f"  card#{cid} {name} -> name='{new_name}', viz updated")
            if apply:
                payload = {"visualization_settings": vs}
                if new_name != name:
                    payload["name"] = new_name
                requests.put(f"{BASE}/card/{cid}", headers=headers,
                             json=payload).raise_for_status()


def fix_date_row_charts(headers, apply):
    cards = requests.get(f"{BASE}/card/", headers=headers).json()
    target_ids = []
    for c in cards:
        name = c.get("name") or ""
        if not any(name.startswith(p) for p in DATE_ROW_PREFIXES):
            continue
        if c.get("display") not in ("row", "bar"):
            continue
        target_ids.append(c["id"])

        dq = json.loads(json.dumps(c.get("dataset_query") or {}))
        stages = dq.get("stages") or []
        if not stages:
            print(f"  [SKIP] card#{c['id']} {name}: 無 mbql stage"); continue
        st = stages[0]

        # 找出 license_date breakout，準備換成 order-by desc
        ob_changed = False
        new_order = []
        has_date_order = False
        for ob in st.get("order-by", []) or []:
            direction, _meta, field_ref = ob
            if (isinstance(field_ref, list) and len(field_ref) >= 3
                    and field_ref[2] == LICENSE_DATE_FIELD_ID):
                has_date_order = True
                if direction != "desc":
                    ob[0] = "desc"; ob_changed = True
            new_order.append(ob)
        if not has_date_order:
            new_order.insert(0, [
                "desc",
                {"lib/uuid": f"auto-desc-{c['id']}"},
                ["field",
                 {"base-type": "type/Date", "temporal-unit": "month",
                  "effective-type": "type/Date",
                  "lib/uuid": f"auto-field-{c['id']}"},
                 LICENSE_DATE_FIELD_ID],
            ])
            ob_changed = True
        st["order-by"] = new_order

        vs = dict(c.get("visualization_settings") or {})
        viz_changed = False
        if vs.get("graph.max_categories") != MAX_CATEGORIES:
            vs["graph.max_categories"] = MAX_CATEGORIES; viz_changed = True
        if vs.get("graph.show_other_category") is not True:
            vs["graph.show_other_category"] = True; viz_changed = True
        if vs.get("graph.other_category_aggregation_fn") != "sum":
            vs["graph.other_category_aggregation_fn"] = "sum"; viz_changed = True

        if not (ob_changed or viz_changed):
            print(f"  [SKIP] card#{c['id']} {name}: 已是預期設定"); continue

        print(f"  card#{c['id']} {name}: order_by_desc={ob_changed}, viz={viz_changed}")
        if apply:
            requests.put(f"{BASE}/card/{c['id']}", headers=headers,
                         json={
                             "dataset_query": dq,
                             "visualization_settings": vs,
                         }).raise_for_status()
    return set(target_ids)


def expand_dashcards(headers, target_card_ids, apply):
    if not target_card_ids:
        return
    for d in requests.get(f"{BASE}/dashboard", headers=headers).json():
        dd = requests.get(f"{BASE}/dashboard/{d['id']}", headers=headers).json()
        dashcards = dd.get("dashcards") or []
        changed = False
        for dc in dashcards:
            if (dc.get("card") or {}).get("id") in target_card_ids:
                if (dc.get("size_y") or 0) < TARGET_SIZE_Y:
                    print(f"  dashboard#{d['id']} {d['name']} dashcard#{dc['id']}"
                          f" size_y {dc.get('size_y')} -> {TARGET_SIZE_Y}")
                    dc["size_y"] = TARGET_SIZE_Y; changed = True
        if changed and apply:
            payload = []
            for dc in dashcards:
                payload.append({
                    "id": dc["id"],
                    "card_id": (dc.get("card") or {}).get("id"),
                    "row": dc.get("row"),
                    "col": dc.get("col"),
                    "size_x": dc.get("size_x"),
                    "size_y": dc.get("size_y"),
                    "series": [s.get("id") for s in (dc.get("series") or [])],
                    "parameter_mappings": dc.get("parameter_mappings") or [],
                    "visualization_settings": dc.get("visualization_settings") or {},
                })
            requests.put(f"{BASE}/dashboard/{d['id']}/cards",
                         headers=headers,
                         json={"cards": payload}).raise_for_status()


def patch_native_sql(headers, apply):
    """把 native query 中的 `AS "經銷商"` 改成 `AS "車行"`，
    以及 result_metadata 內的舊顯示名稱。"""
    cards = requests.get(f"{BASE}/card/", headers=headers).json()
    for c in cards:
        dq = c.get("dataset_query") or {}
        stages = dq.get("stages") or []
        if not stages:
            continue
        st = stages[0]
        if st.get("lib/type") != "mbql.stage/native":
            continue
        sql = st.get("native") or ""
        new_sql = sql
        for k, v in LABEL_RENAME.items():
            new_sql = new_sql.replace(f'AS "{k}"', f'AS "{v}"')
        if new_sql == sql:
            continue
        new_dq = json.loads(json.dumps(dq))
        new_dq["stages"][0]["native"] = new_sql
        # 同步更新 result_metadata 中對應的 name/display_name
        new_rmd = json.loads(json.dumps(c.get("result_metadata") or []))
        for m in new_rmd:
            for k, v in LABEL_RENAME.items():
                if m.get("name") == k:
                    m["name"] = v
                if m.get("display_name") == k:
                    m["display_name"] = v
        print(f"  card#{c['id']} {c.get('name')}: native SQL updated")
        if apply:
            requests.put(f"{BASE}/card/{c['id']}", headers=headers,
                         json={"dataset_query": new_dq,
                               "result_metadata": new_rmd}).raise_for_status()


def refresh_card_metadata(headers, apply):
    """重新跑一次 query，讓帶有 dealer 欄位的 card 重新計算 result_metadata，
    使快取在 result_metadata.display_name 中的『經銷商』字串改寫成『車行』。"""
    cards = requests.get(f"{BASE}/card/", headers=headers).json()
    for c in cards:
        rmd = c.get("result_metadata") or []
        has_dealer = any((m.get("name") in FIELD_RENAME) for m in rmd)
        if not has_dealer:
            continue
        print(f"  refresh card#{c['id']} {c.get('name')}")
        if apply:
            try:
                requests.post(f"{BASE}/card/{c['id']}/query",
                              headers=headers, json={"ignore_cache": True}, timeout=60)
            except Exception as e:
                print(f"    [warn] refresh failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="實際寫入 Metabase（缺省為 dry run）")
    args = ap.parse_args()
    h = login()

    print("=== 1. 欄位 display_name：經銷商 → 車行 ===")
    rename_fields(h, args.apply)

    print("\n=== 2. Card 標籤/名稱：經銷商 → 車行 ===")
    rename_card_labels(h, args.apply)

    print("\n=== 3. 日期長條圖：最新在上、其他壓縮最舊 ===")
    target_ids = fix_date_row_charts(h, args.apply)

    print("\n=== 4. 對應 dashcard 拉高至 size_y >= 13 ===")
    expand_dashcards(h, target_ids, args.apply)

    print("\n=== 5. 重新跑帶 dealer 欄位的 card 以刷新 result_metadata ===")
    refresh_card_metadata(h, args.apply)

    print("\n=== 6. 修補 native SQL 別名：經銷商 → 車行 ===")
    patch_native_sql(h, args.apply)

    print("\n[DONE] " + ("APPLIED" if args.apply else "DRY RUN"))


if __name__ == "__main__":
    main()
