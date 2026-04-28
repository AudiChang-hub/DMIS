#!/usr/bin/env python3
"""
擷取 Odoo 主要畫面截圖以供報告使用。
登入 dmis_dev，取得 session cookie，再以 headless Chrome 開啟各頁面截圖。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

BASE = "http://localhost:8069"
DB = "dmis_dev"
USER = "admin"
PWD = "admin"
OUT = Path("/home/audi/project/DMIS/output_report/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def authenticate():
    body = json.dumps({"jsonrpc": "2.0", "params": {
        "db": DB, "login": USER, "password": PWD
    }}).encode()
    req = request.Request(
        f"{BASE}/web/session/authenticate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    resp = request.urlopen(req)
    raw = resp.read()
    cookie = resp.headers.get("Set-Cookie", "")
    sid = ""
    for part in cookie.split(","):
        for kv in part.split(";"):
            kv = kv.strip()
            if kv.startswith("session_id="):
                sid = kv.split("=", 1)[1]
    if not sid:
        print("auth failed:", raw[:200])
        sys.exit(1)
    return sid


def shoot(name, url, sid, w=1440, h=900, wait_ms=5000):
    out = OUT / f"{name}.png"
    # 用 chrome headless ，先寫一個 tmp html 自動帶 cookie 不容易，改用 --user-data-dir + 啟動腳本
    # 簡單做法：使用 chrome 的 --header / 透過 cookie 檔案不直接支援；改用 python http 取得後的轉換不可行。
    # 採折衷：先用 chrome 啟動 about:blank 寫入 cookie 後 navigate。需 DevTools。
    # 為簡化，使用 chrome 的 --remote-debugging-port + python cdp。
    raise NotImplementedError


def shoot_via_cdp(targets, sid):
    import http.client
    import websocket  # type: ignore

    # 啟動 chrome
    user_dir = "/tmp/chrome-shot"
    subprocess.run(["rm", "-rf", user_dir])
    proc = subprocess.Popen([
        "google-chrome",
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        f"--user-data-dir={user_dir}",
        "--window-size=1440,900",
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # 等待 devtools
        for _ in range(40):
            try:
                c = http.client.HTTPConnection("127.0.0.1", 9222, timeout=1)
                c.request("GET", "/json/version")
                r = c.getresponse()
                data = json.loads(r.read())
                ws_url = data["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("chrome devtools 未就緒")
            sys.exit(1)

        ws = websocket.create_connection(ws_url, timeout=30)
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

        # 取得 target / attach
        r = send("Target.getTargets")
        target_id = None
        for t in r["result"]["targetInfos"]:
            if t["type"] == "page":
                target_id = t["targetId"]
                break
        att = send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        sess = att["result"]["sessionId"]

        send("Network.enable", {}, sess)
        send("Page.enable", {}, sess)
        send("Network.setCookies", {"cookies": [{
            "name": "session_id",
            "value": sid,
            "domain": "localhost",
            "path": "/",
        }]}, sess)
        send("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False
        }, sess)

        for name, url, wait in targets:
            print(f"-> {name}: {url}")
            send("Page.navigate", {"url": url}, sess)
            # 等待 load event
            t0 = time.time()
            loaded = False
            while time.time() - t0 < 20:
                try:
                    raw = ws.recv()
                    evt = json.loads(raw)
                    if evt.get("method") == "Page.loadEventFired":
                        loaded = True
                        break
                except Exception:
                    break
            time.sleep(wait)  # 額外等 Odoo client 渲染
            shot = send("Page.captureScreenshot", {"format": "png"}, sess)
            png = shot["result"]["data"]
            import base64
            (OUT / f"{name}.png").write_bytes(base64.b64decode(png))
            print(f"   saved {name}.png ({len(png)} b64 chars)")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def main():
    sid = authenticate()
    print("session_id =", sid[:12], "...")

    targets = [
        ("01_login", f"{BASE}/web/login", 2.0),
        ("02_apps", f"{BASE}/web#action=base.open_module_tree", 7.0),
        ("03_dealers", f"{BASE}/web#action=85", 7.0),
        ("03b_dealer_form", f"{BASE}/web#action=85&id=11&view_type=form", 7.0),
        ("04_customers", f"{BASE}/web#action=89", 7.0),
        ("05_products", f"{BASE}/web#action=142", 7.0),
        ("05b_product_form", f"{BASE}/web#action=142&id=1&view_type=form", 8.0),
        ("06_sales", f"{BASE}/web#action=95", 7.0),
        ("06b_sale_form", f"{BASE}/web#action=95&id=7994&view_type=form", 8.0),
        ("07_visits", f"{BASE}/web#action=104", 7.0),
        ("07b_visit_new", f"{BASE}/web#action=104&view_type=form", 7.0),
        ("08_finance", f"{BASE}/web#action=96", 7.0),
        ("08b_finance_new", f"{BASE}/web#action=96&view_type=form", 7.0),
        ("09_report", f"{BASE}/web#action=98&view_type=pivot", 8.0),
        ("09b_report_graph", f"{BASE}/web#action=98&view_type=graph", 8.0),
    ]
    shoot_via_cdp(targets, sid)


if __name__ == "__main__":
    main()
