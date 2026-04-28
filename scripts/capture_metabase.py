#!/usr/bin/env python3
"""擷取 Metabase 儀表板截圖供進度報告使用。

使用方式：
    python3 scripts/capture_metabase.py

會將 PNG 寫入 output_report/screenshots_full/metabase_*.png。
"""
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

BASE = "http://localhost:3000"
EMAIL = "admin@dmis.local"
PASSWORD = "Dmis2026!"
OUT = Path("/home/audi/project/DMIS/output_report/screenshots_full")
OUT.mkdir(parents=True, exist_ok=True)

# (檔名, URL, 等待秒)
TARGETS = [
    ("metabase_home", f"{BASE}/", 6.0),
    ("metabase_dashboards", f"{BASE}/collection/root", 6.0),
    ("metabase_p1_total_sales", f"{BASE}/dashboard/2", 9.0),
    ("metabase_p3_ev_sales", f"{BASE}/dashboard/4", 9.0),
    ("metabase_p9_fuel_sales", f"{BASE}/dashboard/9", 9.0),
    ("metabase_p11_dealer_sales", f"{BASE}/dashboard/11", 9.0),
]


def login_session():
    body = json.dumps({"username": EMAIL, "password": PASSWORD}).encode()
    req = request.Request(f"{BASE}/api/session", data=body,
                          headers={"Content-Type": "application/json"})
    resp = request.urlopen(req)
    data = json.loads(resp.read())
    return data["id"]


def shoot_all(token):
    user_dir = "/tmp/chrome-shot-metabase"
    subprocess.run(["rm", "-rf", user_dir])
    proc = subprocess.Popen([
        "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", f"--user-data-dir={user_dir}",
        "--window-size=1440,900",
        "--remote-debugging-port=9223",
        "--remote-allow-origins=*",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                c = http.client.HTTPConnection("127.0.0.1", 9223, timeout=1)
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
            "name": "metabase.SESSION", "value": token,
            "domain": "localhost", "path": "/",
        }]}, sess)
        send("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False,
        }, sess)

        for name, url, wait in TARGETS:
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
    token = login_session()
    print(f"metabase token = {token[:12]}...")
    shoot_all(token)
    print(f"DONE -> {OUT}")


if __name__ == "__main__":
    main()
