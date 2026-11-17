"""偶爾用的後台工作與「設定與管理」篇章截圖（T-197 第二批）。每段寫到 static/help/screens/<篇名>/。

在 seed_help_demo --manage 之後執行。會實際操作的只有：王小明的撥款入帳、快速進車 3 台（DEMOE00051～53）、
審核刪除示範客戶33、價格表分工、建立「示範春節送禮」、上傳示範進貨表；其餘只填表不送出。全部都是合成資料。
"""
import io

from shots import TEXT, common_parent, mark, shot, viewport
from scenarios.topics import folder, order_pk


def wide(page, height=1100):
    page.set_viewport_size({"width": 1440, "height": height})


def expect(page, text, where="main"):
    body = page.evaluate(TEXT, where)
    if text not in body:
        raise RuntimeError(f"畫面上找不到「{text}」，說明要一起改：{body[:300]}")
    return body


# ── 分期與平台撥款對帳 ───────────────────────────────────────────
def reconciliation(page, base, out, assets, facts):
    out = folder(out, "reconciliation")
    wide(page)
    url = f"{base}/operations/reconciliation/?q=王小明"
    page.goto(url, wait_until="networkidle")
    row = ".reconciliation-row:not(.is-posted)"
    expect(page, "$69,920")
    page.fill(f"{row} [data-actual-input]", "69920")
    page.wait_for_timeout(300)
    actual = mark(page, f"{row} [data-actual-input]", "rec-actual", "td")
    button = mark(page, f"{row} .inventory-row-action button[type=submit]", "rec-post")
    shot(page, out / "01-pending.jpg", [{"sel": "form.operations-filters", "n": 1}, {"sel": f"{row} .reconciliation-expected", "n": 2},
                                        {"sel": actual, "n": 3}, {"sel": button, "n": 3}], margin=30)
    with page.expect_navigation():
        page.click(button)
    page.wait_for_load_state("networkidle")
    message = expect(page, "實際入帳 69,920 元")
    page.goto(url, wait_until="networkidle")
    posted = ".reconciliation-row.is-posted"
    shot(page, out / "02-posted.jpg", [{"sel": f"{posted} .reconciliation-difference", "n": 4},
                                       {"sel": f"{posted} form[action*=unconfirm] button", "n": 5}], margin=40)
    return {"message": message[message.find("已登記"):][:60]}


# ── 進車、調車與現有台數 ─────────────────────────────────────────
def inventory(page, base, out, assets, facts):
    out = folder(out, "inventory")
    wide(page, 1200)
    page.goto(f"{base}/data/inventory/quick-entry/", wait_until="networkidle")
    cars = (("DEMOE00051", "珍珠白", "202609"), ("DEMOE00052", "珍珠白", "202609"), ("DEMOE00053", "消光黑", "202607"))
    model = page.locator("select[name='vehicles-0-vehicle_model'] option", has_text="SUI 1").first.get_attribute("value")
    for i, (engine, color, made) in enumerate(cars):
        page.select_option(f"select[name='vehicles-{i}-vehicle_model']", model)
        page.wait_for_timeout(300)
        page.select_option(f"select[name='vehicles-{i}-color']", label=color)
        page.fill(f"input[name='vehicles-{i}-identifier']", engine)
        page.fill(f"input[name='vehicles-{i}-manufactured_year_month']", made)
        page.select_option(f"select[name='vehicles-{i}-acquisition_type']", "company")
    page.evaluate("document.activeElement.blur()")
    rows = common_parent(page, "select[name='vehicles-0-vehicle_model']", "select[name='vehicles-2-vehicle_model']", "quick-rows")
    first = mark(page, "select[name='vehicles-0-vehicle_model']", "quick-row-0", ".quick-entry-row")
    source = mark(page, "select[name='vehicles-0-acquisition_type']", "quick-source", "label, .field, div")
    submit = mark(page, "button:has-text('建立全部車輛')", "quick-submit")
    shot(page, out / "01-quick-entry.jpg", [{"sel": first, "n": 1}, {"sel": source, "n": 2}, {"sel": submit, "n": 3}], margin=30, max_height=1100)
    del rows
    with page.expect_navigation():
        page.click(submit)
    page.wait_for_load_state("networkidle")
    created = expect(page, "共建立 3 台車輛")
    page.goto(f"{base}/data/inventory/?q=DEMOE0005", wait_until="networkidle")
    toggle = mark(page, ".inventory-priority-toggle", "priority")
    shot(page, out / "02-list.jpg", [{"sel": ".inventory-filters", "n": 4}, {"sel": toggle, "n": 5}], margin=30, max_height=900)
    page.goto(f"{base}/data/inventory/stock-count/", wait_until="networkidle")
    export = mark(page, "main :is(a,button):has-text('匯出 Excel')", "stock-export")
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    viewport(page, out / "03-stock-count.jpg", [{"sel": export, "n": 6}], height=760)
    return {"created": created[created.find("已完成"):][:40]}


