"""「剛開始用」的篇章截圖（T-197 第二批）。每段寫到 static/help/screens/<篇名>/。

使用 seed_help_demo 的合成資料（含 --manage 補的示範業務帳號、公告）。不送出任何會改資料的表單。
"""
from shots import ANNOTATE, CLEAR, TEXT, mark, shot, viewport
from scenarios.topics import folder, order_pk


def clip(page, path, items, box):
    """標註後只截 box（x, y, width, height）這一塊，用在小選單、手機畫面。"""
    page.evaluate(ANNOTATE, items)
    page.screenshot(path=str(path), type="jpeg", quality=82, clip=dict(zip(("x", "y", "width", "height"), box)))
    page.evaluate(CLEAR)


def mobile(page):
    """同一個登入狀態開手機寬度的新分頁。"""
    phone = page.context.new_page()
    phone.set_viewport_size({"width": 375, "height": 812})
    return phone


# ── 第一次登入與畫面入口 ─────────────────────────────────────────
def first_use(page, base, out, assets, facts):
    out = folder(out, "first-use")
    guest = page.context.browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-TW", reduced_motion="reduce")
    login = guest.new_page()
    login.goto(f"{base}/login/", wait_until="networkidle")
    login.fill("input[name=username]", "demo.sales")
    login.evaluate("document.activeElement.blur()")
    login.evaluate("document.querySelectorAll('.login-field').forEach((f,i)=>f.setAttribute('data-help-shot','login-field-'+i))")
    shot(login, out / "01-login.jpg", [{"sel": "[data-help-shot=login-field-0]", "n": 1, "pad": 8},
                                      {"sel": "[data-login-submit]", "n": 2}], margin=40)
    guest.close()

    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{base}/", wait_until="networkidle")
    page.evaluate("document.querySelector('details.account-menu').open=true")
    page.wait_for_timeout(300)
    box = page.evaluate("()=>{const r=document.querySelector('.account-menu__popover').getBoundingClientRect(); return [r.left,r.top,r.right,r.bottom]}")
    left = max(0, box[0] - 260)
    clip(page, out / "02-account-menu.jpg", [{"sel": ".account-menu__popover", "n": 3}],
         (left, 0, min(1440, box[2] + 30) - left, box[3] + 30))
    page.evaluate("document.querySelector('details.account-menu').open=false")

    phone = mobile(page)
    phone.set_viewport_size({"width": 375, "height": 1180})  # 「更多」整片都要入鏡，最下面才看得到配色、密碼與登出
    phone.goto(f"{base}/", wait_until="networkidle")
    phone.click("details.mobile-data-menu > summary")
    phone.wait_for_timeout(400)
    viewport(phone, out / "03-mobile-more.jpg", [{"sel": "details.mobile-data-menu > summary", "n": 4},
                                                 {"sel": ".mobile-data-popover__footer", "n": 5}])
    phone.close()
    return {}


# ── 首頁、常用功能與公告 ─────────────────────────────────────────
def home(page, base, out, assets, facts):
    out = folder(out, "home")
    page.set_viewport_size({"width": 1440, "height": 1100})
    page.goto(f"{base}/", wait_until="networkidle")
    if "12/1 起 SUI 125 現金價調整" not in page.evaluate(TEXT, "main"):
        raise RuntimeError("首頁沒有示範公告；請先跑 seed_help_demo --manage")
    shot(page, out / "01-dashboard.jpg", [{"sel": "a[href$='home-favorites/']", "n": 1}, {"sel": ".news-tabs", "n": 2}],
         margin=30, max_height=1000)
    page.goto(f"{base}/account/home-favorites/", wait_until="networkidle")
    page.fill("[data-favorites-search]", "草稿")
    page.wait_for_timeout(400)
    shot(page, out / "02-favorites.jpg", [{"sel": "[data-favorites-search]", "n": 3}, {"sel": ".favorites-preview", "n": 4}],
         margin=30, max_height=900)
    phone = mobile(page)
    phone.goto(f"{base}/", wait_until="networkidle")
    phone.click("details.mobile-data-menu > summary")
    phone.wait_for_timeout(300)
    phone.click("[data-mobile-shortcuts-open]")
    phone.wait_for_timeout(500)
    viewport(phone, out / "03-mobile-shortcuts.jpg", [{"sel": "dialog[open] select", "n": 5}])
    phone.close()
    return {}


