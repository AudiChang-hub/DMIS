"""日常與偶爾用的篇章截圖（T-197 第一批）。每段一個函式、各自寫到 static/help/screens/<篇名>/。

使用 seed_help_demo 的合成資料：示範車行丙 10 月 3 張（台數獎金已入帳）、示範客戶31（取消用）、示範客戶32（收款用），
以及 create_order／mainline 建好的王小明訂單（facts["create_order"]["order_pk"]）。
"""
from shots import ANNOTATE, CLEAR, TEXT, common_parent, leaf_text, mark, region, shot, viewport


def folder(out, name):
    path = out / name
    path.mkdir(parents=True, exist_ok=True)
    for old in path.glob("*.jpg"):
        old.unlink()
    return path


def order_pk(page, base, owner):
    """用全部訂單搜尋找到合成訂單的編號（不依賴資料庫順序）。"""
    page.goto(f"{base}/orders/?q={owner}", wait_until="networkidle")
    href = page.locator(f"a:has-text('{owner}')").first.get_attribute("href")
    return href.rstrip("/").split("/")[-1]


def section(page, title, tag):
    page.evaluate("([t,g])=>{const s=[...document.querySelectorAll('section')].find(x=>(x.querySelector('h2,h3')||{}).textContent?.includes(t)); if(!s) throw new Error('找不到區塊：'+t); s.setAttribute('data-help-shot',g)}",
                  [title, tag])
    return f"[data-help-shot={tag}]"


# ── 車行傭金與台數獎金 ─────────────────────────────────────────────
def dealer_payouts(page, base, out, assets, facts):
    out = folder(out, "dealer-payouts")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{base}/reports/dealer-payouts/", wait_until="networkidle")
    dealer = page.locator("select[name=dealer] option:has-text('示範車行丙')").first.get_attribute("value")
    page.goto(f"{base}/reports/dealer-payouts/?dealer={dealer}", wait_until="networkidle")
    page.wait_for_timeout(600)
    card = mark(page, "button:has-text('示範車行丙全部標記已給付')", "dealer-card", "section, article, details")
    text = page.evaluate(TEXT, "main")
    if "$6,000" not in text or "達 3 台門檻" not in text:
        raise RuntimeError("示範車行丙不是 $6,000／達 3 台門檻，說明範例要重算：" + text[:400])
    filters = mark(page, "select[name=dealer]", "payout-filters", "form")
    summary = leaf_text(page, "未給付金額", "payout-summary-title")
    page.evaluate("()=>{let x=document.querySelector('[data-help-shot=payout-summary-title]'); while(x && !/已給付金額/.test(x.innerText)) x=x.parentElement; x.setAttribute('data-help-shot','payout-summary')}")
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    viewport(page, out / "01-filter-summary.jpg", [{"sel": filters, "n": 1}, {"sel": "[data-help-shot=payout-summary]", "n": 2}], height=640)
    first_row = mark(page, f"{card} >> text=抵扣應收", "commission-tag")
    bonus = mark(page, "text=示範十月台數獎金", "bonus-name")
    shot(page, out / "02-dealer-card.jpg", [{"sel": card, "n": 3, "pad": 2}, {"sel": first_row, "n": 4}, {"sel": bonus, "n": 5}], margin=24, max_height=980)
    page.locator("text=逐單明細 3 張").first.click()
    page.wait_for_timeout(500)
    detail = mark(page, "text=逐單明細 3 張", "bonus-detail", "details, div[class]")
    shot(page, out / "03-bonus-detail.jpg", [{"sel": detail, "n": 6}], margin=30)
    # 標記台數獎金已給付（只做追蹤，不寫收支）
    toggle = page.evaluate("()=>{const row=document.querySelector('[data-help-shot=bonus-name]').closest('[class*=item], li, article, div'); let x=row; while(x && !x.querySelector('input[type=checkbox], button')) x=x.parentElement; const c=x.querySelector('label:has(input[type=checkbox]), button'); c.setAttribute('data-help-shot','bonus-toggle'); return c.textContent.trim()}")
    page.click("[data-help-shot=bonus-toggle]")
    page.wait_for_timeout(1500)
    confirm = page.locator("dialog[open] button.primary")
    if confirm.count():
        confirm.first.click()
        page.wait_for_timeout(1500)
    page.wait_for_load_state("networkidle")
    bonus = mark(page, "text=示範十月台數獎金", "bonus-name-paid")
    shot(page, out / "04-bonus-paid.jpg", [{"sel": bonus, "n": 7}], margin=90)
    paid = page.evaluate(TEXT, "main")
    return {"toggle": toggle, "after": paid[paid.find("已給付金額"):][:80]}


