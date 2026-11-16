"""〈報表中心：查一段期間的車行排行〉：2026/09/01～11/30，車行第一名示範車行丙 4 張。"""
from shots import ANNOTATE, CLEAR, TEXT, mark, shot


def run(page, base, out, assets, facts):
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{base}/reports/", wait_until="networkidle")
    # 左側「報表頁面」預設收合，直接開這份報表的網址（說明文字照實寫「從報表頁面選」）
    page.goto(base + page.locator("a:has-text('通路與車行銷售')").first.get_attribute("href"), wait_until="networkidle")
    page.wait_for_timeout(1000)
    rail = mark(page, "text=報表頁面", "rail", "button, a, aside")
    page.fill("#id_start", "2026-09-01")
    page.fill("#id_end", "2026-11-30")
    filters = mark(page, "#id_start", "filters", "form")
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    page.evaluate(ANNOTATE, [{"sel": rail, "n": 1}, {"sel": filters, "n": 2}])
    page.screenshot(path=str(out / "01-open-filter.jpg"), type="jpeg", quality=82, clip={"x": 0, "y": 0, "width": 1440, "height": 560})
    page.evaluate(CLEAR)
    page.locator("#id_start").dispatch_event("change")
    page.wait_for_timeout(1500)
    page.locator("#id_end").dispatch_event("change")
    page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle")

    ranking = "#chart-1"
    shot(page, out / "02-ranking.jpg", [{"sel": ranking, "n": 3}], margin=20)
    result = {"ranking": page.evaluate(TEXT, ranking)[:300]}
    if "共 23 張訂單" not in result["ranking"]:
        raise RuntimeError("這段期間不是 23 張，說明範例要重寫：" + result["ranking"])
    bar = page.locator(f"{ranking} .report-bar-track[aria-label^='示範車行丙']").first
    if "示範車行丙：4" not in (bar.get_attribute("aria-label") or ""):
        raise RuntimeError("示範車行丙不是 4 張，說明範例要重寫：" + (bar.get_attribute("aria-label") or ""))
    bar.click()
    page.wait_for_timeout(1800)
    page.wait_for_load_state("networkidle")
    shot(page, out / "04-crossfilter.jpg", [{"sel": "#chart-0", "n": 5}, {"sel": f"{ranking} [aria-pressed=true]", "n": 4}], margin=24)
    chip = mark(page, "text=圖表與表格已同步更新", "chip", "div[class]")
    shot(page, out / "05-filter-chip.jpg", [{"sel": chip, "n": 6}], margin=30)
    source = mark(page, "#chart-0 a:has-text('查看來源訂單')", "source-link")
    page.click(source)
    page.wait_for_timeout(2000)
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(out / "07-source-orders.jpg"), type="jpeg", quality=82)
    return result