# ── 刪除訂單與還原 ───────────────────────────────────────────────
def order_deletion(page, base, out, assets, facts):
    out = folder(out, "order-deletion")
    wide(page, 1000)
    page.goto(f"{base}/orders/deletion-review/", wait_until="networkidle")
    expect(page, "示範客戶33")
    review = mark(page, "main :is(a,button):has-text('檢查與審核')", "review-button")
    shot(page, out / "01-queue.jpg", [{"sel": ".deletion-review-impacts", "n": 1}, {"sel": review, "n": 2}], margin=40, max_height=700)
    with page.expect_navigation():
        page.click(review)
    page.wait_for_load_state("networkidle")
    confirm = mark(page, "main button:has-text('確認刪除訂單')", "delete-confirm", "form .form-actions, .form-actions, form")
    shot(page, out / "02-review.jpg", [{"sel": confirm, "n": 3}], margin=60, max_height=900)
    page.locator("main input[type=checkbox]").evaluate_all("els=>els.forEach(e=>{if(!e.checked) e.click()})")
    with page.expect_navigation():
        page.click("main button:has-text('確認刪除訂單')")
    page.wait_for_load_state("networkidle")
    page.goto(f"{base}/orders/deleted/", wait_until="networkidle")
    expect(page, "示範客戶33")
    restore = mark(page, "main :is(a,button):has-text('檢視與還原')", "restore")
    shot(page, out / "03-recycle.jpg", [{"sel": restore, "n": 4}], margin=40, max_height=600)
    return {}


# ── 下單改價、贈品與自訂分期 ─────────────────────────────────────
def order_pricing(page, base, out, assets, facts):
    out = folder(out, "order-pricing")
    wide(page, 1400)
    page.goto(f"{base}/catalog/", wait_until="networkidle")
    page.locator("a:has-text('選這台接單')").first.click()
    page.wait_for_load_state("networkidle")
    page.locator("select.payment-split__method").first.select_option("installment")
    page.wait_for_timeout(400)
    page.click("#installment-manual-toggle")
    page.wait_for_timeout(300)
    page.fill("#id_installment_company", "示範租賃")
    page.fill("#id_installment_periods", "30")
    page.fill("#id_installment_opening_fee", "2000")
    page.locator("#id_installment_periods").dispatch_event("input")
    page.wait_for_timeout(400)
    monthly = page.input_value("#id_installment_monthly")
    if monthly != "2533":
        raise RuntimeError(f"自訂分期每期帶入 {monthly}，範例寫 2,533 要重算")
    page.evaluate("document.activeElement.blur()")
    fields = common_parent(page, "#id_installment_company", "#id_installment_opening_fee", "custom-fields")
    shot(page, out / "01-custom-installment.jpg", [{"sel": "#installment-manual-toggle", "n": 1}, {"sel": fields, "n": 2},
                                                    {"sel": "#id_installment_monthly", "n": 3}], margin=40, max_height=900)
    return {"monthly": monthly}


