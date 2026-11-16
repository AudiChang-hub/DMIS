"""〈建立訂單〉：王小明買 SUI 125 消光黑、分期 24 期、指定號碼、加購後箱、訂金 3,000。"""
import re

from shots import TEXT, common_parent, leaf_text, mark, region, shot

SECTION = "details, fieldset, section"


def next_step(page):
    """按「下一步」並等網址換到下一個步驟（頁面可能還在自動存草稿，不能只等第一次換頁）。"""
    before = page.url.split("step=")[-1]
    page.click("button[name=_wizard_action][value=next]")
    try:
        page.wait_for_url(lambda url: "step=" in url and url.split("step=")[-1] != before, timeout=20000)
    except Exception:
        page.wait_for_load_state("networkidle")
        raise RuntimeError("停在原步驟：" + page.evaluate(TEXT, "main")[:400])
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def run(page, base, out, assets, facts):
    page.goto(f"{base}/catalog/", wait_until="networkidle")
    card = mark(page, "a:has-text('選這台接單')", "card", "article, li, .catalog-color-card, .catalog-card")
    button = mark(page, "a:has-text('選這台接單')", "pick")
    region(page, out / "01-catalog.jpg", card, [{"sel": button, "n": 1}], pad=24)
    page.click(button)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # 第 1 步：車款與車價（分期單牌險費留空＝不向客人收）
    page.locator("select.payment-split__method").first.select_option("installment")
    page.wait_for_timeout(400)
    page.select_option("#installment-period-choice", "24")
    page.wait_for_timeout(400)
    pay = mark(page, "select.payment-split__method", "pay", ".payment-split")
    plan = mark(page, "#installment-company-choice", "plan", "div[class*=installment]")
    plate = mark(page, "#id_plate_insurance_fee", "plate", ".field")
    section = mark(page, "select.payment-split__method", "pay-section", SECTION)
    region(page, out / "03-payment.jpg", section, [{"sel": pay, "n": 2}, {"sel": plan, "n": 3}, {"sel": plate, "n": 4}])
    next_step(page)

    # 第 2 步：車主與證件
    page.set_input_files("#id_id_front", str(assets / "demo-id-front.jpg"))
    page.wait_for_timeout(1500)
    page.set_input_files("#id_id_back", str(assets / "demo-id-back.jpg"))
    page.wait_for_timeout(5000)
    page.evaluate(r"()=>[...document.querySelectorAll('body *')].filter(e=>getComputedStyle(e).position=='fixed'&&/證件辨識完成/.test(e.textContent)&&e.textContent.length<60).forEach(e=>e.style.display='none')")
    page.fill("#id_owner_phone", "0900-000-123")
    page.check("#id_id_verified")
    ok = mark(page, "text=辨識完成，請核對資料", "ocr-ok", "div[class]")
    page.evaluate("()=>{const b=[...document.querySelectorAll('button')].find(x=>/調整裁切/.test(x.textContent)); b.parentElement.setAttribute('data-help-shot','card-photo')}")
    fields = common_parent(page, "#id_owner_name", "#id_owner_birth_date", "owner-fields")
    shot(page, out / "04-owner.jpg", [{"sel": ok, "n": 1}, {"sel": "[data-help-shot=card-photo]", "n": 2}, {"sel": fields, "n": 3}], margin=24)
    # 證件調整視窗（〈拍證件與核對資料〉）：打開後截圖再取消，不改照片
    page.locator("button:has-text('調整裁切')").first.click()
    page.wait_for_timeout(1200)
    dialog = page.locator("dialog[open]").first
    box = dialog.bounding_box()
    shots_in_dialog = [{"sel": mark(page, "dialog[open] button:has-text('向左轉')", "turn-left"), "n": 1},
                       {"sel": mark(page, "dialog[open] button:has-text('自動偵測')", "auto-detect"), "n": 2},
                       {"sel": mark(page, "dialog[open] button:has-text('套用')", "apply"), "n": 3}]
    from shots import ANNOTATE, CLEAR
    page.evaluate(ANNOTATE, shots_in_dialog)
    page.screenshot(path=str(out / "10-adjust.jpg"), type="jpeg", quality=82,
                    clip={"x": max(0, box["x"] - 16), "y": max(0, box["y"] - 16), "width": min(1440, box["width"] + 32), "height": box["height"] + 32})
    page.evaluate(CLEAR)
    page.locator("dialog[open] button:has-text('取消')").first.click()
    page.wait_for_timeout(500)
    verify = mark(page, "#id_id_verified", "verify", "label, .check-row")
    region(page, out / "05-verify.jpg", verify, [{"sel": verify, "n": 4}], pad=48)
    next_step(page)

    # 第 3 步：汰舊與補助（本例沒有，截圖給〈汰舊與補助〉用）
    tradein = mark(page, "text=申請補助（可多選）", "tradein-section", SECTION)
    programs = common_parent(page, "#id_subsidy_programs_0", "#subsidy-other-toggle", "programs")
    region(page, out / "09-tradein.jpg", tradein, [{"sel": programs, "n": 1}])
    next_step(page)

    # 第 4 步：選號與交車
    page.select_option("#id_plate_choice", "watch")
    page.wait_for_timeout(300)
    page.fill("#id_watched_numbers", "8899、9988")
    page.fill("#id_plate_selection_fee", "1200")
    page.select_option("#id_delivery_method", "store_pickup")
    region(page, out / "06-delivery.jpg", mark(page, "#id_plate_choice", "delivery-section", SECTION), [
        {"sel": mark(page, "#id_plate_choice", "plate-choice", ".field"), "n": 1},
        {"sel": mark(page, "#id_plate_selection_fee", "plate-fee", ".field"), "n": 2},
        {"sel": mark(page, "#id_watched_numbers", "watched", ".field"), "n": 3},
        {"sel": mark(page, "#id_delivery_method", "delivery-method", ".field"), "n": 4}])
    next_step(page)

    # 第 5 步：加購項目
    page.select_option("#id_accessories-0-accessory_product", label="示範後箱")
    page.wait_for_timeout(600)
    row = mark(page, "#id_accessories-0-accessory_product", "acc-row", ".accessory-row, .order-accessory-row, tr, .accessory-line")
    region(page, out / "07-accessory.jpg", mark(page, "#id_accessories-0-accessory_product", "acc-section", SECTION), [{"sel": row, "n": 1}])
    next_step(page)

    # 第 6 步：訂金與費用
    page.fill("#id_deposit_amount", "3000")
    page.fill("#id_deposit_date", "2026-11-16")
    page.select_option("#id_deposit_method", "cash")
    page.wait_for_timeout(500)
    leaf_text(page, "目前金額", "amount-title")
    page.evaluate("()=>{const z=[...document.querySelectorAll('main *')].find(e=>e.children.length==0&&/由分期公司支付/.test(e.textContent)); z.setAttribute('data-help-shot','amount-end')}")
    amounts = common_parent(page, "[data-help-shot=amount-title]", "[data-help-shot=amount-end]", "amounts")
    amount_text = page.evaluate(TEXT, amounts)
    if "4,400" not in amount_text:
        raise RuntimeError(f"分期外應收不是 4,400，說明範例要重算：{amount_text[:200]}")
    deposit = mark(page, "#id_deposit_amount", "deposit", ".form-grid, .field-group, fieldset")
    shot(page, out / "08-deposit.jpg", [{"sel": amounts, "n": 1}, {"sel": deposit, "n": 2}], margin=24)
    next_step(page)

    # 第 7 步：確認送出
    submit = mark(page, "button:has-text('確認並建立訂單')", "submit")
    page.click(submit)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path=str(out / "11-submitted.jpg"), type="jpeg", quality=82, clip={"x": 0, "y": 0, "width": 1440, "height": 1030})
    order = re.search(r"/(\d+)/$", page.url)
    if not order:
        raise RuntimeError("沒有進到訂單成立頁：" + page.url)
    return {"order_pk": order.group(1), "amounts": amount_text}