# ── 個資與帳號安全 ───────────────────────────────────────────────
def security(page, base, out, assets, facts):
    out = folder(out, "security")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{base}/account/password/", wait_until="networkidle")
    form = mark(page, ".password-change-shell form", "password-form")
    shot(page, out / "01-password.jpg", [{"sel": form, "n": 1}], margin=30)
    return {}


# ── 畫面出現看不懂的訊息 ─────────────────────────────────────────
def troubleshooting(page, base, out, assets, facts):
    out = folder(out, "troubleshooting")
    # 權限不足的錯誤頁：用沒有刪除審核權限的示範業務開「刪除審核」（示範站開著除錯模式，404 會是開發用頁面，所以拍 403）
    guest = page.context.browser.new_context(viewport={"width": 1440, "height": 800}, locale="zh-TW", reduced_motion="reduce")
    sales = guest.new_page()
    sales.goto(f"{base}/login/", wait_until="networkidle")
    sales.fill("input[name=username]", "demo.sales")
    sales.fill("input[name=password]", facts["_password"])
    sales.click("[data-login-submit]")
    sales.wait_for_load_state("networkidle")
    sales.goto(f"{base}/orders/deletion-review/", wait_until="networkidle")
    if "你目前不能執行這個操作" not in sales.evaluate(TEXT, "main"):
        raise RuntimeError("示範業務開刪除審核沒有出現權限不足頁")
    shot(sales, out / "01-forbidden.jpg", [{"sel": ".error-page", "n": 1}], margin=30)
    guest.close()
    page.set_viewport_size({"width": 1440, "height": 800})
    page.goto(f"{base}/orders/", wait_until="networkidle")
    page.context.set_offline(True)
    page.evaluate("window.dispatchEvent(new Event('offline'))")
    page.wait_for_timeout(800)
    banner = page.locator("[data-connectivity-banner]")
    if banner.is_hidden():
        page.context.set_offline(False)
        raise RuntimeError("沒有出現「目前沒有網路連線」提示")
    viewport(page, out / "02-offline.jpg", [{"sel": "[data-connectivity-banner]", "n": 2}], height=420)
    page.context.set_offline(False)
    page.evaluate("window.dispatchEvent(new Event('online'))")
    pk = order_pk(page, base, "示範客戶32")
    page.goto(f"{base}/orders/{pk}/?tab=delivery", wait_until="networkidle")
    page.wait_for_timeout(600)
    blockers = page.locator(".delivery-blockers:visible").first
    text = blockers.inner_text()
    if "尚未配車" not in text:
        raise RuntimeError("示範客戶32 的交車清單沒有「尚未配車」：" + text)
    blockers.evaluate("e=>(e.closest('section, article, .card')||e).setAttribute('data-help-shot','blockers')")
    shot(page, out / "03-delivery-blockers.jpg", [{"sel": "[data-help-shot=blockers]", "n": 3}], margin=30, max_height=700)
    return {"blockers": text}


# ── 名詞表 ───────────────────────────────────────────────────────
def glossary(page, base, out, assets, facts):
    out = folder(out, "glossary")
    page.set_viewport_size({"width": 1440, "height": 1300})
    page.goto(f"{base}/orders/", wait_until="networkidle")
    # 最新的幾張單剛好是不同狀態（刪除確認中、待配車、已取消、已交車／待結案…），框住狀態欄的前幾格
    page.evaluate("""()=>{const pills=[...document.querySelectorAll('.status-pill')].slice(0,6);
        const top=Math.min(...pills.map(p=>p.getBoundingClientRect().top)), bottom=Math.max(...pills.map(p=>p.getBoundingClientRect().bottom));
        const left=Math.min(...pills.map(p=>p.getBoundingClientRect().left)), right=Math.max(...pills.map(p=>p.getBoundingClientRect().right));
        const box=document.createElement('div'); box.setAttribute('data-help-shot','status-column');
        Object.assign(box.style,{position:'absolute',left:(left+scrollX)+'px',top:(top+scrollY)+'px',width:(right-left)+'px',height:(bottom-top)+'px',pointerEvents:'none'});
        document.body.appendChild(box)}""")
    shot(page, out / "01-status.jpg", [{"sel": "[data-help-shot=status-column]", "n": 1, "pad": 10}], margin=30, max_height=1000)
    return {}


PARTS = (first_use, home, security, troubleshooting, glossary)


def run(page, base, out, assets, facts):
    return {part.__name__: part(page, base, out, assets, facts) for part in PARTS}
