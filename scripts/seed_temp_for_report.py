#!/usr/bin/env python3
"""
為報告截圖建立暫時性的種子資料；同時提供清除模式。
- 用法：python3 scripts/seed_temp_for_report.py [seed|cleanup]
- 機制：以 IDs 寫入 /tmp/dmis_seed_ids.json 追蹤；cleanup 讀回後 unlink。
"""
import json
import os
import sys
from urllib import request

BASE = "http://localhost:8069"
DB = "dmis_dev"
USER = "admin"
PWD = "admin"
TRACK_FILE = "/tmp/dmis_seed_ids.json"


def login():
    body = {"jsonrpc": "2.0", "params": {"db": DB, "login": USER, "password": PWD}}
    req = request.Request(
        f"{BASE}/web/session/authenticate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = request.urlopen(req)
    sid = ""
    for part in resp.headers.get("Set-Cookie", "").split(","):
        for kv in part.split(";"):
            kv = kv.strip()
            if kv.startswith("session_id="):
                sid = kv.split("=", 1)[1]
    if not sid:
        print("login failed")
        sys.exit(1)
    return sid


def rpc(model, method, args=None, kwargs=None, sid=None):
    payload = {
        "jsonrpc": "2.0", "method": "call",
        "params": {"model": model, "method": method,
                   "args": args or [], "kwargs": kwargs or {}},
    }
    headers = {"Content-Type": "application/json", "Cookie": f"session_id={sid}"}
    req = request.Request(f"{BASE}/web/dataset/call_kw",
                          data=json.dumps(payload).encode(), headers=headers)
    res = json.loads(request.urlopen(req).read())
    if "error" in res:
        msg = res["error"].get("data", {}).get("message", res["error"])
        raise RuntimeError(msg)
    return res.get("result")


def create_track(sid, tracker, model, vals):
    rid = rpc(model, "create", [vals], sid=sid)
    tracker.setdefault(model, []).append(rid)
    return rid


def seed():
    sid = login()
    tracker = {}
    print(f"login ok, sid={sid[:10]}...")

    dealers = rpc("dms.dealer", "search_read", [[], ["id", "name"]],
                  {"limit": 3, "order": "id"}, sid=sid)
    purposes = rpc("dms.visit.purpose", "search_read", [[], ["id"]],
                   {"limit": 1}, sid=sid)
    visitor = rpc("res.users", "search", [[["id", "=", 2]]], sid=sid)[0]
    purpose_id = purposes[0]["id"] if purposes else False
    visit_dates = ["2026-04-15 10:00:00", "2026-04-22 14:30:00", "2026-04-28 09:00:00"]
    states = ["done", "done", "draft"]
    for d, vd, st in zip(dealers, visit_dates, states):
        create_track(sid, tracker, "dms.visit", {
            "visit_date": vd, "dealer_id": d["id"], "visitor_id": visitor,
            "purpose_id": purpose_id, "state": st,
            "note": f"例行拜訪 {d['name']}：確認展車、補充 DM 與優惠單張。",
        })
    print(f"seed dms.visit: {len(tracker.get('dms.visit', []))} records")

    orders = rpc("dms.sale.order", "search_read",
                 [[["state", "=", "confirmed"], ["dealer_id", "!=", False],
                   ["product_id", "!=", False]],
                  ["id", "name"]],
                 {"limit": 2, "order": "id desc"}, sid=sid)
    for o in orders:
        try:
            create_track(sid, tracker, "dms.commission.record", {
                "sale_order_id": o["id"],
                "base_commission": 800.0, "volume_bonus": 200.0,
                "state": "active",
            })
        except Exception as e:
            print(f"  commission_record skip: {e}")
    print(f"seed dms.commission.record: {len(tracker.get('dms.commission.record', []))} records")

    incentive_types = rpc("dms.incentive.type", "search_read", [[], ["id"]],
                          {"limit": 1}, sid=sid)
    if incentive_types and orders:
        for o in orders:
            try:
                create_track(sid, tracker, "dms.incentive.delivery", {
                    "sale_order_id": o["id"],
                    "incentive_type_id": incentive_types[0]["id"],
                    "qty": 1, "state": "pending",
                    "remark": "核銷待出貨：超商提貨券 500 元",
                })
            except Exception as e:
                print(f"  incentive_delivery skip: {e}")
    print(f"seed dms.incentive.delivery: {len(tracker.get('dms.incentive.delivery', []))} records")

    used_tmpl_ids = rpc("dms.commission.vehicle.rule", "search_read",
                        [[], ["product_tmpl_id"]], sid=sid)
    used = {r["product_tmpl_id"][0] for r in used_tmpl_ids if r.get("product_tmpl_id")}
    tmpls = rpc("dms.product.template", "search",
                [[["id", "not in", list(used)] if used else []]],
                {"limit": 1}, sid=sid)
    if tmpls:
        try:
            create_track(sid, tracker, "dms.commission.vehicle.rule", {
                "product_tmpl_id": tmpls[0],
                "addon_amount": 1500.0,
                "note": "該車型專屬加碼 1500 元",
            })
        except Exception as e:
            print(f"  vehicle_rule skip: {e}")
    print(f"seed dms.commission.vehicle.rule: {len(tracker.get('dms.commission.vehicle.rule', []))} records")

    with open(TRACK_FILE, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)
    print(f"\nTracker -> {TRACK_FILE}")
    print(json.dumps(tracker, ensure_ascii=False))


def cleanup():
    if not os.path.exists(TRACK_FILE):
        # fallback: 嘗試清除資料庫中所有 fallback 假資料
        print("no tracker file. Try fallback cleanup of any visit with note prefix.")
        sid = login()
        try:
            ids = rpc("dms.visit", "search",
                      [[["note", "ilike", "例行拜訪"]]], sid=sid)
            if ids:
                rpc("dms.visit", "unlink", [ids], sid=sid)
                print(f"  fallback removed {len(ids)} dms.visit")
        except Exception as e:
            print(f"  fallback error: {e}")
        return
    with open(TRACK_FILE, "r", encoding="utf-8") as f:
        tracker = json.load(f)
    sid = login()
    print(f"login ok, sid={sid[:10]}...")
    for model, ids in tracker.items():
        if not ids:
            continue
        try:
            rpc(model, "unlink", [ids], sid=sid)
            print(f"{model}: removed {len(ids)} records")
        except Exception as e:
            print(f"{model}: cleanup error -> {e}")
    os.unlink(TRACK_FILE)
    print("CLEANUP DONE.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if mode == "seed":
        seed()
    elif mode == "cleanup":
        cleanup()
    else:
        print("usage: seed_temp_for_report.py [seed|cleanup]")
        sys.exit(2)
