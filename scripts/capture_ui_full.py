#!/usr/bin/env python3
"""擷取 DMIS 全模組（六大選單）UI 截圖。"""
import base64
import http.client
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

import websocket  # type: ignore

BASE = "http://localhost:8069"
DB = "dmis_dev"
USER = "admin"
PWD = "admin"
OUT = Path("/home/audi/project/DMIS/output_report/screenshots_full")
OUT.mkdir(parents=True, exist_ok=True)

# (檔名, URL, 等待秒)
TARGETS = [
    # ---- 0. 共通 ----
    ("00_login", f"{BASE}/web/login", 2.0),
    ("00_apps", f"{BASE}/web#action=base.open_module_tree", 7.0),

    # ---- 1. 車行管理 ----
    ("11_dealers_list", f"{BASE}/web#action=85&view_type=list", 7.0),
    ("11_dealers_form", f"{BASE}/web#action=85&id=11&view_type=form", 8.0),
    ("12_brands_list", f"{BASE}/web#action=87&view_type=list", 6.0),
    ("12_brands_form", f"{BASE}/web#action=87&id=1&view_type=form", 6.0),
    ("13_storetype_list", f"{BASE}/web#action=88&view_type=list", 6.0),
    ("13_storetype_form", f"{BASE}/web#action=88&id=1&view_type=form", 6.0),
    ("14_visit_list", f"{BASE}/web#action=104&view_type=list", 7.0),
    ("14_visit_form", f"{BASE}/web#action=104&id=870&view_type=form", 7.0),
    ("15_visit_calendar", f"{BASE}/web#action=105", 8.0),
    ("16_visit_purpose", f"{BASE}/web#action=103&view_type=list", 6.0),
    ("17_holiday_list", f"{BASE}/web#action=108&view_type=list", 6.0),
    ("18_holiday_sync_wizard", f"{BASE}/web#action=119", 6.0),
    ("19_visit_bulk_wizard", f"{BASE}/web#action=149", 6.0),

    # ---- 2. 車銷管理 ----
    ("21_pricetable_list", f"{BASE}/web#action=142&view_type=list", 7.0),
    ("21_pricetable_form", f"{BASE}/web#action=142&id=1&view_type=form", 8.0),
    ("22_sale_list", f"{BASE}/web#action=95&view_type=list", 7.0),
    ("22_sale_form", f"{BASE}/web#action=95&id=7994&view_type=form", 8.0),
    ("23_sale_analysis", f"{BASE}/web#action=463", 7.0),
    ("24_sync_log", f"{BASE}/web#action=460&view_type=list", 6.0),
    ("25_excel_import", f"{BASE}/web#action=462", 6.0),

    # ---- 3. 銷售分析 ----
    ("31_report_sales_pivot", f"{BASE}/web#action=98&view_type=pivot", 8.0),
    ("31_report_sales_graph", f"{BASE}/web#action=98&view_type=graph", 8.0),
    ("32_report_profit", f"{BASE}/web#action=99&view_type=pivot", 7.0),
    ("33_report_commission", f"{BASE}/web#action=100&view_type=pivot", 7.0),
    ("34_report_rule", f"{BASE}/web#action=101&view_type=list", 7.0),
    ("35_report_virtual", f"{BASE}/web#action=102&view_type=list", 7.0),

    # ---- 4. 傭金管理 ----
    ("41_cm_product_rule", f"{BASE}/web#action=153&view_type=list", 6.0),
    ("41_cm_product_rule_form", f"{BASE}/web#action=153&id=10&view_type=form", 6.0),
    ("42_cm_dealer_rule", f"{BASE}/web#action=154&view_type=list", 6.0),
    ("43_cm_vehicle_rule", f"{BASE}/web#action=162&view_type=list", 6.0),
    ("44_cm_volume_rule", f"{BASE}/web#action=155&view_type=list", 6.0),
    ("45_cm_volume_gift", f"{BASE}/web#action=166&view_type=list", 6.0),
    ("46_incentive_type", f"{BASE}/web#action=156&view_type=list", 6.0),
    ("47_incentive_rule", f"{BASE}/web#action=157&view_type=list", 6.0),
    ("48_cm_record", f"{BASE}/web#action=158&view_type=list", 6.0),
    ("48_cm_record_form", f"{BASE}/web#action=158&id=8&view_type=form", 7.0),
    ("49_incentive_delivery", f"{BASE}/web#action=159&view_type=list", 6.0),
    ("49_incentive_delivery_form", f"{BASE}/web#action=159&id=10&view_type=form", 7.0),
    ("4a_cm_monthly", f"{BASE}/web#action=160", 7.0),
    ("4b_cm_summary", f"{BASE}/web#action=161", 7.0),

    # ---- 5. 零件管理 ----
    ("51_part_list", f"{BASE}/web#action=168&view_type=list", 6.0),
    ("51_part_form", f"{BASE}/web#action=168&id=1&view_type=form", 7.0),
    ("52_part_category", f"{BASE}/web#action=167&view_type=list", 6.0),
    ("53_catalog_list", f"{BASE}/web#action=452&view_type=list", 6.0),
    ("53_catalog_form", f"{BASE}/web#action=452&id=1&view_type=form", 7.0),
    ("54_catalog_search_wizard", f"{BASE}/web#action=454", 6.0),
    ("55_catalog_import_wizard", f"{BASE}/web#action=455", 6.0),

    # ---- 6. 使用者管理系統 ----
    ("61_access_group_list", f"{BASE}/web#action=125&view_type=list", 6.0),
    ("61_access_group_form", f"{BASE}/web#action=125&id=1&view_type=form", 7.0),
    ("62_audit_log_list", f"{BASE}/web#action=126&view_type=list", 7.0),
    ("62_audit_log_form", f"{BASE}/web#action=126&id=1&view_type=form", 6.0),
]


