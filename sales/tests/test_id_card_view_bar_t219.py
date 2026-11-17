"""T-219：建立訂單證件卡片的「調整裁切／旋轉」與「已手動調整」標籤移到卡片下方一列，不再疊在證件上遮住證號。"""
import re
from pathlib import Path

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase

TEMPLATE = Path(settings.BASE_DIR) / "templates" / "sales" / "_order_owner_section.html"
CSS = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")


def rule(selector):
    found = re.findall(rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]*)\}}", CSS)
    assert len(found) == 1, selector
    return found[0]


class IdCardViewBarTests(SimpleTestCase):
    def test_badge_and_action_sit_in_a_bar_after_the_card_on_both_sides(self):
        get_template("sales/_order_owner_section.html")  # 語法正確
        source = TEMPLATE.read_text(encoding="utf-8")
        views = re.findall(r'<button type="button" class="id-card-view".*?</button>', source, re.S)
        self.assertEqual(len(views), 2, "正面、反面各一")
        for view in views:
            canvas = view.index("data-id-card-canvas")
            bar = view.index('class="id-card-view__bar"')
            self.assertLess(canvas, bar, "下方一列在卡片之後")
            inside = view[bar:]
            self.assertIn("data-id-card-badge", inside)
            self.assertIn("調整裁切／旋轉", inside)

    def test_nothing_is_overlaid_on_the_card(self):
        for selector in (".id-card-view__badge", ".id-card-view__action", ".id-card-view__bar"):
            self.assertNotIn("position: absolute", rule(selector), f"{selector} 不疊在證件上")
        self.assertIn("aspect-ratio: 85.6 / 54", rule(".id-card-view__card"), "卡片本身維持證件比例")
        self.assertNotIn("aspect-ratio", rule(".id-card-view"), "外框高度＝卡片＋下方一列")
        self.assertIn("min-height: 44px", rule(".id-card-view__bar"))
