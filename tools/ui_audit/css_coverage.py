"""量 app.css 實際用到哪些規則（Chromium CSS coverage，T-242）。不進 CI，本機手動執行。

用法：python tools/ui_audit/css_coverage.py [--reuse] [--limit 260]
  --reuse  沿用上次 tmp/ui-audit/ 的暫存資料庫（省掉重建合成資料的時間）
結果：tmp/ui-audit/coverage.json（逐條規則）與 tmp/ui-audit/coverage-summary.json（統計）。

做法：爬站內連結（同一 URL 樣式最多 2 頁）× 4 種寬度；每頁展開所有 details、逐一打開 dialog、
手機寬度打開「更多」選單、聚焦第一個欄位；部分頁面輪流套 6 種主題。
coverage 看不到滑過、聚焦、錯誤等互動狀態，以及沒爬到的資料情境；分析時把這些另外分類，
並用 rg 式的字詞比對檢查沒用到的 class 是否還出現在模板、static/js、sales 程式裡。
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, THEMES, crawl, prepare, route_of, session_key, start_server  # noqa: E402

PORT = 8863
WIDTHS = ((375, 812, True), (768, 1024, True), (1024, 768, False), (1440, 900, False))
THEME_PAGES = 12  # 每種寬度前幾頁輪流套 6 種主題
STATE = re.compile(r":(hover|focus|focus-visible|focus-within|active|disabled|checked|invalid|placeholder-shown|target|visited)|::placeholder|\[aria-|\[open\]|\.is-[\w-]+|\.has-[\w-]+|\[data-state|\[hidden\]|:has\(")
CLASS = re.compile(r"\.([A-Za-z_][\w-]*)")
CRLF, LF = chr(13) + chr(10), chr(10)

INTERACT = """async (mobile) => {
  document.querySelectorAll('details').forEach(d => { d.open = true; });
  for (const dialog of document.querySelectorAll('dialog')) {
    try { dialog.showModal(); void document.body.offsetHeight; dialog.close(); } catch (e) {}
  }
  const field = document.querySelector('main input:not([type=hidden]), main select, main textarea');
  if (field) { field.focus(); void document.body.offsetHeight; field.blur(); }
  void document.body.offsetHeight;
}"""
THEME_LOOP = """(themes) => {
  const html = document.documentElement, original = html.dataset.theme;
  for (const theme of themes) { html.dataset.theme = theme; void document.body.offsetHeight; getComputedStyle(document.body).color; }
  html.dataset.theme = original; void document.body.offsetHeight;
}"""


def skip_space(text, i, stop):
    """從 i 往後跳過空白與註解，回傳第一個有內容的位置。"""
    while i < stop:
        if text[i].isspace():
            i += 1
        elif text.startswith("/*", i):
            i = text.find("*/", i + 2) + 2 or stop
        else:
            break
    return i


def parse_rules(text):
    """列出 app.css 的每一條樣式規則：(開始, 結束, 選擇器, 所在條件)。
    coverage 只回報有用到的規則，沒用到的要靠這裡列全；開始位置與 coverage 的 startOffset 相同（選擇器第一個字）。
    @keyframes 內的影格、@font-face 不算樣式規則。"""
    rules, stack, i, n, last = [], [], 0, len(text), 0
    while i < n:
        if text.startswith("/*", i):
            i = text.find("*/", i + 2) + 2 or n
            continue
        ch = text[i]
        if ch in "\"'":
            i = text.find(ch, i + 1) + 1 or n
            continue
        if ch == "{":
            start = skip_space(text, last, i)
            prelude = text[start:i].strip()
            stack.append((start, prelude))
            last = i + 1
        elif ch == "}":
            if stack:
                start, prelude = stack.pop()
                parents = [p for _, p in stack]
                if not prelude.startswith("@") and not any(p.startswith(("@keyframes", "@-webkit-keyframes", "@font-face")) for p in parents):
                    rules.append((start, i + 1, prelude, parents))
            last = i + 1
        elif ch == ";" and (not stack or stack[-1][1].startswith("@")):
            last = i + 1  # @import／@charset 等陳述句
        i += 1
    return rules


def measure(urls_limit, reuse):
    work = ROOT / "tmp" / "ui-audit"
    env = prepare(work, fresh=not reuse)
    key = session_key(env)
    route = route_of(env)
    base = f"http://127.0.0.1:{PORT}"
    used_by, per_page, css_text = defaultdict(set), {}, None
    with open(work / "server.log", "wb") as log:
        server = start_server(env, PORT, log)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                for width, height, mobile in WIDTHS:
                    context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=mobile, has_touch=mobile)
                    context.add_cookies([{"name": "sessionid", "value": key, "url": base}])
                    page = context.new_page()
                    urls = crawl(page, base, route, limit=urls_limit)
                    print(f"{width}px：{len(urls)} 頁", flush=True)
                    cdp = context.new_cdp_session(page)
                    sheets = {}
                    cdp.on("CSS.styleSheetAdded", lambda e: sheets.__setitem__(e["header"]["styleSheetId"], e["header"].get("sourceURL", "")))
                    cdp.send("DOM.enable"); cdp.send("CSS.enable")
                    for index, url in enumerate(urls):
                        cdp.send("CSS.startRuleUsageTracking")
                        try:
                            page.goto(base + url, wait_until="networkidle", timeout=30000)
                            page.evaluate(INTERACT, mobile)
                            if mobile and page.query_selector(".mobile-data-menu > summary"):
                                page.click(".mobile-data-menu > summary"); page.wait_for_timeout(150)
                            if index < THEME_PAGES:
                                page.evaluate(THEME_LOOP, list(THEMES))
                        except Exception as error:  # noqa: BLE001
                            print("略過", url, str(error)[:80])
                        usage = cdp.send("CSS.stopRuleUsageTracking")["ruleUsage"]
                        app_ids = {sid for sid, src in sheets.items() if "/css/app" in src}
                        if css_text is None and app_ids:
                            css_text = cdp.send("CSS.getStyleSheetText", {"styleSheetId": next(iter(app_ids))})["text"]
                        name = route(url.split("?")[0]) or url
                        count = 0
                        for item in usage:
                            if item["styleSheetId"] not in app_ids:
                                continue
                            if item["used"]:
                                used_by[int(item["startOffset"])].add(name); count += 1
                        per_page[f"{width} {url}"] = count
                    context.close()
                browser.close()
        finally:
            server.terminate()
    return css_text, used_by, per_page


def corpus_words():
    words = set()
    for folder, pattern in (("templates", "**/*.html"), ("static/js", "**/*.js"), ("sales", "**/*.py")):
        for path in (ROOT / folder).glob(pattern):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            words.update(re.findall(r"[A-Za-z_][\w-]*", path.read_text(encoding="utf-8", errors="ignore")))
    return words


def prefix(selector):
    match = CLASS.search(selector)
    if not match:
        return "（無 class）"
    parts = match.group(1).split("-")
    return "-".join(parts[:2]) if len(parts) > 1 else parts[0]


def analyze(css_text, used_by, per_page):
    words = corpus_words()
    def lf(chunk):  # Windows 工作樹是 CRLF，大小一律以 repo 的 LF 計
        return len(chunk.replace(CRLF, LF).encode())
    total_bytes = lf(css_text)
    rows, cats, cat_bytes = [], Counter(), Counter()
    for start, end, selector, conditions in parse_rules(css_text):
        size = lf(css_text[start:end])
        used = start in used_by
        if used:
            category = "used"
        elif any(c.startswith("@media print") for c in conditions):
            category = "print"
        elif any(k in c for c in conditions for k in ("prefers-reduced-motion", "prefers-color-scheme", "hover:", "pointer:", "prefers-contrast")):
            category = "user-preference"
        elif STATE.search(selector):
            category = "interaction-state"
        else:
            classes = set(CLASS.findall(selector))
            if not classes:
                category = "no-class"
            elif all(c in words for c in classes):
                category = "class-referenced"  # coverage 沒看到，但 class 還在模板／JS／程式裡：可能是沒爬到的情境
            else:
                category = "dead-candidate"   # 至少一個 class 在模板／JS／程式裡都找不到
        cats[category] += 1; cat_bytes[category] += size
        rows.append({"start": start, "bytes": size, "selector": " ".join(selector.split())[:200], "conditions": conditions,
                     "category": category, "routes": sorted(used_by.get(start, ()))})
    matched = sum(1 for row in rows if row["routes"])
    single = Counter(); single_bytes = Counter()
    for row in rows:
        if row["category"] == "used" and len(row["routes"]) == 1:
            single[prefix(row["selector"])] += 1; single_bytes[prefix(row["selector"])] += row["bytes"]
    pages = sorted(per_page.items(), key=lambda kv: -kv[1])
    summary = {
        "file_bytes": total_bytes, "rules": len(rows), "rule_bytes": sum(r["bytes"] for r in rows),
        "coverage_entries_matched": matched, "coverage_entries_total": len(used_by),
        "categories": {k: {"rules": cats[k], "kb": round(cat_bytes[k] / 1024, 1),
                           "pct_rules": round(cats[k] * 100 / len(rows), 1), "pct_bytes": round(cat_bytes[k] * 100 / total_bytes, 1)}
                       for k in cats},
        "pages_measured": len(per_page), "routes": len({r for row in rows for r in row["routes"]}),
        "rules_used_per_page": {"min": pages[-1][1] if pages else 0, "max": pages[0][1] if pages else 0,
                                "median": pages[len(pages) // 2][1] if pages else 0, "top": pages[:10], "bottom": pages[-5:]},
        "single_route_used": {"rules": sum(single.values()), "kb": round(sum(single_bytes.values()) / 1024, 1),
                              "top15": [(k, single[k], round(single_bytes[k] / 1024, 1)) for k, _ in single_bytes.most_common(15)]},
    }
    return rows, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--limit", type=int, default=260)
    parser.add_argument("--analyze-only", action="store_true", help="只用上次的 raw.json 重新分析")
    args = parser.parse_args()
    if args.analyze_only:
        raw = json.loads((ROOT / "tmp" / "ui-audit" / "raw.json").read_text(encoding="utf-8"))
        css_text, used_by, per_page = raw["css"], {int(k): set(v) for k, v in raw["used_by"].items()}, raw["per_page"]
    else:
        css_text, used_by, per_page = measure(args.limit, args.reuse)
    (ROOT / "tmp" / "ui-audit" / "raw.json").write_text(json.dumps({"css": css_text, "used_by": {k: sorted(v) for k, v in used_by.items()}, "per_page": per_page}, ensure_ascii=False), encoding="utf-8")
    rows, summary = analyze(css_text, used_by, per_page)
    out = ROOT / "tmp" / "ui-audit"
    (out / "coverage.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "coverage-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