# ── 價格表分發與年節送禮 ─────────────────────────────────────────
def price_list(page, base, out, assets, facts):
    out = folder(out, "price-list")
    wide(page, 1100)
    page.goto(f"{base}/data/price-list-distribution/?owner=all", wait_until="networkidle")
    expect(page, "示範車行丙")
    check = mark(page, ".price-distribution-check", "pl-check")
    shot(page, out / "01-distribution.jpg", [{"sel": ".price-distribution-progress", "n": 1}, {"sel": "#distribution-owner", "n": 2},
                                             {"sel": check, "n": 3}], margin=30, max_height=1000)
    page.goto(f"{base}/data/price-list-distribution/", wait_until="networkidle")
    page.click("main a:has-text('分配與排序')")
    page.wait_for_load_state("networkidle")
    for name in ("示範車行甲", "示範車行乙"):
        page.locator(f"main label:has-text('{name}') input[type=checkbox], main tr:has-text('{name}') input[type=checkbox]").first.check()
    page.select_option("[data-selected-assignee]", label="示範業務")
    page.wait_for_timeout(300)
    assign = mark(page, "[data-assign-selected]", "assign", ".price-assignment-bulk, form > div, div")
    shot(page, out / "02-assign.jpg", [{"sel": ".price-assignment-status", "n": 4}, {"sel": "[data-assign-selected]", "n": 4}], margin=30, max_height=1000)
    del assign
    with page.expect_navigation():
        page.click("[data-assign-selected]")
    page.wait_for_load_state("networkidle")
    page.goto(f"{base}/data/gift-distribution/", wait_until="networkidle")
    page.fill("input[name=title]", "示範春節送禮")
    page.fill("input[name=scheduled_on]", "2027-02-01")
    page.check("input[name=include_holiday_dealers]")
    with page.expect_navigation():
        page.click("main button:has-text('建立活動')")
    page.wait_for_load_state("networkidle")
    expect(page, "示範車行丙")
    page.evaluate("document.querySelectorAll('.messages, .toast, [data-toast], .flash-messages').forEach(e=>e.remove())")
    table = mark(page, "main :is(button):has-text('標記完成')", "gift-table", "table, ul, section")
    shot(page, out / "03-gift.jpg", [{"sel": table, "n": 5}], margin=30, max_height=900)
    return {}


# ── 機種、售價與年式 ─────────────────────────────────────────────
def vehicle_models(page, base, out, assets, facts):
    out = folder(out, "vehicle-models")
    wide(page, 1100)
    page.goto(f"{base}/data/vehicle-models/", wait_until="networkidle")
    href = page.evaluate("""()=>{const a=[...document.querySelectorAll('main a[href*="/vehicle-models/"][href$="/edit/"]')].find(x=>{
        let p=x; for(let i=0;i<6&&p;i++){ if(p.textContent.includes('SUI 125')) return true; p=p.parentElement } return false});
        if(!a) throw new Error('找不到 SUI 125 的編輯連結'); return a.getAttribute('href')}""")
    page.goto(base + href, wait_until="networkidle")
    workspace = page.url.rstrip("/").rsplit("/", 1)[0]
    viewport(page, out / "01-workspace.jpg", [{"sel": ".model-workspace-tabs", "n": 1}, {"sel": ".model-workspace-actions", "n": 2}],
             height=560)
    page.goto(f"{workspace}/prices/?new=1", wait_until="networkidle")  # 等於按「＋ 新增版本」
    page.wait_for_timeout(400)
    note = ".model-prefill-note"
    if not page.locator(note).count():
        raise RuntimeError("新增售價版本沒有「已帶入…」提示")
    date_input = mark(page, "main input[type=date]", "price-date", "form")
    shot(page, out / "02-price.jpg", [{"sel": note, "n": 3}, {"sel": date_input, "n": 4}], margin=30, max_height=1000)
    page.goto(f"{base}/data/vehicle-models/batch/", wait_until="networkidle")
    shot(page, out / "03-batch.jpg", [{"sel": ".model-batch-toolbar", "n": 5}], margin=30, max_height=800)
    return {}


