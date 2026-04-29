#!/usr/bin/env python3
"""擷取 dms.motor.type.rule 與 dms.dealer.brand.rule 兩個規則表 UI 截圖。"""
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
OUT = Path("/home/audi/project/DMIS/output_report/screenshots_rules")
OUT.mkdir(parents=True, exist_ok=True)


def authenticate():
    body = json.dumps({"jsonrpc": "2.0", "params": {
        "db": DB, "login": USER, "password": PWD
    }}).encode()
    req = request.Request(
        f"{BASE}/web/session/authenticate", data=body,
        headers={"Content-Type": "application/json"},
    )
    resp = request.urlopen(req)
    cookie = resp.headers.get("Set-Cookie", "")
    for part in cookie.split(","):
        for kv in part.split(";"):
            kv = kv.strip()
            if kv.startswith("session_id="):
                return kv.split("=", 1)[1]
    sys.exit("auth failed")


def capture(targets, sid):
    user_dir = "/tmp/chrome-shot-rules"
    subprocess.run(["pkill", "-9", "-f", "chrome.*9222"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["rm", "-rf", user_dir])
    proc = subprocess.Popen([
        "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", f"--user-data-dir={user_dir}",
        "--window-size=1440,900", "--remote-debugging-port=9222",
        "--remote-allow-origins=*", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                c = http.client.HTTPConnection("127.0.0.1", 9222, timeout=1)
                c.request("GET", "/json/version")
                ws_url = json.loads(c.getresponse().read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.3)
        else:
            sys.exit("chrome devtools not ready")

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

        r = send("Target.getTargets")
        target_id = next(t["targetId"] for t in r["result"]["targetInfos"]
                         if t["type"] == "page")
        sess = send("Target.attachToTarget", {
            "targetId": target_id, "flatten": True
        })["result"]["sessionId"]

        send("Network.enable", {}, sess)
        send("Page.enable", {}, sess)
        send("Network.setCookies", {"cookies": [{
            "name": "session_id", "value": sid,
            "domain": "localhost", "path": "/",
        }]}, sess)
        send("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 900,
            "deviceScaleFactor": 1, "mobile": False,
        }, sess)

        for name, url, wait in targets:
            print(f"-> {name}: {url}")
            send("Page.navigate", {"url": url}, sess)
            t0 = time.time()
            while time.time() - t0 < 20:
                try:
                    evt = json.loads(ws.recv())
                    if evt.get("method") == "Page.loadEventFired":
                        break
                except Exception:
                    break
            time.sleep(wait)
            shot = send("Page.captureScreenshot", {"format": "png"}, sess)
            (OUT / f"{name}.png").write_bytes(
                base64.b64decode(shot["result"]["data"]))
            print(f"   saved {name}.png")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main():
    sid = authenticate()
    targets = [
        ("01_motor_type_rule_list",
         f"{BASE}/web#action=495&view_type=list", 6.0),
        ("02_motor_type_rule_form",
         f"{BASE}/web#action=495&view_type=form&id=1", 6.0),
        ("03_dealer_brand_rule_list",
         f"{BASE}/web#action=496&view_type=list", 6.0),
        ("04_dealer_brand_rule_form",
         f"{BASE}/web#action=496&view_type=form&id=1", 6.0),
        ("05_diagnose_unmatched",
         f"{BASE}/web#action=497", 8.0),
        ("06_diagnose_motor_unmatched",
         f"{BASE}/web#action=498", 8.0),
    ]
    capture(targets, sid)


if __name__ == "__main__":
    main()
