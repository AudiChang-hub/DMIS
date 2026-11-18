"""指定頁面的互動狀態截圖（滑過、聚焦、展開），給 snapshot_compare.py compare 比對（T-242）。不進 CI。

全路由截圖只拍靜態畫面；搬樣式時另外用這支拍「滑過、鍵盤聚焦、展開」的樣子，前後各拍一次再比對：
  python tools/ui_audit/interaction_states.py tmp/ui-snap/states-after --db-from <合成資料庫> --pages /data/... /data/...
每頁在每種寬度、主題各拍：整頁、第一個 details 展開、前 N 個可互動元素各自滑過與聚焦時的局部圖。
"""
import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import prepare, session_key, start_server  # noqa: E402
from snapshot_compare import MASK, SETTLE, WORK, restore_db  # noqa: E402

TARGETS = "main a[href], main button, main summary, main [role=tab], main input:not([type=hidden]), main select, main tr, main [tabindex='0']"


def slug(url):
    return (re.sub(r"[^\w-]+", "_", url.strip("/")) or "home")[:90]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--pages", nargs="+", required=True)
    parser.add_argument("--db-from", required=True)
    parser.add_argument("--port", type=int, default=8866)
    parser.add_argument("--widths", default="375,1440")
    parser.add_argument("--themes", default="professional,night-blue")
    parser.add_argument("--per-page", type=int, default=12)
    args = parser.parse_args()
    restore_db(Path(args.db_from))
    env = prepare(WORK, fresh=False)
    key = session_key(env)
    base = f"http://127.0.0.1:{args.port}"
    log_rows = []
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "server.log", "wb") as log:
        server = start_server(env, args.port, log)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                for width in (int(w) for w in args.widths.split(",")):
                    mobile = width < 860
                    context = browser.new_context(viewport={"width": width, "height": 900}, is_mobile=mobile, has_touch=mobile)
                    context.add_cookies([{"name": "sessionid", "value": key, "url": base}])
                    page = context.new_page()
                    for url in args.pages:
                        for theme in args.themes.split(","):
                            folder = args.out / theme / str(width) / slug(url)
                            folder.mkdir(parents=True, exist_ok=True)
                            response = page.goto(base + url, wait_until="networkidle")
                            if not response or response.status >= 400:
                                log_rows.append(f"{width} {url} HTTP {response.status if response else '-'}"); break
                            page.add_style_tag(content=MASK)
                            page.evaluate("t => { document.documentElement.dataset.theme = t; }", theme)
                            page.evaluate(SETTLE)
                            page.screenshot(path=str(folder / "page.png"), full_page=True, animations="disabled", caret="hide")
                            if page.evaluate("(() => { const d = document.querySelector('main details:not([open])'); if (d) d.open = true; return !!d; })()"):
                                page.screenshot(path=str(folder / "details-open.png"), full_page=True, animations="disabled", caret="hide")
                            handles = [h for h in page.query_selector_all(TARGETS) if h.is_visible()][:args.per_page]
                            for index, handle in enumerate(handles):
                                try:
                                    # 全站 scroll-behavior: smooth：要用 instant，否則截圖時還在捲動，局部圖位置會跑掉。
                                    handle.evaluate("e => e.scrollIntoView({block: 'center', behavior: 'instant'})")
                                    page.wait_for_timeout(100)
                                    box = handle.bounding_box()
                                    if not box or box["width"] < 2:
                                        continue
                                    clip = {"x": max(0, box["x"] - 8), "y": max(0, box["y"] - 8),
                                            "width": min(box["width"] + 16, width), "height": min(box["height"] + 16, 600)}
                                    # 直接移動滑鼠到元素中心（不做可點擊檢查），被覆蓋的元素也照樣拍，前後兩次拍的元素才一致。
                                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                    page.wait_for_timeout(250)
                                    page.screenshot(path=str(folder / f"{index:02d}-hover.png"), clip=clip, animations="disabled", caret="hide")
                                    handle.focus()
                                    page.keyboard.press("Shift")  # 讓 :focus-visible 生效
                                    page.wait_for_timeout(150)
                                    page.screenshot(path=str(folder / f"{index:02d}-focus.png"), clip=clip, animations="disabled", caret="hide")
                                    page.mouse.move(0, 0)
                                except Exception as error:  # noqa: BLE001
                                    log_rows.append(f"{width} {url} #{index} {str(error)[:60]}")
                    context.close()
                browser.close()
        finally:
            server.terminate()
    (args.out / "log.json").write_text(json.dumps(log_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("完成；略過", len(log_rows), "項（見 log.json）")


if __name__ == "__main__":
    main()