# ── 配件與工資 ───────────────────────────────────────────────────
def accessories(page, base, out, assets, facts):
    out = folder(out, "accessories")
    wide(page, 1000)
    page.goto(f"{base}/data/accessories/", wait_until="networkidle")
    expect(page, "示範後箱")
    tabs = mark(page, "main a:has-text('安全配件')", "acc-tab", "nav, [role=tablist], div")
    mark(page, "main a:has-text('批次修改')", "acc-batch")
    mark(page, "main a:has-text('＋ 新增配件')", "acc-add")
    actions = common_parent(page, "[data-help-shot=acc-batch]", "[data-help-shot=acc-add]", "acc-actions")
    shot(page, out / "01-list.jpg", [{"sel": tabs, "n": 1}, {"sel": actions, "n": 2}], margin=30, max_height=800)
    return {}


# ── 選車展示與車色圖片 ───────────────────────────────────────────
def catalog_photos(page, base, out, assets, facts):
    out = folder(out, "catalog-photos")
    wide(page, 1100)
    page.goto(f"{base}/data/catalog/photos/", wait_until="networkidle")
    missing = mark(page, ".photo-cell[data-has-photo='0']", "missing-cell")
    shot(page, out / "01-board.jpg", [{"sel": ".photo-board__meter", "n": 1}, {"sel": "[data-photo-missing-only]", "n": 2},
                                      {"sel": missing, "n": 3}], margin=30, max_height=900)
    page.goto(f"{base}/data/catalog/1/", wait_until="networkidle")
    switch = mark(page, ".image-source-switch", "image-switch")
    card = mark(page, ".image-source-switch", "image-card", "section, fieldset, article")
    shot(page, out / "02-edit.jpg", [{"sel": card, "n": 4, "pad": 2}], margin=30, max_height=900)
    del switch
    return {}


# ── 原廠車型比對 ─────────────────────────────────────────────────
def official_catalog(page, base, out, assets, facts):
    out = folder(out, "official-catalog")
    wide(page, 1000)
    page.goto(f"{base}/data/catalog/official/?brand=sym&tab=pending", wait_until="networkidle")
    expect(page, "示範 Jet SR")
    shot(page, out / "01-pending.jpg", [{"sel": ".official-brand-tabs", "n": 1}, {"sel": ".official-tabs", "n": 1},
                                        {"sel": ".official-row__form", "n": 2}], margin=30, max_height=900)
    return {}


# ── 原廠獎勵與補助方案 ─────────────────────────────────
def incentives(page, base, out, assets, facts):
    out = folder(out, "incentives")
    wide(page, 1300)
    page.goto(f"{base}/data/incentive-campaigns/new/", wait_until="networkidle")
    page.fill("main input[name=name]", "示範十一月加碼")
    shot(page, out / "01-campaign.jpg", [{"sel": "[data-campaign-items]", "n": 1}, {"sel": ".campaign-chips", "n": 2}],
         margin=30, max_height=1200)
    page.goto(f"{base}/data/subsidy-programs/", wait_until="networkidle")
    add = mark(page, "main :is(a,button,summary):has-text('＋ 新增補助方案')", "subsidy-add")
    shot(page, out / "02-subsidy.jpg", [{"sel": add, "n": 3}, {"sel": ".installment-company-table", "n": 3}], margin=30, max_height=800)
    return {}


