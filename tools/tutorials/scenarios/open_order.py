"""教學片：開訂單（建立訂單精靈七個步驟）。"""
from pathlib import Path

TITLE = "開訂單"
SUBTITLE = "建立訂單精靈：車款 → 付款 → 車主 → 汰舊補助 → 選號交車 → 訂金 → 確認"


def next_step(rec, step):
    rec.click(rec.page.locator("button[name=_wizard_action][value=next]"))
    rec.page.wait_for_url(f"**step={step}**")
    rec.page.wait_for_load_state("networkidle")


def run(rec, base_url, assets):
    page = rec.page
    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")
    rec.title(f"教學｜{TITLE}", SUBTITLE)

    rec.say("這支影片示範怎麼在系統裡開一張新訂單。先按畫面上方的「建立訂單」，進入選車頁。")
    rec.click(page.get_by_role("link", name="建立訂單").first, after=0.2)
    page.wait_for_url("**/catalog/**")
    page.wait_for_load_state("networkidle")
    rec.wait()

    # 選車
    rec.say("選車頁會列出所有車款和車色，可以用品牌、車型篩選，也可以直接往下找。這裡先篩選 SUZUKI。")
    rec.choose(page.locator("#catalog-brand"), "SUZUKI")
    page.wait_for_load_state("networkidle")
    rec.pause(0.8)
    rec.scroll_by(420, 1.4)
    rec.say("找到要的車款和顏色，按「選這台接單」，直接進入建立訂單。")
    card_link = page.locator("a", has_text="選這台接單").first
    rec.click(card_link, after=0.2)
    page.wait_for_url("**/intake/new/**")
    page.wait_for_load_state("networkidle")
    rec.wait()

    # 第一步：車款與來源
    rec.say("進入建立訂單精靈。第一步「車款與來源」，車型和車色都已經帶入。")
    rec.highlight(page.locator("#id_vehicle_model").locator("xpath=ancestor::*[contains(@class,'field')][1]"), 0.9)
    rec.say("這裡只要選擇訂單來源和來源名稱，再按「下一步」，系統會自動存成草稿。")
    rec.highlight(page.locator("#id_source_type"), 0.6)
    rec.pick("id_source", "", "示範門市")
    rec.wait()
    rec.click(page.locator("button[name=_wizard_action][value=next]"))
    page.wait_for_url("**step=payment**")
    page.wait_for_load_state("networkidle")

    # 第二步：付款與車價
    rec.say("第二步是付款與車價。選擇現金或分期，車價會自動帶入；分期再選分期公司與期數。")
    rec.highlight(page.locator("#id_payment_type"), 0.6)
    rec.highlight(page.locator("#id_vehicle_price"), 0.8)
    rec.wait()
    next_step(rec, "owner")

    # 第三步：車主與證件
    rec.say("第三步是車主與證件。請把身分證正面和反面都上傳，兩面都上傳後系統才會開始辨識姓名、證號、生日和地址。")
    rec.highlight(page.locator("#id_id_front").locator("xpath=ancestor::*[contains(@class,'field')][1]"), 0.6)
    page.locator("#id_id_front").set_input_files(str(Path(assets) / "id-front.png"))
    rec.pause(0.8)
    page.locator("#id_id_back").set_input_files(str(Path(assets) / "id-back.png"))
    page.wait_for_function("() => document.querySelector('#id_owner_name') && document.querySelector('#id_owner_name').value", timeout=20000)
    rec.wait()
    rec.say("辨識完成後，請對照照片逐項核對，補上電話，再勾選「已人工核對證件」，然後按「下一步」。")
    rec.highlight(page.locator("#id_owner_name"), 0.6)
    rec.highlight(page.locator("#id_owner_id_number"), 0.5)
    rec.type(page.locator("#id_owner_phone"), "0912345678")
    rec.click(page.locator("#id_id_verified"))
    rec.wait()
    next_step(rec, "tradein")

    # 第四步：汰舊與補助
    rec.say("第四步是汰舊與補助。先問客人有沒有舊車要汰舊，這裡示範選「是」，下方會多出舊車主的相關欄位。")
    rec.choose(page.locator("#id_trade_in_intent"), "是")
    rec.wait()
    rec.say("如果舊車主就是新車主本人，勾選這一項；舊車主的證件和存摺可以現在上傳，也可以之後在訂單補上。")
    rec.click(page.locator("#id_old_owner_same_as_owner"))
    rec.highlight(page.locator("[data-trade-in-uploads]"), 1.2)
    rec.wait()
    rec.say("接著勾選要申請的補助方案，可以多選。政府有清單以外的補助時，勾「其他」，再填寫補助名稱。")
    rec.click(page.locator(".subsidy-program-picker label", has_text="汰舊換新").first)
    rec.click(page.locator("[data-subsidy-other-toggle]"))
    rec.type(page.locator("#id_subsidy_other"), "縣市加碼補助")
    rec.wait()
    next_step(rec, "delivery")

    # 第五步：選號與交車
    rec.say("第五步是選號與交車。選擇車牌的選號方式（還沒決定可選「待確認」）和交車方式，有其他交代可以寫在備註。")
    rec.highlight(page.locator("#id_plate_choice"), 0.6)
    rec.choose(page.locator("#id_delivery_method"), "客人來店取車")
    rec.wait()
    next_step(rec, "deposit")

    # 第六步：訂金與費用
    rec.say("第六步是訂金與費用。有收訂金就填上金額和付款方式。")
    rec.type(page.locator("#id_deposit_amount"), "3000")
    rec.choose(page.locator("#id_deposit_method"), "現金")
    rec.wait()
    rec.say("有談定總價優惠時，點開「店內調整」。這一區預設收合，平板拿給客人看時不會直接露出。")
    rec.click(page.locator("#intake-discount > summary"))
    rec.wait()
    rec.say("可以選折抵金額或打折，填好後下方會試算優惠前後的總價，再填寫優惠原因，然後按「下一步」。")
    rec.type(page.locator("#id_intake_discount_amount"), "1000")
    rec.highlight(page.locator("[data-discount-preview]"), 1.0)
    rec.type(page.locator("#id_intake_discount_reason"), "老客戶介紹")
    rec.wait()
    next_step(rec, "confirm")

    # 第七步：確認送出
    rec.say("最後一步，核對整張訂單。哪裡需要修改，按該段落的「修改」就能回去調整。")
    rec.scroll_by(900, 3.2)
    rec.say("確認沒問題後，按「確認並建立訂單」。")
    rec.click(page.locator("button[name=_wizard_action][value=submit]"), after=0.3)
    page.wait_for_load_state("networkidle")
    rec.wait()
    rec.say("訂單建立後，系統直接記為由你接單，並出現簽署方式，可以請客人在平板上電子簽名，或印出紙本簽名。到這裡就完成開單了。")
    rec.pause(1.0)
    rec.wait(pad=1.2)
