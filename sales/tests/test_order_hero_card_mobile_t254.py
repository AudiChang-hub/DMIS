"""T-254（使用者 2026-11-20「車行小卡選甲」）：手機版訂單頁頁首的台數歸屬小卡只留一行小字。

頂端區塊（T-250）已常駐「車行」與「變更車行」，頁首小卡收起「這台目前算給＋車行名稱＋變更車行」，
只留：原訂單來源｜依原領牌期間計算（平台單為平台說明）、鎖定原因。浮層改由頂端區塊打開。

順帶修正同一入口的 bug：按頂端「變更車行」時，小卡的「點浮層外就關閉」把同一下點擊當成點在外面，
浮層一打開就被關掉（實測手機 375／390 打不開）。電腦版畫面不變。
"""
import re
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase

STATIC = Path(settings.BASE_DIR) / "static"


class MobileAttributionCardTests(SimpleTestCase):
    def css_block(self):
        css = (STATIC / "css/order-commission-recipient.css").read_text(encoding="utf-8")
        return css[css.index("/* T-254"):]

    def test_mobile_card_keeps_only_meta_and_lock_reason(self):
        block = self.css_block()
        self.assertRegex(block, r"@media \(max-width: 860px\) \{")
        self.assertIn(".order-hero :is(.commission-attribution__label, .commission-attribution__recipient) { display: none; }", block)
        self.assertIn(".order-hero .commission-attribution__editor > summary { display: none; }", block)
        self.assertIn(".order-hero .commission-attribution { display: block; padding: 0; background: none; border: 0; box-shadow: none; }", block)
        for kept in ("commission-attribution__meta", "commission-attribution__locked"):
            self.assertNotRegex(block, re.escape(kept) + r"[^{]*\{[^}]*display: none")

    def test_card_template_still_renders_meta_and_lock_reason(self):
        html = render_to_string("sales/_order_commission_attribution.html", {
            "order": type("O", (), {"source_type": "store", "source": "", "effective_commission_recipient": "",
                                    "get_source_type_display": lambda self: "本店"})(),
            "inline_order_form": None, "commission_form": None, "commission_block_reason": "示範鎖定原因",
        })
        self.assertIn('class="commission-attribution__meta"', html)
        self.assertIn('<p class="commission-attribution__locked">示範鎖定原因</p>', html)

    def test_compact_change_button_opens_panel_instead_of_closing_it(self):
        attribution = (STATIC / "js/order-commission-attribution.js").read_text(encoding="utf-8")
        self.assertIn("if (event.target.closest?.('[data-compact-change]')) return;", attribution)
        # 收起來的小卡按鈕看不到時，關閉後焦點回到頂端「變更車行」。
        self.assertIn("summary.getClientRects().length ? summary : document.querySelector('[data-compact-change]') || summary", attribution)
        compact = (STATIC / "js/order-compact-bar.js").read_text(encoding="utf-8")
        self.assertIn("panel?.querySelector('select, input:not([type=hidden]), textarea, button:not([hidden])')", compact)
        self.assertIn("panel?.scrollIntoView({block: 'nearest', behavior: 'instant'});", compact)