def login_session():
    body = json.dumps({"jsonrpc": "2.0", "params": {
        "db": DB, "login": USER, "password": PWD,
    }}).encode()
    req = request.Request(f"{BASE}/web/session/authenticate", data=body,
                          headers={"Content-Type": "application/json"})
    resp = request.urlopen(req)
    sid = ""
    for part in resp.headers.get("Set-Cookie", "").split(","):
        for kv in part.split(";"):
            kv = kv.strip()
            if kv.startswith("session_id="):
                sid = kv.split("=", 1)[1]
    return sid


def shoot_all(sid, only=None):
    user_dir = "/tmp/chrome-shot-full"
    subprocess.run(["rm", "-rf", user_dir])
    proc = subprocess.Popen([
        "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", f"--user-data-dir={user_dir}",
        "--window-size=1440,900",
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                c = http.client.HTTPConnection("127.0.0.1", 9222, timeout=1)
                c.request("GET", "/json/version")
                ws_url = json.loads(c.getresponse().read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("chrome devtools 未就緒")
            sys.exit(1)

        ws = websocket.create_connection(ws_url, timeout=60)
        msg_id = [0]

        def send(method, params=None, sess=None):
            msg_id[0] += 1
            payload = {"id": msg_id[0], "method": method, "params": params or {}}
            if sess:
                payload["sessionId"] = sess
            ws.send(json.dumps(payload))
            while True:
                resp = json.loads(ws.recv())
                if resp.get("id") == msg_id[0]:
                    return resp

        target_id = None
        for t in send("Target.getTargets")["result"]["targetInfos"]:
            if t["type"] == "page":
                target_id = t["targetId"]
                break
        sess = send("Target.attachToTarget",
                    {"targetId": target_id, "flatten": True})["result"]["sessionId"]
        send("Network.enable", {}, sess)
        send("Page.enable", {}, sess)
        send("Network.setCookies", {"cookies": [{
            "name": "session_id", "value": sid, "domain": "localhost", "path": "/",
        }]}, sess)
        send("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False,
        }, sess)

        for name, url, wait in TARGETS:
            if only and name not in only:
                continue
            print(f"-> {name}: {url}")
            send("Page.navigate", {"url": url}, sess)
            t0 = time.time()
            while time.time() - t0 < 25:
                try:
                    evt = json.loads(ws.recv())
                    if evt.get("method") == "Page.loadEventFired":
                        break
                except Exception:
                    break
            time.sleep(wait)
            shot = send("Page.captureScreenshot", {"format": "png"}, sess)
            (OUT / f"{name}.png").write_bytes(base64.b64decode(shot["result"]["data"]))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main():
    sid = login_session()
    if not sid:
        print("login failed")
        sys.exit(1)
    print(f"sid = {sid[:12]}...")
    only = set(sys.argv[1:]) if len(sys.argv) > 1 else None
    shoot_all(sid, only=only)
    print(f"DONE -> {OUT}")


if __name__ == "__main__":
    main()