# ── 看營運總表 ────────────────────────────────────────────────────
def operations(page, base, out, assets, facts):
    out = folder(out, "operations")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{base}/operations/", wait_until="networkidle")
    page.wait_for_timeout(800)
    periods = mark(page, "a:has-text('上月'), button:has-text('上月')", "periods", "nav, div[class]")
    headline = mark(page, "text=有 5 件需要處理", "headline", "p") if page.locator("text=件需要處理").count() else None
    headline = mark(page, "text=件需要處理", "headline", "p")
    tiles = leaf_text(page, "領牌台數", "tile-first")
    page.evaluate("()=>{let x=document.querySelector('[data-help-shot=tile-first]'); while(x && !/車款成交額/.test(x.innerText)) x=x.parentElement; x.setAttribute('data-help-shot','tiles')}")
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    # 合成資料的淨利是負數，容易誤導：只截到前兩張卡片（台數與成交額）的寬度
    page.evaluate(ANNOTATE, [{"sel": periods, "n": 1}, {"sel": headline, "n": 2}])
    page.screenshot(path=str(out / "01-headline.jpg"), type="jpeg", quality=82, clip={"x": 280, "y": 70, "width": 1160, "height": 130})
    page.evaluate(CLEAR)
    # 合成資料的淨利是負數，容易誤導：只截前兩張卡片（領牌台數、車款成交額）
    box = page.evaluate("""()=>{const a=document.querySelector('[data-help-shot=tile-first]').closest('article, section, div[class*=kpi], div[class*=card], div[class*=tile]').getBoundingClientRect();
        const b=[...document.querySelectorAll('main *')].find(e=>e.children.length==0&&e.textContent.trim()=='車款成交額').closest('article, section, div[class*=kpi], div[class*=card], div[class*=tile]').getBoundingClientRect();
        return [a.left,a.top,b.right,Math.max(a.bottom,b.bottom)]}""")
    page.evaluate(ANNOTATE, [{"sel": "[data-help-shot=tile-first]", "n": 3, "pad": 4}])
    page.screenshot(path=str(out / "02-tiles.jpg"), type="jpeg", quality=82, clip={"x": box[0] - 20, "y": box[1] - 20, "width": box[2] - box[0] + 40, "height": box[3] - box[1] + 40})
    page.evaluate(CLEAR)
    attention = section(page, "需要處理", "attention")
    region(page, out / "03-attention.jpg", attention, [{"sel": attention, "n": 4, "pad": -4}], pad=20)
    return {"headline": page.evaluate(TEXT, headline)}


# ── 找一張訂單 ────────────────────────────────────────────────────
def find_order(page, base, out, assets, facts):
    out = folder(out, "find-order")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{base}/orders/?q=示範車行丙", wait_until="networkidle")
    page.wait_for_timeout(600)
    search = mark(page, "input[name=q]", "search", "form")
    leaf_text(page, "還沒交車的訂單", "tab-first")
    leaf_text(page, "含取消待退款與例外結案", "tab-last")
    tabs = common_parent(page, "[data-help-shot=tab-first]", "[data-help-shot=tab-last]", "tabs")
    shot(page, out / "01-search.jpg", [{"sel": search, "n": 1, "pad": 4}, {"sel": tabs, "n": 2}], margin=24, max_height=820)
    counts = page.evaluate(TEXT, tabs)[:160]
    sort_link = page.locator("thead a:has-text('領牌日'), thead button:has-text('領牌日')").first
    sort_link.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    bar = mark(page, "a:has-text('領牌日期：')", "sort-bar", "li, div[class]")
    head = mark(page, "thead", "table-head")
    shot(page, out / "02-sort.jpg", [{"sel": bar, "n": 3}, {"sel": head, "n": 4, "pad": 2}], margin=24, max_height=700)
    return {"tabs": counts}


