"""換頁效能量測：CPU 降速 4 倍下的 CSS 大小、app.css 解析、整頁樣式重算、long task（T-242）。不進 CI。

用法：python tools/ui_audit/perf_probe.py <輸出.json> --db-from <合成資料庫> [--port 8868] [--pages /a/ /b/]
每頁量 3 次取中位數；搬樣式前後各在自己的工作樹跑一次，再比 JSON。
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import prepare, session_key, start_server  # noqa: E402
from snapshot_compare import WORK, restore_db  # noqa: E402

PAGES = ("/", "/orders/", "/orders/30/", "/operations/", "/data/", "/data/price-list-distribution/",
         "/data/price-list-distribution/1/assignments/", "/data/dealer-reward-items/", "/data/catalog/photos/",
         "/data/business-holidays/")
INIT = "window.__lt=[];try{new PerformanceObserver(l=>{for(const e of l.getEntries()) __lt.push(e.duration)}).observe({type:'longtask',buffered:true});}catch(e){}"
PROBE = """async () => {
  const sheets = [...document.styleSheets].filter(s => s.href);
  const css = {};
  for (const s of sheets) { const r = performance.getEntriesByName(s.href)[0]; css[new URL(s.href).pathname] = r ? Math.round(r.decodedBodySize / 1024) : null; }
  let rules = 0;
  const count = list => { for (const r of list) { rules++; if (r.cssRules) count(r.cssRules); } };
  for (const s of document.styleSheets) { try { count(s.cssRules); } catch (e) {} }
  const html = document.documentElement, theme = html.dataset.theme, t = [];
  for (let i = 0; i < 6; i++) { const a = performance.now(); html.dataset.theme = i % 2 ? theme : 'night-blue'; void html.offsetHeight; t.push(performance.now() - a); }
  html.dataset.theme = theme; void html.offsetHeight; t.sort((x, y) => x - y);
  const app = sheets.find(s => s.href.includes('/css/app'));
  const text = await (await fetch(app.href)).text();
  const p = []; for (let i = 0; i < 3; i++) { const a = performance.now(); new CSSStyleSheet().replaceSync(text); p.push(performance.now() - a); }
  p.sort((x, y) => x - y);
  return {css, rules, recalcMs: t[3], appParseMs: p[1], longTaskMs: __lt.reduce((a, b) => a + b, 0), longTasks: __lt.length};
}"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--db-from", required=True)
    parser.add_argument("--port", type=int, default=8868)
    parser.add_argument("--pages", nargs="*", default=list(PAGES))
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    restore_db(Path(args.db_from))
    env = prepare(WORK, fresh=False)
    key = session_key(env)
    base = f"http://127.0.0.1:{args.port}"
    result = {}
    with open(args.out.with_suffix(".server.log"), "wb") as log:
        server = start_server(env, args.port, log)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                for mobile, width in ((True, 375), (False, 1440)):
                    for url in args.pages:
                        runs = []
                        for _ in range(args.runs):
                            context = browser.new_context(viewport={"width": width, "height": 900}, is_mobile=mobile, has_touch=mobile)
                            context.add_cookies([{"name": "sessionid", "value": key, "url": base}])
                            context.add_init_script(INIT)
                            page = context.new_page()
                            cdp = context.new_cdp_session(page)
                            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
                            page.goto(base + url, wait_until="load")
                            page.wait_for_timeout(300)
                            runs.append(page.evaluate(PROBE))
                            context.close()
                        median = {k: statistics.median(r[k] for r in runs) for k in ("rules", "recalcMs", "appParseMs", "longTaskMs", "longTasks")}
                        median["css"] = runs[0]["css"]
                        result[f"{width} {url}"] = {k: round(v, 1) if isinstance(v, float) else v for k, v in median.items()}
                        print(width, url, result[f"{width} {url}"], flush=True)
                browser.close()
        finally:
            server.terminate()
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
