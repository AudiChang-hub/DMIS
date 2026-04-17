#!/usr/bin/env python3
"""Phase 2 準備：查詢 Metabase 中 ds_sales_report 所有欄位的 field_id 與 dashboard 清單。"""
import json
import requests

BASE = "http://localhost:3000/api"


def login():
    r = requests.post(f"{BASE}/session", json={"username": "admin@dmis.local", "password": "Dmis2026!"})
    r.raise_for_status()
    return r.json()["id"]


def get(tok, path):
    return requests.get(f"{BASE}{path}", headers={"X-Metabase-Session": tok}).json()


def main():
    tok = login()
    # 列出所有 databases，找到 DMIS/PostgreSQL
    dbs = get(tok, "/database")
    db_list = dbs.get("data", dbs) if isinstance(dbs, dict) else dbs
    print("Databases:")
    for db in db_list:
        print(f"  id={db['id']} name={db['name']} engine={db.get('engine')}")
    print()

    # 找到 ds_sales_report table
    for db in db_list:
        tables = get(tok, f"/database/{db['id']}/metadata")
        for t in tables.get("tables") or []:
            if t.get("name") == "ds_sales_report":
                print(f"Table: {t['name']} (id={t['id']}, db={db['name']})")
                print("Fields:")
                for f in sorted(t.get("fields") or [], key=lambda x: x.get("name") or ""):
                    print(f"  field_id={f['id']:>5} name={f['name']:<30} base={f.get('base_type')}")
                print()

    # Dashboard id 清單
    print("Dashboards:")
    dashes = sorted(get(tok, "/dashboard"), key=lambda x: x.get("name") or "")
    for d in dashes:
        print(f"  id={d['id']:>3} name={d['name']}")


if __name__ == "__main__":
    main()
