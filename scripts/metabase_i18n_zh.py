#!/usr/bin/env python3
"""
批量將 Metabase 上 ds_sales_report 各欄位的 display_name 改為繁體中文。
同時更新每張 card 的 visualization_settings 中的 column 中文名稱，以及
Y 軸 / X 軸標籤。
"""
import argparse, requests, json, sys

BASE = "http://localhost:3000/api"

# ── 欄位名稱 → 中文 display_name ──────────────────────────
FIELD_DISPLAY_NAME = {
    "license_date":       "領牌日期",
    "license_ym":         "領牌年月",
    "sort_license_date":  "排序用領牌日期",
    "model":              "車型",
    "car_color":          "車色",
    "model_color":        "車型_車色",
    "dealer":             "經銷商",
    "dealer_not_null":    "經銷商(含馭盛)",
    "vin_or_en":          "引擎號碼",
    "license_plate":      "車牌號碼",
    "energy_type":        "能源型式",
    "motor_type":         "車種類型",
    "owner_name":         "車主姓名",
    "sex":                "性別",
    "age":                "年齡",
    "age_group":          "年齡組",
    "region":             "地區",
    "region_district":    "縣市區域",
    "sales_source":       "銷售來源",
    "sales_type":         "銷售類型",
    "brand_type":         "品牌分類",
    "receipt_price":      "收款金額",
    "cost":               "成本",
    "net_profit":         "淨利",
    "dealer_comm_out":    "業務佣金",
    "friendly_bonus_out": "友好獎金",
    "first_sale_bonus":   "首賣獎金",
    "basic_bonus":        "基本獎金",
    "dealer_receipt":     "經銷商收款",
    "company_gift":       "公司贈品",
    "platform_gift":      "平台贈品",
    "gift_card":          "禮券",
    "subsidy_plan":       "補助方案",
    "settle_date":        "結算日期",
    "apply_date":         "申請日期",
    "volume_bonus":       "量獎",
    "total_commission":   "總佣金",
    "remark":             "備註",
    "order_name":         "訂單編號",
    "state":              "狀態",
    "order_date":         "訂單日期",
    "id":                 "編號",
    "count":              "計數",
}

# ── 軸標籤翻譯 ──────────────────────────
AXIS_LABELS = {
    "License Date": "領牌日期",
    "License Date: Month": "領牌日期：月份",
    "License Date: 月份": "領牌日期：月份",
    "License Ym": "領牌年月",
    "Sales Source": "銷售來源",
    "Motor Type": "車種類型",
    "Dealer": "經銷商",
    "Dealer Not Null": "經銷商(含馭盛)",
    "Model": "車型",
    "Region": "地區",
    "Sex": "性別",
    "Age Group": "年齡組",
    "Brand Type": "品牌分類",
    "Car Color": "車色",
    "Model Color": "車型_車色",
    "Energy Type": "能源型式",
    "Count": "計數",
    "count": "計數",
}


def get_session():
    r = requests.post(f"{BASE}/session",
                      json={"username": "admin@dmis.local", "password": "Dmis2026!"})
    r.raise_for_status()
    return {"X-Metabase-Session": r.json()["id"]}


def update_field_display_names(headers, apply=False):
    """更新 ds_sales_report 表的 field display_name"""
    # Find table id for ds_sales_report
    resp = requests.get(f"{BASE}/table", headers=headers)
    tables = resp.json()
    tbl = None
    for t in tables:
        if t.get("name") == "ds_sales_report":
            tbl = t
            break
    if not tbl:
        print("  WARN: ds_sales_report table not found in Metabase metadata")
        return

    tid = tbl["id"]
    resp = requests.get(f"{BASE}/table/{tid}/fields", headers=headers)
    # resp might be table metadata with fields
    resp2 = requests.get(f"{BASE}/table/{tid}/query_metadata", headers=headers)
    fields = resp2.json().get("fields", [])

    changed = 0
    for f in fields:
        fname = f.get("name", "")
        cur_display = f.get("display_name", "")
        new_display = FIELD_DISPLAY_NAME.get(fname)
        if new_display and cur_display != new_display:
            print(f"  field#{f['id']} {fname}: '{cur_display}' → '{new_display}'")
            if apply:
                requests.put(f"{BASE}/field/{f['id']}",
                             headers=headers,
                             json={"display_name": new_display})
            changed += 1
    print(f"  Fields: {changed} {'updated' if apply else 'to update'}")


def update_card_viz_labels(headers, apply=False):
    """更新每張 DMIS card 的 visualization_settings 中的欄位中文標籤"""
    resp = requests.get(f"{BASE}/card/", headers=headers)
    cards = resp.json()

    updated = 0
    for c in cards:
        name = c.get("name", "")
        if not name.startswith("P"):
            continue

        cid = c["id"]
        vs = c.get("visualization_settings", {})
        changed = False

        # column_settings: {"[\"ref\",[\"field\",1647,null]]": {"column_title": "xxx"}}
        col_settings = vs.get("column_settings", {})
        for key, val in col_settings.items():
            ct = val.get("column_title", "")
            if ct in AXIS_LABELS:
                val["column_title"] = AXIS_LABELS[ct]
                changed = True

        # graph.x_axis.title_text / graph.y_axis.title_text
        for axis_key in ["graph.x_axis.title_text", "graph.y_axis.title_text"]:
            v = vs.get(axis_key, "")
            if v in AXIS_LABELS:
                vs[axis_key] = AXIS_LABELS[v]
                changed = True

        # series_settings labels
        ss = vs.get("series_settings", {})
        for skey, sval in ss.items():
            t = sval.get("title", "")
            if t in AXIS_LABELS:
                sval["title"] = AXIS_LABELS[t]
                changed = True

        if changed:
            print(f"  card#{cid} {name}: viz_settings updated")
            if apply:
                requests.put(f"{BASE}/card/{cid}",
                             headers=headers,
                             json={"visualization_settings": vs})
            updated += 1

    print(f"  Cards viz: {updated} {'updated' if apply else 'to update'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    headers = get_session()

    print("=== 1. Field display_name 中文化 ===")
    update_field_display_names(headers, args.apply)

    print("\n=== 2. Card visualization_settings 中文化 ===")
    update_card_viz_labels(headers, args.apply)


if __name__ == "__main__":
    main()