# ── 分期方案、領牌費用與假日 ─────────────────────────────────────
def installment_rules(page, base, out, assets, facts):
    out = folder(out, "installment-rules")
    wide(page, 1100)
    page.goto(f"{base}/data/vehicle-models/1/installment-plans/?new=1#plan-form", wait_until="networkidle")  # 等於按「＋ 新增版本」
    row = mark(page, ".installment-option-row", "plan-row")
    page.evaluate("""()=>{const row=document.querySelector('[data-help-shot=plan-row]');
        const s=[...row.querySelectorAll('select')].find(x=>[...x.options].some(o=>o.text.includes('按比例')));
        if(!s) throw new Error('找不到預估撥款方式'); (s.closest('label, .field')||s).setAttribute('data-help-shot','plan-method')}""")
    rate = "[data-help-shot=plan-method]"
    shot(page, out / "01-plan.jpg", [{"sel": row, "n": 1}, {"sel": rate, "n": 2}], margin=60, max_height=900)
    page.goto(f"{base}/data/registration-fee-rules/", wait_until="networkidle")
    card = mark(page, ".registration-rule-card", "rule-card")
    shot(page, out / "02-registration.jpg", [{"sel": card, "n": 3}], margin=30, max_height=800)
    page.goto(f"{base}/data/business-holidays/", wait_until="networkidle")
    viewport(page, out / "03-holiday.jpg", [{"sel": ".holiday-view-switch", "n": 4}, {"sel": ".holiday-sync-status", "n": 4}],
             height=900)
    return {}


# ── 車行、網路平台與本店人員 ─────────────────────────────────────
def sales_sources(page, base, out, assets, facts):
    out = folder(out, "sales-sources")
    wide(page, 1100)
    page.goto(f"{base}/data/channels/", wait_until="networkidle")
    add = mark(page, "main a[href*='kind=dealer']", "dealer-add")
    viewport(page, out / "01-list.jpg", [{"sel": ".sales-source-filters", "n": 1}, {"sel": add, "n": 2},
                                         {"sel": ".source-status-switch", "n": 3}], height=1000)
    page.goto(f"{base}/data/channels/", wait_until="networkidle")
    page.locator("main a:has-text('編輯資料')").first.click()
    page.wait_for_load_state("networkidle")
    page.evaluate("document.querySelectorAll('.dealer-brand-details').forEach(d=>d.open=true)")
    shot(page, out / "02-edit.jpg", [{"sel": "#brand-policies .dealer-cooperation-profile-grid", "n": 4},
                                     {"sel": ".dealer-brand-details > summary", "n": 5}], margin=30, max_height=1050)
    page.goto(f"{base}/data/staff/", wait_until="networkidle")
    expect(page, "示範業務")
    shot(page, out / "03-staff.jpg", [{"sel": ".staff-source-table", "n": 6}], margin=30, max_height=600)
    return {}


# ── 車行傭金、獎勵活動與台數獎金設定 ─────────────────────────────
def dealer_rules(page, base, out, assets, facts):
    out = folder(out, "dealer-rules")
    wide(page, 1000)
    page.goto(f"{base}/data/dealer-volume-bonuses/", wait_until="networkidle")
    expect(page, "示範十月台數獎金")
    add = mark(page, "main :is(a,button):has-text('＋ 新增規則')", "bonus-add")
    shot(page, out / "01-list.jpg", [{"sel": ".dealer-reward-tabs", "n": 1}, {"sel": add, "n": 2}], margin=30, max_height=800)
    wide(page, 1400)
    page.goto(f"{base}/data/dealer-volume-bonuses/new/", wait_until="networkidle")
    page.fill("input[name=name]", "示範十月台數獎金（範例）")
    page.check("input[name=period_type][value=month]")
    page.fill("input[name=period_year]", "2026")
    page.locator("input[name=period_months]").evaluate_all("els=>els.forEach(e=>{if(e.checked!==(e.value==='10')) e.click()})")
    page.fill("input[name='tiers-0-minimum_quantity']", "3")
    page.fill("input[name='tiers-0-bonus_per_vehicle']", "500")
    page.evaluate("document.activeElement.blur()")
    shot(page, out / "02-form.jpg", [{"sel": ".bonus-period-type", "n": 3}, {"sel": "[data-bonus-tiers]", "n": 4}],
         margin=40, max_height=1300)
    return {}


