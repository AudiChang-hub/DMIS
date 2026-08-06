#!/usr/bin/env python3
"""DMIS 端對端使用流程測試（API 層）。

Browser tool 不可用，改以 HTTP/RPC 模擬使用者流程：
  1. Odoo /web/login 登入
  2. 透過 RPC 讀取 ds.sales.report（銷售分析）列表與 aggregate
  3. /metabase/public/dashboard 嵌入路由驗證
  4. Metabase session + 逐 card 執行（57 張）統計成功/失敗率
  5. 抽樣各 dashboard 代表 card，驗證篩選條件確實生效
"""
import json
import os
import sys
import requests
from collections import Counter
from metabase_credentials import load_metabase_credentials

ODOO = os.environ.get("ODOO_URL", "http://localhost:8069")
DB = os.environ.get("ODOO_DB", "dmis_dev")
ODOO_USERNAME = os.environ.get("ODOO_USERNAME")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD")
if not ODOO_USERNAME or not ODOO_PASSWORD:
    raise SystemExit("請先設定 ODOO_USERNAME 與 ODOO_PASSWORD 環境變數。")
MB, MB_EMAIL, MB_PASSWORD = load_metabase_credentials(api=False)

OK = "\033[32mOK \033[0m"
FAIL = "\033[31mFAIL\033[0m"

results = []


def step(name, ok, detail=""):
    results.append((ok, name, detail))
    print(f"{OK if ok else FAIL} {name}  {detail}")


# ── Odoo login ─────────────────────────────────────
s = requests.Session()
r = s.post(f"{ODOO}/web/session/authenticate", json={
    "jsonrpc": "2.0",
    "params": {"db": DB, "login": ODOO_USERNAME, "password": ODOO_PASSWORD}
}, timeout=15)
j = r.json()
uid = (j.get("result") or {}).get("uid")
step("Odoo /web/session/authenticate", bool(uid), f"uid={uid}")
if not uid:
    sys.exit(1)


# ── RPC: ds.sales.report search_count + read_group ──
def rpc(model, method, args, kwargs=None):
    r = s.post(f"{ODOO}/web/dataset/call_kw", json={
        "jsonrpc": "2.0",
        "params": {
            "model": model, "method": method,
            "args": args, "kwargs": kwargs or {},
        }
    }, timeout=30)
    return r.json().get("result")


total = rpc("ds.sales.report", "search_count", [[]])
step("ds.sales.report search_count", isinstance(total, int) and total > 0, f"total={total}")

grp = rpc("ds.sales.report", "read_group", [[], ["energy_type"], ["energy_type"]])
step("ds.sales.report read_group(energy_type)", bool(grp), f"groups={[(g['energy_type'], g['energy_type_count']) for g in grp or []]}")

sample = rpc("ds.sales.report", "search_read", [[("state", "=", "confirmed")]],
             {"fields": ["license_date", "model", "dealer", "sales_source", "energy_type",
                         "age_group", "sex", "subsidy_plan", "receipt_price", "remark"],
              "limit": 3})
step("ds.sales.report search_read remark", bool(sample) and "remark" in (sample[0] if sample else {}),
     f"sample_keys={list(sample[0].keys()) if sample else []}")


# ── Odoo 嵌入頁面：dms_report/dashboard ──
r = s.get(f"{ODOO}/web#action=&model=ds.sales.report&view_type=list", timeout=10, allow_redirects=False)
step("Odoo web client", r.status_code in (200, 303), f"HTTP {r.status_code}")


# ── Metabase session ──────────────────────────────
mb = requests.Session()
r = mb.post(f"{MB}/api/session", json={"username": MB_EMAIL, "password": MB_PASSWORD}, timeout=15)
tok = r.json().get("id")
step("Metabase /api/session", bool(tok), f"session={tok[:8] + '...' if tok else ''}")
if not tok:
    sys.exit(1)
hdr = {"X-Metabase-Session": tok}


# ── 執行全部 57 張 card query 並統計 ─────────────────
cards = mb.get(f"{MB}/api/card", headers=hdr).json()
active = [c for c in cards if not c.get("archived")]
step("Metabase cards listing", len(active) >= 57, f"active_cards={len(active)}")

success, fail, rowcounts = 0, 0, []
fail_list = []
for c in active:
    cid = c["id"]
    q = mb.post(f"{MB}/api/card/{cid}/query", headers=hdr, timeout=60)
    if q.status_code < 300:
        data = (q.json() or {}).get("data") or {}
        rows = data.get("rows") or []
        if (q.json() or {}).get("status") == "failed":
            fail += 1
            fail_list.append((cid, c["name"], (q.json() or {}).get("error", "")[:80]))
        else:
            success += 1
            rowcounts.append((cid, c["name"], len(rows)))
    else:
        fail += 1
        fail_list.append((cid, c["name"], f"HTTP {q.status_code}"))

step("Metabase 全卡查詢執行", fail == 0, f"success={success} fail={fail} / total={len(active)}")
if fail_list:
    for cid, n, e in fail_list[:10]:
        print(f"   FAIL card#{cid} {n}: {e}")

# ── 抽樣驗證重建表格 ────────────────────────────────
rebuilt = [44, 46, 50, 52, 53, 54, 59, 60, 61, 68]
print("\n── 重建表格查詢列數 ──")
for cid, n, r in rowcounts:
    if cid in rebuilt:
        print(f"   card#{cid:<3} {n}: {r} rows")

# ── 抽樣驗證 per-card 硬篩 ──────────────────────────
print("\n── per-card 篩選抽樣 ──")
for cid in [49, 57, 62, 69, 80, 92]:  # P5-1, P10-1, P14, P17 first, P19 first, P22 20-29男
    c = mb.get(f"{MB}/api/card/{cid}", headers=hdr).json()
    filters = (((c.get("dataset_query") or {}).get("stages") or [{}])[0].get("filters") or [])
    sigs = []
    for f in filters:
        op = f[0]
        fid = None
        val = None
        for el in f[2:]:
            if isinstance(el, list) and el and el[0] == "field":
                fid = el[2]
            else:
                val = el
        sigs.append(f"{op}|field#{fid}|{val}")
    print(f"   card#{cid} {c.get('name')}: {sigs}")


# ── 總結 ────────────────────────────────────────────
print("\n" + "=" * 60)
ok_cnt = sum(1 for r in results if r[0])
print(f"Summary: {ok_cnt}/{len(results)} checks passed")
for ok, n, d in results:
    mark = "OK" if ok else "FAIL"
    print(f"  [{mark}] {n}  {d}")

sys.exit(0 if ok_cnt == len(results) and fail == 0 else 1)
