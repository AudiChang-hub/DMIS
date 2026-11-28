"""「從這裡開始」主線：接著 create_order 的王小明訂單，配車 → 領牌 → 交車收尾款 → 套表列印 → 結案。"""
from shots import ANNOTATE, CLEAR, TEXT, common_parent, leaf_text, mark, shot, viewport


def section(page, title, tag):
    page.evaluate("([t,g])=>{const s=[...document.querySelectorAll('section')].find(x=>(x.querySelector('h2,h3')||{}).textContent?.includes(t)); if(!s) throw new Error('找不到區塊：'+t); s.setAttribute('data-help-shot',g)}",
                  [title, tag])
    return f"[data-help-shot={tag}]"


def run(page, base, out, assets, facts):
    order = f"{base}/orders/{facts['create_order']['order_pk']}/"
    result = {}

    # 配車：訂單頁直接停在目前步驟
    page.goto(order, wait_until="networkidle")
    page.wait_for_timeout(800)
    leaf_text(page, "訂車與配件", "nav-first", left_of=300)
    leaf_text(page, "交車與收尾款", "nav-last", left_of=300)
    nav = common_parent(page, "[data-help-shot=nav-first]", "[data-help-shot=nav-last]", "order-nav")
    allocate = mark(page, "button:has-text('確認配車並鎖定')", "allocate")
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    viewport(page, out / "01-order-allocate.jpg", [{"sel": nav, "n": 1, "pad": 2}, {"sel": section(page, "配車", "allocate-section"), "n": 2},
                                                     {"sel": allocate, "n": 3}], height=760)
    page.click(allocate)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # 領牌
    page.goto(order, wait_until="networkidle")
    page.wait_for_timeout(800)
    page.fill("#reg_registration_date", "2026-11-16")
    page.fill("#reg_final_plate_number", "ABC-1234")
    # 自動儲存成功後領牌區（#registration-completion）會被伺服器重畫的版本整個換掉，先標記就會被洗掉。
    # 2.45.0 起存檔要多算原廠代墊／代轉（T-337），固定等 1.8 秒不夠，改成等頁首存檔狀態變「已儲存」、領牌區換成可確認。
    page.wait_for_function("()=>{const c=document.querySelector('[data-save-chip]');"
                           "return c&&c.dataset.state==='saved'&&!c.hasAttribute('data-sending')"
                           "&&document.querySelector('#registration-completion.is-ready')}", timeout=20000)
    page.wait_for_timeout(500)
    shot(page, out / "02-registration.jpg", [{"sel": mark(page, "#reg_registration_date", "reg-date", ".field"), "n": 1},
                                             {"sel": mark(page, "#reg_final_plate_number", "reg-plate", ".field"), "n": 2},
                                             {"sel": mark(page, "button:has-text('確認完成')", "reg-done"), "n": 3}], margin=30)
    page.click("button:has-text('確認完成')")
    page.wait_for_timeout(700)
    lock = mark(page, "button:has-text('確認完成並鎖定')", "lock")
    dialog = mark(page, "button:has-text('確認完成並鎖定')", "lock-dialog", "dialog, [role=dialog]")
    page.evaluate(ANNOTATE, [{"sel": lock, "n": 4}])
    box = page.evaluate("(s)=>{const r=document.querySelector(s).getBoundingClientRect(); return [r.left,r.top,r.width,r.height]}", dialog)
    page.screenshot(path=str(out / "03-registration-lock.jpg"), type="jpeg", quality=82,
                    clip={"x": box[0] - 24, "y": box[1] - 24, "width": box[2] + 48, "height": box[3] + 48})
    page.evaluate(CLEAR)
    page.click(lock)
    page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle")

    # 交車並收尾款
    page.goto(order, wait_until="networkidle")
    page.wait_for_timeout(800)
    section(page, "交車與收尾款", "delivery-section")
    page.evaluate(r"()=>{const a=[...document.querySelectorAll('[data-help-shot=delivery-section] *')].find(e=>e.children.length==0&&e.textContent.trim()=='應收怎麼算'); let x=a; while(!/應收\s*\$/.test(x.innerText)||x.innerText.length<60) x=x.parentElement; x.setAttribute('data-help-shot','balance-how')}")
    result["balance"] = page.evaluate(TEXT, "[data-help-shot=balance-how]")
    if "$1,400" not in result["balance"]:
        raise RuntimeError("應收不是 $1,400，說明範例要重算：" + result["balance"])
    page.fill("#id_balance-received_amount", "1400")
    page.fill("#id_balance-received_on", "2026-11-16")
    page.select_option("#id_balance-payment_method", "現金")
    received = common_parent(page, "#id_balance-received_amount", "#id_balance-payment_method", "balance-fields")
    shot(page, out / "04-delivery-balance.jpg", [{"sel": "[data-help-shot=balance-how]", "n": 1}, {"sel": received, "n": 2}], margin=24)
    page.fill("#id_delivered_at", "2026-11-16T15:00")
    done = mark(page, "button:has-text('收尾款並完成交車')", "delivery-done")
    shot(page, out / "05-delivery-submit.jpg", [{"sel": mark(page, "#id_recipient_name", "recipient", ".form-grid, fieldset, .field"), "n": 3},
                                                {"sel": done, "n": 4}], margin=24)
    page.click(done)
    page.wait_for_timeout(1200)
    confirm = page.locator("dialog[open] button.primary, dialog[open] button.danger")
    if confirm.count():
        confirm.first.click()
    page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle")
    page.goto(order, wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path=str(out / "06-delivered.jpg"), type="jpeg", quality=82, clip={"x": 0, "y": 0, "width": 1440, "height": 560})

    # 結案（先拍，套表列印不影響訂單狀態）：「確認結案」在左側「取消與結案」面板裡
    page.click(leaf_text(page, "取消與結案", "nav-close", left_of=300))
    page.wait_for_timeout(1200)
    close_section = section(page, "確認結案", "close-section")
    close = mark(page, "button:has-text('確認結案')", "close")
    shot(page, out / "11-close.jpg", [{"sel": close_section, "n": 1, "pad": 2}, {"sel": close, "n": 2}], margin=30)

    # 套表列印
    page.goto(f"{base}/orders/forms-print/?q=王小明&tab=all", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.locator("input[aria-label*='建議的套表']").first.check()
    page.wait_for_timeout(300)
    mark(page, "input[aria-label*='建議的套表']", "fp-row", "tr")
    page.evaluate("()=>{const r=document.querySelector('[data-help-shot=fp-row]'); const c=[...r.querySelectorAll('input[type=checkbox]')]; c[c.length-1].click(); c[0].closest('td,th,label').setAttribute('data-help-shot','fp-lead')}")
    page.wait_for_timeout(400)
    tray = mark(page, ".form-print__tray", "fp-tray")
    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
    page.evaluate(ANNOTATE, [{"sel": "[data-help-shot=fp-lead]", "n": 1}, {"sel": tray, "n": 2, "pad": 2}])
    page.screenshot(path=str(out / "07-formprint-select.jpg"), type="jpeg", quality=82, clip={"x": 0, "y": 70, "width": 1440, "height": 760})
    page.evaluate(CLEAR)
    page.set_viewport_size({"width": 1440, "height": 900})  # 預覽是全螢幕視窗，截一個螢幕高就好
    page.keyboard.press("p")
    page.wait_for_timeout(2500)
    page.evaluate("()=>{const f=t=>[...document.querySelectorAll('button')].filter(b=>t.test(b.textContent)&&b.getClientRects().length&&b.getBoundingClientRect().top>600).pop(); f(/下載信封/).setAttribute('data-help-shot','fp-word'); f(/開啟.*列印/).setAttribute('data-help-shot','fp-pdf')}")
    page.evaluate(ANNOTATE, [{"sel": "[data-help-shot=fp-word]", "n": 4}, {"sel": "[data-help-shot=fp-pdf]", "n": 5}])
    page.screenshot(path=str(out / "09-formprint-preview.jpg"), type="jpeg", quality=82)
    page.evaluate(CLEAR)
    page.evaluate("()=>{const b=[...document.querySelectorAll('dialog[open] button')].find(x=>x.textContent.trim()==='2'); if(!b) throw new Error('找不到預覽第 2 頁縮圖'); b.click()}")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out / "10-formprint-idcopy.jpg"), type="jpeg", quality=82)
    return result
