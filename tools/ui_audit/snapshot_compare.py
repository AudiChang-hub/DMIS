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
  --reuse                      沿用上次的暫存資料庫（合成資料相同，前後比對時建議加上）
全程只用 seed_help_demo 的合成資料與 tmp/ 下的暫存 SQLite。
畫面上會跳動的內容（時鐘、資料時間、<time>）先隱藏；比對仍有差異時看 diff 圖判斷是不是動態文字。
"""
import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, THEMES, crawl, prepare, route_of, session_key, start_server  # noqa: E402

PORT = 8864
WORK = ROOT / "tmp" / "ui-snap-db"
MOBILE = {375: 812, 390: 844}
MASK = "[data-brand-clock], .ops-stamp, time, [data-relative-time] { visibility: hidden !important; } * { caret-color: transparent !important; }"


def slug(url):
    return (re.sub(r"[^\w-]+", "_", url.strip("/")) or "home")[:90]


def capture(out, widths, themes, limit, urls_file, reuse):
    out.mkdir(parents=True, exist_ok=True)
    env = prepare(WORK, fresh=not reuse)
    key = session_key(env)
    base = f"http://127.0.0.1:{PORT}"
    failures = []
    with open(out / "server.log", "wb") as log:
        server = start_server(env, PORT, log)
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
    report = {"identical": 0, "changed": [], "missing": []}
    for old in sorted(before.rglob("*.png")):
        rel = old.relative_to(before)
        new = after / rel
        if not new.exists():
            report["missing"].append(str(rel)); continue
        a, b = Image.open(old).convert("RGB"), Image.open(new).convert("RGB")
        if a.size != b.size:
            report["changed"].append({"file": str(rel), "size": [a.size, b.size]})
            continue
        box = ImageChops.difference(a, b).getbbox()
        if not box:
            report["identical"] += 1; continue
        report["changed"].append({"file": str(rel), "bbox": box})
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
    print(f"相同 {report['identical']}、不同 {len(report['changed'])}、缺少 {len(report['missing'])}；明細與左右對照圖在 {out}")
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
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("before", type=Path)
    cmp_.add_argument("after", type=Path)
    cmp_.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        themes = THEMES if args.themes == "all" else tuple(t for t in args.themes.split(",") if t in THEMES)
        capture(args.out, [int(w) for w in args.widths.split(",")], themes, args.limit, args.urls, args.reuse)
    else:
        compare(args.before, args.after, args.out)


if __name__ == "__main__":
    main()
