"""手機文字健檢（T-267）：每頁在 375／390 寬執行 mobile_text_audit.js，列出水平溢出、被藏起來的文字、
太窄的文字欄（一個字一行）與被拆行的短標籤，並存整頁截圖。不進 CI，本機手動執行。

  python tools/ui_audit/mobile_text_audit.py OUT --urls tmp/ui-snap/before/urls.json --db-from tmp/ui-snap-golden [--jobs 8]

全程只用 seed_help_demo 的合成資料與 tmp/ 下的暫存 SQLite。
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402

AUDIT = (Path(__file__).resolve().parent / "mobile_text_audit.js").read_text(encoding="utf-8")
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
SIZES = {375: 812, 390: 844}


def slug(url):
    import re
    return (re.sub(r"[^\w-]+", "_", url.strip("/")) or "home")[:90]


def worker(args):
    base, key, urls, out, shots = args
    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    from playwright.sync_api import sync_playwright
    from snapshot_compare import MASK, SETTLE
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in SIZES.items():
            ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                      is_mobile=True, has_touch=True, user_agent=UA, locale="zh-TW")
            ctx.add_cookies([{"name": "sessionid", "value": key, "url": base}])
            page = ctx.new_page()
            for url in urls:
                try:
                    page.goto(base + url, wait_until="networkidle", timeout=45000)
                    page.add_style_tag(content=MASK)
                    page.evaluate(SETTLE)
                    results[f"{width} {url}"] = page.evaluate(AUDIT)
                    if shots:
                        path = Path(out) / str(width) / f"{slug(url)}.png"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(path), full_page=True, animations="disabled", caret="hide")
                    # 訂單頁的各步驟：只有目前步驟顯示，其他步驟用 ?tab= 逐一打開再量（伺服器端就會把該步驟設為目前步驟）。
                    if "tab=" not in url:
                        keys = page.evaluate("[...document.querySelectorAll('[role=tabpanel][data-step-key]:not(.is-active)')].map(p => p.dataset.stepKey)")
                        for key in keys:
                            tab_url = url + ("&" if "?" in url else "?") + f"tab={key}"
                            page.goto(base + tab_url, wait_until="networkidle", timeout=45000)
                            page.add_style_tag(content=MASK)
                            page.evaluate(SETTLE)
                            results[f"{width} {tab_url}"] = page.evaluate(AUDIT)
                            if shots:
                                path = Path(out) / str(width) / f"{slug(tab_url)}.png"
                                page.screenshot(path=str(path), full_page=True, animations="disabled", caret="hide")
                except Exception as error:  # noqa: BLE001
                    results[f"{width} {url}"] = {"error": str(error)[:200]}
            ctx.close()
        browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--urls", required=True)
    parser.add_argument("--db-from", required=True)
    parser.add_argument("--port", type=int, default=8873)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--no-shots", action="store_true")
    parser.add_argument("--only", help="只跑網址含這段文字的頁面")
    args = parser.parse_args()
    os.environ.setdefault("UI_AUDIT_DB_DIR", str(ROOT / "tmp" / "mobile-audit-db"))
    import snapshot_compare as sc
    from common import prepare, session_key, start_server
    sc.restore_db(Path(args.db_from))
    env = prepare(sc.WORK, fresh=False)
    key = session_key(env)
    urls = json.loads(Path(args.urls).read_text(encoding="utf-8"))
    if args.only:
        urls = [u for u in urls if args.only in u]
    args.out.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{args.port}"
    chunks = [urls[i::args.jobs] for i in range(args.jobs) if urls[i::args.jobs]]
    results = {}
    with open(args.out / "server.log", "wb") as log:
        server = start_server(env, args.port, log)
        try:
            with ProcessPoolExecutor(len(chunks)) as pool:
                for part in pool.map(worker, [(base, key, c, str(args.out), not args.no_shots) for c in chunks]):
                    results.update(part)
        finally:
            server.terminate()
    results = dict(sorted(results.items(), key=lambda kv: (kv[0].split(" ", 1)[1], kv[0])))
    (args.out / "audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {k: sum(len(v.get(k, [])) for v in results.values()) for k in ("overflow", "truncated", "narrow", "split")}
    hscroll = [k for k, v in results.items() if v.get("scrollW", 0) > v.get("vw", 1e9)]
    errors = [k for k, v in results.items() if "error" in v]
    summary = {"pages": len(results), "counts": counts, "hscroll": hscroll, "errors": errors,
               "pagesWithIssues": sorted({k for k, v in results.items() if any(v.get(x) for x in ("truncated", "narrow", "split", "overflow"))})}
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({**summary, "pagesWithIssues": len(summary["pagesWithIssues"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