def wang_pk(page, base, facts):
    return facts.get("create_order", {}).get("order_pk") or order_pk(page, base, "王小明")


# ── 一台車用多種付款＋接續草稿 ─────────────────────────────────────
def multi_payment(page, base, out, assets, facts):
    out_dir = folder(out, "multi-payment")
    drafts = folder(out, "drafts")
    page.set_viewport_size({"width": 1440, "height": 1400})
    page.goto(f"{base}/catalog/", wait_until="networkidle")
    page.locator("a:has-text('選這台接單')").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    amounts = page.locator(".payment-split input[type=number]")
    amounts.first.fill("20000")
    page.click("button:has-text('＋ 新增付款方式')")
    page.wait_for_timeout(400)
    page.locator("select.payment-split__method").nth(1).select_option("installment")
    page.wait_for_timeout(600)
    hint = amounts.nth(1).get_attribute("placeholder") or ""
    page.locator(".payment-split").first.evaluate("e=>e.setAttribute('data-help-shot','split-first')")
    page.locator(".payment-split").nth(1).evaluate("e=>e.setAttribute('data-help-shot','split-second')")
    rows = common_parent(page, "[data-help-shot=split-first]", "[data-help-shot=split-second]", "split-rows")
    add = mark(page, "button:has-text('＋ 新增付款方式')", "split-add")
    shot(page, out_dir / "01-two-rows.jpg", [{"sel": rows, "n": 1, "pad": 4}, {"sel": add, "n": 2}], margin=40, max_height=600)
    amounts.nth(1).fill("56000")
    page.select_option("#installment-period-choice", "24")
    page.wait_for_timeout(600)
    total = mark(page, "text=車價合計", "split-total", "div[class], p")
    shot(page, out_dir / "02-total.jpg", [{"sel": "[data-help-shot=split-second]", "n": 3, "pad": 4}, {"sel": total, "n": 4}], margin=30, max_height=700)
    with page.expect_navigation():
        page.click("button[name=_wizard_action][value=next]")
    page.wait_for_load_state("networkidle")
    # 草稿：中斷後從全部訂單接續
    page.goto(f"{base}/orders/", wait_until="networkidle")
    entry = mark(page, "text=未完成草稿 ·", "draft-entry", "section, div[class]")
    shot(page, drafts / "01-draft-entry.jpg", [{"sel": entry, "n": 1}], margin=24, max_height=500)
    page.locator("a:has-text('查看草稿'), button:has-text('查看草稿')").first.click()
    page.wait_for_timeout(800)
    resume = mark(page, "a:has-text('接續填單')", "resume")
    shot(page, drafts / "02-resume.jpg", [{"sel": resume, "n": 2}], margin=120, max_height=600)
    return {"hint_after_installment": hint}


# ── 讓客人簽訂購單 ────────────────────────────────────────────────
def sign(page, base, out, assets, facts):
    out = folder(out, "sign")
    page.set_viewport_size({"width": 1440, "height": 1000})
    pk = order_pk(page, base, "示範客戶32")
    page.goto(f"{base}/orders/{pk}/?tab=documents", wait_until="networkidle")
    page.wait_for_timeout(800)
    mobile = mark(page, "a:has-text('在行動裝置上簽名'), button:has-text('在行動裝置上簽名')", "sign-mobile")
    paper = mark(page, "button:has-text('選擇要印的聯別'), summary:has-text('選擇要印的聯別')", "sign-paper")
    shot(page, out / "01-choice.jpg", [{"sel": mobile, "n": 1}, {"sel": paper, "n": 2}], margin=60, max_height=700)
    page.click(mobile)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    docs = mark(page, "text=簽署這份文件", "sign-docs", "fieldset, section, div[class]")
    name = mark(page, "text=簽署人姓名", "signer", ".field, label, div[class]")
    pad = mark(page, "canvas", "pad")
    submit = mark(page, "button:has-text('確認簽署')", "sign-submit")
    shot(page, out / "02-documents.jpg", [{"sel": docs, "n": 3, "pad": 2}], margin=30, max_height=400)
    shot(page, out / "03-sign.jpg", [{"sel": name, "n": 4}, {"sel": pad, "n": 5}, {"sel": submit, "n": 6}], margin=30, max_height=900)
    return {}