# ── 帳號與權限 ───────────────────────────────────────────────────
def accounts(page, base, out, assets, facts):
    out = folder(out, "accounts")
    wide(page, 1000)
    page.goto(f"{base}/system/users/", wait_until="networkidle")
    expect(page, "示範業務")
    add = mark(page, "main :is(a,button):has-text('＋ 建立內部帳號')", "user-add")
    page.evaluate("""()=>{const p=[...document.querySelectorAll('main p')].find(x=>x.textContent.trim()==='@demo.sales');
        if(!p) throw new Error('找不到示範業務'); const row=p.closest('article, li, tr, [class*=account-card], [class*=account-row]')||p.parentElement.parentElement;
        const actions=row.querySelector('.account-actions')||row; actions.setAttribute('data-help-shot','sales-actions')}""")
    wide(page, 1300)
    viewport(page, out / "01-users.jpg", [{"sel": add, "n": 1}, {"sel": "[data-help-shot=sales-actions]", "n": 2}], height=1300)
    href = page.evaluate("""()=>{const a=[...document.querySelectorAll('main a[href*="/permissions/"]')].find(x=>
        (x.closest('tr, li, article')||x).textContent.includes('demo.sales'));
        if(!a) throw new Error('找不到示範業務的權限連結'); return a.getAttribute('href')}""")
    user_url = base + href.split("?")[0]
    page.goto(f"{user_url}?tab=features", wait_until="networkidle")
    tools = mark(page, "main button:has-text('複製並預覽')", "copy-tools", ".access-tools")
    shot(page, out / "02-features.jpg", [{"sel": ".permission-tabs", "n": 3}, {"sel": tools, "n": 4}], margin=30, max_height=900)
    page.goto(f"{user_url}?tab=scope", wait_until="networkidle")
    page.select_option("select[name=order_scope]", "own")
    scope_box = mark(page, "select[name=order_scope]", "scope-field", ".field, label, div")
    shot(page, out / "03-scope.jpg", [{"sel": scope_box, "n": 5}], margin=60, max_height=800)
    return {}


# ── 建立與修改報表 ───────────────────────────────────────────────
def report_design(page, base, out, assets, facts):
    out = folder(out, "report-design")
    wide(page, 1000)
    page.goto(f"{base}/data/report-design/", wait_until="networkidle")
    page.click("main button:has-text('＋ 新增報表')")
    page.wait_for_timeout(500)
    viewport(page, out / "01-starters.jpg", [{"sel": ".catalog-starters", "n": 1}])
    page.goto(f"{base}/data/report-design/new/?start=channel", wait_until="networkidle")
    page.wait_for_timeout(800)
    viewport(page, out / "02-designer.jpg", [{"sel": ".report-property-panel", "n": 2}, {"sel": ".report-savebar", "n": 3}])
    return {}


# ── 列印範本與公司抬頭 ───────────────────────────────────────────
def print_templates(page, base, out, assets, facts):
    out = folder(out, "print-templates")
    wide(page, 1300)
    page.goto(f"{base}/data/print-templates/new/", wait_until="networkidle")
    page.fill("input[name=name]", "示範報件單")
    page.select_option("select[name=document_type]", "submission")
    page.select_option("select[name='print_fields-0-field_key']", "owner_name")
    page.fill("input[name='print_fields-0-x_mm']", "30")
    page.fill("input[name='print_fields-0-y_mm']", "52")
    page.fill("input[name='print_fields-0-font_size']", "12")
    page.evaluate("document.activeElement.blur()")
    shot(page, out / "01-form.jpg", [{"sel": ".positioned-field-row", "n": 1}, {"sel": ".sticky-form-actions", "n": 2}],
         margin=30, max_height=1200)
    page.goto(f"{base}/data/print-companies/", wait_until="networkidle")
    shot(page, out / "02-company.jpg", [{"sel": ".company-preview", "n": 3}], margin=40, max_height=900)
    return {}


