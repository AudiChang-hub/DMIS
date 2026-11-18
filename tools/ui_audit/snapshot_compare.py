"""全路由 × 寬度 × 主題的整頁截圖與逐像素比對（T-242）。不進 CI，本機手動執行。

改樣式前後各拍一次，再比對：
  python tools/ui_audit/snapshot_compare.py capture tmp/ui-snap/before
  （改 CSS）
  python tools/ui_audit/snapshot_compare.py capture tmp/ui-snap/after --urls tmp/ui-snap/before/urls.json
  python tools/ui_audit/snapshot_compare.py compare tmp/ui-snap/before tmp/ui-snap/after

capture 選項：
  --widths 375,390,1024,1440   寬度（預設這 4 種；375／390 以手機模式拍）
  --themes all                 主題（預設 6 種全部；逗號分隔可只拍幾種）
  --limit 260                  最多爬幾頁（同一 URL 樣式最多 2 頁）
  --urls FILE                  沿用另一次的網址清單，前後兩次才比得起來
  --db-from DIR                先把同一份合成資料庫複製來用（前後比對必用；GET 頁面也可能寫入資料）
  --widths ""                  只爬網址、不截圖（先產生 urls.json，前後兩次都用它）
  --reuse                      沿用上次的暫存資料庫
全程只用 seed_help_demo 的合成資料與 tmp/ 下的暫存 SQLite。
畫面上會跳動的內容（時鐘、資料時間、<time>、依時段變的首頁問候）先隱藏；比對仍有差異時看 diff 圖判斷是不是動態文字。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, THEMES, crawl, prepare, route_of, session_key, start_server  # noqa: E402

PORT = 8864
WORK = Path(os.environ.get("UI_AUDIT_DB_DIR") or ROOT / "tmp" / "ui-snap-db")  # 同時跑兩支工具時用不同資料夾
MOBILE = {375: 812, 390: 844}
NOISE_PIXELS, NOISE_LEVEL = 80, 48
MASK = ("[data-brand-clock], .ops-stamp, time, [data-relative-time], .home-hero h1, .deletion-review-stats__wait, "
        "input[type=datetime-local], .system-status-summary, .system-status-card p, .system-status-card small { visibility: hidden !important; }"
        "img[loading=lazy] { content-visibility: visible !important; } * { caret-color: transparent !important; }")


# 截圖前：圖片全部載入並解碼、字型就緒、捲回頂端（列表會帶回上次捲動位置）、
# 畫面上的時刻（HH:MM、HH:MM:SS）一律換成 --:--（查詢時間、公告預設時間等每次都不同）。
SETTLE = r"""async () => {
  document.querySelectorAll('img[loading=lazy]').forEach(img => { img.loading = 'eager'; });
  await document.fonts.ready;
  const wait = img => Promise.race([img.decode().catch(() => {}), new Promise(done => setTimeout(done, 8000))]);
  await Promise.all([...document.images].map(wait));
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (/\d{1,2}:\d{2}/.test(node.nodeValue)) node.nodeValue = node.nodeValue.replace(/\b\d{1,2}:\d{2}(:\d{2})?\b/g, '--:--');
  }
  window.scrollTo({top: 0, behavior: 'instant'});
  await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
}"""


def restore_db(source):
    """前後兩次截圖都從同一份合成資料開始：GET 頁面也可能寫入資料（例如自動同步），不能沿用上一次跑過的資料庫。"""
    import shutil
    from common import SETTINGS
    if WORK.exists():
        shutil.rmtree(WORK)
    shutil.copytree(source, WORK)
    (WORK / "settings" / "help_demo_settings.py").write_text(
        SETTINGS.format(db=WORK / "demo.sqlite3", media=WORK / "media"), encoding="utf-8")


def slug(url):
    return (re.sub(r"[^\w-]+", "_", url.strip("/")) or "home")[:90]


def capture(out, widths, themes, limit, urls_file, reuse, db_from=None, port=PORT):
    out.mkdir(parents=True, exist_ok=True)
    if db_from:
        restore_db(Path(db_from))
    env = prepare(WORK, fresh=not (reuse or db_from))
    key = session_key(env)
    base = f"http://127.0.0.1:{port}"
    failures = []
    with open(out / "server.log", "wb") as log:
        server = start_server(env, port, log)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                if urls_file:
                    urls = json.loads(Path(urls_file).read_text(encoding="utf-8"))
                else:
                    context = browser.new_context(viewport={"width": 1440, "height": 900})
                    context.add_cookies([{"name": "sessionid", "value": key, "url": base}])
                    urls = crawl(context.new_page(), base, route_of(env), limit=limit)
                    context.close()
                (out / "urls.json").write_text(json.dumps(urls, ensure_ascii=False, indent=1), encoding="utf-8")
                if not widths:
                    print(f"只爬網址：{len(urls)} 頁 → {out / 'urls.json'}")
                total = len(urls) * len(widths) * len(themes)
                print(f"{len(urls)} 頁 × {len(widths)} 寬度 × {len(themes)} 主題 = {total} 張", flush=True)
                for width in widths:
                    mobile = width in MOBILE
                    context = browser.new_context(viewport={"width": width, "height": MOBILE.get(width, 900)},
                                                  device_scale_factor=1, is_mobile=mobile, has_touch=mobile)
                    context.add_cookies([{"name": "sessionid", "value": key, "url": base}])
                    page = context.new_page()
                    for url in urls:
                        try:
                            page.goto(base + url, wait_until="networkidle", timeout=30000)
                            page.add_style_tag(content=MASK)
                            page.evaluate(SETTLE)
                        except Exception as error:  # noqa: BLE001
                            failures.append(f"{width} {url} {str(error)[:80]}")
                            continue
                        for theme in themes:
                            page.evaluate("t => { document.documentElement.dataset.theme = t; void document.body.offsetHeight; }", theme)
                            path = out / theme / str(width) / f"{slug(url)}.png"
                            path.parent.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(path), full_page=True, animations="disabled", caret="hide")
                    context.close()
                browser.close()
        finally:
            server.terminate()
    (out / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=1), encoding="utf-8")
    print("完成；失敗", len(failures), "頁（見 failures.json）")


def compare(before, after, out):
    from PIL import Image, ImageChops
    out = out or after.parent / f"diff-{after.name}"
    out.mkdir(parents=True, exist_ok=True)
    # 同一份程式連拍兩次，固定定位底部選單下的文字偶爾有反鋸齒差異（最多約 40 個像素、色差 ≤ 27）；
    # 不超過 NOISE_PIXELS 個像素、且沒有任何像素色差達 NOISE_LEVEL 的，另列「渲染雜訊」，不算畫面改變。
    report = {"identical": 0, "noise": [], "changed": [], "missing": []}
    for old in sorted(before.rglob("*.png")):
        rel = old.relative_to(before)
        new = after / rel
        if not new.exists():
            report["missing"].append(str(rel)); continue
        a, b = Image.open(old).convert("RGB"), Image.open(new).convert("RGB")
        if a.size != b.size:
            report["changed"].append({"file": str(rel), "size": [a.size, b.size]})
            continue
        diff = ImageChops.difference(a, b)
        box = diff.getbbox()
        if not box:
            report["identical"] += 1; continue
        histogram = diff.convert("L").histogram()
        pixels, strong = sum(histogram[1:]), sum(histogram[NOISE_LEVEL:])
        if pixels <= NOISE_PIXELS and not strong:
            report["noise"].append({"file": str(rel), "bbox": box, "pixels": pixels}); continue
        report["changed"].append({"file": str(rel), "bbox": box, "pixels": pixels})
        x0, y0, x1, y1 = box
        pad = 40
        crop = (max(0, x0 - pad), max(0, y0 - pad), min(a.size[0], x1 + pad), min(a.size[1], y1 + pad))
        left, right = a.crop(crop), b.crop(crop)
        sheet = Image.new("RGB", (left.size[0] * 2 + 12, left.size[1]), "red")
        sheet.paste(left, (0, 0)); sheet.paste(right, (left.size[0] + 12, 0))
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(target)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"相同 {report['identical']}、渲染雜訊 {len(report['noise'])}、不同 {len(report['changed'])}、缺少 {len(report['missing'])}；明細與左右對照圖在 {out}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("out", type=Path)
    cap.add_argument("--widths", default="375,390,1024,1440")
    cap.add_argument("--themes", default="all")
    cap.add_argument("--limit", type=int, default=260)
    cap.add_argument("--urls")
    cap.add_argument("--reuse", action="store_true")
    cap.add_argument("--port", type=int, default=PORT, help="示範伺服器埠號；同時跑兩份（前／後）時要錯開")
    cap.add_argument("--db-from", help="先把這份合成資料庫（prepare 過的資料夾）複製來用；前後兩次截圖都要用同一份")
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("before", type=Path)
    cmp_.add_argument("after", type=Path)
    cmp_.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        themes = THEMES if args.themes == "all" else tuple(t for t in args.themes.split(",") if t in THEMES)
        capture(args.out, [int(w) for w in args.widths.split(",") if w], themes, args.limit, args.urls, args.reuse, args.db_from, args.port)
    else:
        compare(args.before, args.after, args.out)


if __name__ == "__main__":
    main()