# ── 建立後修改訂單 ────────────────────────────────────────────────
def edit_order(page, base, out, assets, facts):
    out = folder(out, "edit-order")
    page.set_viewport_size({"width": 1440, "height": 1000})
    pk = order_pk(page, base, "示範客戶32")
    page.goto(f"{base}/orders/{pk}/?tab=order", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.select_option("#id_plate_choice", "watch")
    page.wait_for_timeout(500)
    page.fill("#id_plate_selection_fee", "1200")
    page.fill("#id_watched_numbers", "6688、8866")
    page.locator("#id_watched_numbers").blur()
    page.wait_for_timeout(2500)
    status = mark(page, "text=已儲存", "saved", "span, div[class]")
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    viewport(page, out / "01-header-saved.jpg", [{"sel": status, "n": 1}], height=360)
    shot(page, out / "02-field.jpg", [{"sel": mark(page, "#id_plate_choice", "plate-choice", ".field"), "n": 2},
                                      {"sel": mark(page, "#id_plate_selection_fee", "plate-fee", ".field"), "n": 3},
                                      {"sel": mark(page, "#id_watched_numbers", "watched", ".field"), "n": 4}], margin=40, max_height=500)
    return {}


# ── 汰舊與補助（訂單頁） ──────────────────────────────────────────
def subsidy(page, base, out, assets, facts):
    out = folder(out, "subsidy")
    page.set_viewport_size({"width": 1440, "height": 1400})
    pk = order_pk(page, base, "示範客戶32")
    page.goto(f"{base}/orders/{pk}/?tab=subsidy", wait_until="networkidle")
    page.wait_for_timeout(800)
    add = mark(page, "button:has-text('＋ 新增補助項目')", "add-subsidy")
    page.click(add)
    page.wait_for_timeout(500)
    page.locator("[name$='-name']:visible, input[name*=subsidy][name$='name']:visible").last.evaluate("e=>(e.closest('.subsidy-item-row, tr, fieldset, .form-grid')||e.parentElement.parentElement).setAttribute('data-help-shot','new-item')")
    old = mark(page, "text=汰舊與舊車資料", "old-owner", "section, fieldset, div[class]")
    shot(page, out / "01-items.jpg", [{"sel": "[data-help-shot=new-item]", "n": 1}, {"sel": add, "n": 2}, {"sel": old, "n": 3}], margin=40, max_height=1100)
    return {}


# ── 收訂金與登記收款 ──────────────────────────────────────────────
def payments(page, base, out, assets, facts):
    out = folder(out, "payments")
    page.set_viewport_size({"width": 1440, "height": 1000})
    pk = order_pk(page, base, "示範客戶32")
    page.goto(f"{base}/orders/{pk}/?tab=finance", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.click("#add-payment")
    page.wait_for_timeout(500)
    row = page.locator("[data-payment-row]").last
    row.locator("[name$='item_name']").fill("分批匯款")
    row.locator("[name$='received_amount']").fill("1000")
    row.locator("[name$='received_on']").fill("2026-11-15")
    row.locator("[name$='payment_method']").select_option(label="匯款")
    page.wait_for_timeout(800)
    row.evaluate("e=>e.setAttribute('data-help-shot','new-row')")
    first = mark(page, "[data-payment-row]", "deposit-row")
    add = mark(page, "#add-payment", "add-payment")
    shot(page, out / "01-new-row.jpg", [{"sel": first, "n": 1, "pad": 2}, {"sel": "[data-help-shot=new-row]", "n": 2, "pad": 2}, {"sel": add, "n": 3}],
         margin=40, max_height=700)
    row.locator("input[type=checkbox][name$='-confirmed']").click()
    page.wait_for_timeout(800)
    dialog = page.locator("dialog[open]")
    found = dialog.count() > 0
    if found:
        box = dialog.first.bounding_box()
        button = mark(page, "dialog[open] button.primary", "confirm-lock")
        page.evaluate(ANNOTATE, [{"sel": button, "n": 4}])
        page.screenshot(path=str(out / "02-confirm.jpg"), type="jpeg", quality=82,
                        clip={"x": box["x"] - 24, "y": box["y"] - 24, "width": box["width"] + 48, "height": box["height"] + 48})
        page.evaluate(CLEAR)
        page.click(button)
        page.wait_for_timeout(1500)
    return {"dialog": found}


# ── 整理一張訂單的收支 ────────────────────────────────────────────
def order_finance(page, base, out, assets, facts):
    out = folder(out, "order-finance")
    page.set_viewport_size({"width": 1440, "height": 1200})
    pk = wang_pk(page, base, facts)
    page.goto(f"{base}/orders/{pk}/?tab=finance", wait_until="networkidle")
    page.wait_for_timeout(800)
    leaf_text(page, "收入合計", "sum-income")
    page.evaluate("()=>{let x=document.querySelector('[data-help-shot=sum-income]'); while(x && !/支出合計/.test(x.innerText)) x=x.parentElement; x.setAttribute('data-help-shot','summary-box')}")
    shot(page, out / "01-summary.jpg", [{"sel": "[data-help-shot=summary-box]", "n": 1}], margin=30, max_height=500)
    income = mark(page, "text=領牌稅金收入", "income-row", "div[class], tr, li")
    expense = mark(page, "text=傭金支出（車行／本店人員）", "expense-row", "div[class], tr, li")
    shot(page, out / "02-ledger.jpg", [{"sel": income, "n": 2}, {"sel": expense, "n": 3}], margin=40, max_height=1150)
    return {"summary": page.evaluate(TEXT, "[data-help-shot=summary-box]")[:200]}


# ── 取消、退款與沒收 ──────────────────────────────────────────────
def cancel(page, base, out, assets, facts):
    out = folder(out, "cancel")
    page.set_viewport_size({"width": 1440, "height": 1200})
    pk = order_pk(page, base, "示範客戶31")
    page.goto(f"{base}/orders/{pk}/?tab=closing", wait_until="networkidle")
    page.wait_for_timeout(800)
    if not page.locator("button:has-text('確認結算並完成取消')").count():
        page.locator("text=展開取消流程").first.click()
        page.wait_for_timeout(500)
        submit = mark(page, "button:has-text('登記取消訂單')", "cancel-submit")
        shot(page, out / "01-start.jpg", [{"sel": submit, "n": 1}], margin=200, max_height=600)
        page.click(submit)
        page.wait_for_timeout(800)
        confirm = page.locator("dialog[open] button.danger, dialog[open] button.primary")
        if confirm.count():
            confirm.first.click()
        page.wait_for_timeout(2000)
        page.goto(f"{base}/orders/{pk}/?tab=closing", wait_until="networkidle")
        page.wait_for_timeout(800)
    settle = mark(page, "button:has-text('確認結算並完成取消')", "settle-submit")
    forfeit = mark(page, "[name=forfeited_amount]", "forfeit", ".field, label, div[class]")
    page.fill("[name=forfeited_amount]", "1000")
    page.locator("[data-help-shot=settle-submit]").evaluate("b=>b.closest('form').querySelectorAll('input[type=date]').forEach(i=>{if(!i.value) i.value='2026-11-17'})")
    page.locator("[data-help-shot=settle-submit]").evaluate("b=>b.closest('form').querySelectorAll('select').forEach(s=>{if(!s.value && s.options.length>1) s.selectedIndex=1})")
    page.wait_for_timeout(400)
    shot(page, out / "02-settle.jpg", [{"sel": forfeit, "n": 2}, {"sel": settle, "n": 3}], margin=60, max_height=900)
    text = page.evaluate(TEXT, "main")
    page.click(settle)
    page.wait_for_timeout(800)
    confirm = page.locator("dialog[open] button.danger, dialog[open] button.primary")
    if confirm.count():
        confirm.first.click()
    page.wait_for_timeout(2000)
    page.goto(f"{base}/orders/{pk}/", wait_until="networkidle")
    page.screenshot(path=str(out / "03-cancelled.jpg"), type="jpeg", quality=82, clip={"x": 0, "y": 0, "width": 1440, "height": 420})
    after = page.evaluate(TEXT, "main")[:200]
    return {"settle": text[text.find("取消待退款"):][:300], "after": after}


PARTS = (dealer_payouts, operations, find_order, multi_payment, sign, edit_order, subsidy, payments, order_finance, cancel)


def run(page, base, out, assets, facts):
    """run.py 呼叫：out 是 static/help/screens，各段自己建資料夾。"""
    return {part.__name__: part(page, base, out, assets, facts) for part in PARTS}