# ── 舊資料 Excel 匯入 ────────────────────────────────────────────
def demo_purchase_book():
    """合成的進貨表：2 台對得上 SUI 125（型號 SUI125），1 台型號 DEMO-X 系統裡沒有。"""
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "進貨"
    sheet.append(["車種型號", "車身號碼", "進貨日期", "顏色", "數量", "出廠日期"])
    for model, engine, color in (("SUI125", "DEMOE00061", "珍珠白"), ("SUI125", "DEMOE00062", "消光黑"), ("DEMO-X", "DEMOE00063", "亮白")):
        sheet.append([model, engine, "2026/10/05", color, 1, "2026/09"])
    data = io.BytesIO()
    book.save(data)
    return data.getvalue()


def import_data(page, base, out, assets, facts):
    out = folder(out, "import")
    wide(page, 1100)
    page.goto(f"{base}/data/imports/", wait_until="networkidle")
    page.select_option("select[name=import_type]", "operations")
    page.wait_for_timeout(300)
    page.set_input_files("input[name=source_file]", files=[{"name": "示範進貨表.xlsx", "buffer": demo_purchase_book(),
                                                             "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}])
    page.locator("input[name=sheets]").evaluate_all("els=>els.forEach(e=>{e.checked=e.parentElement.textContent.includes('進貨')})")
    shot(page, out / "01-upload.jpg", [{"sel": ".import-upload-form", "n": 1}], margin=30, max_height=900)
    with page.expect_navigation():
        page.click("main button:has-text('上傳並開始檢查')")
    page.wait_for_load_state("networkidle")
    for _ in range(20):
        if page.locator(".import-status-tabs").count():
            break
        page.wait_for_timeout(1000)
        page.reload(wait_until="networkidle")
    body = page.evaluate(TEXT, "main")
    shot(page, out / "02-detail.jpg", [{"sel": ".import-status-tabs", "n": 2}, {"sel": ".import-hero-actions", "n": 3}],
         margin=30, max_height=1000)
    return {"detail": body[:200]}


# ── 系統狀態、公告與說明文字 ─────────────────────────────────────
def system(page, base, out, assets, facts):
    out = folder(out, "system")
    wide(page, 1000)
    page.goto(f"{base}/system-status/", wait_until="networkidle")
    shot(page, out / "01-status.jpg", [{"sel": ".system-status-grid", "n": 1}], margin=30, max_height=900)
    page.goto(f"{base}/system/announcements/", wait_until="networkidle")
    shot(page, out / "02-announcement.jpg", [{"sel": "#announcement-editor", "n": 2}], margin=30, max_height=1000)
    page.goto(f"{base}/system/text/", wait_until="networkidle")
    edit = mark(page, "main :is(a,button):has-text('編輯')", "copy-edit")
    shot(page, out / "03-site-copy.jpg", [{"sel": ".copy-tabs", "n": 3}, {"sel": edit, "n": 3}], margin=30, max_height=800)
    return {}


# ── 系統清空後重建資料 ───────────────────────────────────────────
def rebuild(page, base, out, assets, facts):
    out = folder(out, "rebuild")
    wide(page, 1000)
    page.goto(f"{base}/data/", wait_until="networkidle")
    brand = mark(page, "main a.maintenance-card:has-text('車輛品牌')", "brand-card", "section")
    shot(page, out / "01-maintenance.jpg", [{"sel": brand, "n": 1}], margin=30, max_height=900)
    return {}


PARTS = (reconciliation, inventory, order_deletion, order_pricing, price_list, vehicle_models, accessories, catalog_photos,
         official_catalog, incentives, installment_rules, sales_sources, dealer_rules, accounts, report_design,
         print_templates, import_data, system, rebuild)


def run(page, base, out, assets, facts):
    return {part.__name__: part(page, base, out, assets, facts) for part in PARTS}
