"""T-251（使用者 2026-11-19）：「手機版把頁首重複的大客戶名稱和車行小卡收起來」。

手機版（≤860px）訂單頁頂端區塊已常駐客戶名稱、狀態與儲存狀態，頁首的大名稱列只留給讀屏；名稱旁的備註便條照常顯示。
車行小卡裡有頂端區塊沒有的資訊（原訂單來源、依原領牌期間計算、平台說明、鎖定原因），先保留、回報 PM。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STATIC = Path(settings.BASE_DIR) / "static"
TEMPLATES = Path(settings.BASE_DIR) / "templates"


class MobileHeroCollapseTests(SimpleTestCase):
    def test_mobile_hides_duplicate_name_row_but_keeps_it_for_screen_readers(self):
        css = (STATIC / "css/order-workspace.css").read_text(encoding="utf-8")
        block = css[css.index("/* T-251"):]
        rule = re.search(r"@media \(max-width: 860px\) \{\s*\.order-hero \.title-with-status > :is\(h1, \.status-pill, \.save-chip\) \{([^}]*)\}", block)
        self.assertIsNotNone(rule)
        # 視覺隱藏而不是 display: none：h1 仍是頁面標題，儲存狀態（aria-live）仍會播報。
        self.assertIn("clip-path: inset(50%)", rule.group(1))
        self.assertNotIn("display: none", rule.group(1))

    def test_note_and_attribution_card_stay_visible(self):
        css = (STATIC / "css/order-workspace.css").read_text(encoding="utf-8")
        block = css[css.index("/* T-251"):]
        self.assertNotIn("order-hero-note", block.split("*/", 1)[1])
        self.assertNotIn("commission-attribution", block)

    def test_only_order_page_hero_is_affected(self):
        page = (TEMPLATES / "sales/order_detail.html").read_text(encoding="utf-8")
        # .order-hero 只在訂單頁（非編輯模式）出現，編輯模式與建單精靈不受影響。
        self.assertIn('{% if not editing_order %} order-hero{% endif %}', page)
