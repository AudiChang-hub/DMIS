"""T-303：營運總表「貨」卡兩處改善（使用者 2026-11-24 看過示意圖，照做）。

1. 庫齡長條每段可指到、Tab 聚焦、手機點一下，標題右邊寫「區間 N 台・佔 %」；圖例雙向連動；讀螢幕軟體念每段的台數。
2. 可銷天數欄不畫色塊（拿掉 T-300 的長條、斜紋、實心），改成「N 天」＋一行原因（月賣台數）；缺貨／滯銷／90 天未售標籤保留。
3. 底下兩行公式縮成一句。
只改貨卡：錢卡的帳齡長條、其他卡片不受影響。
"""
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder, VehicleColor, VehicleModel
from sales.services import operations_cockpit
from sales.tests.test_operations_cockpit import make_vehicle

ROOT = Path(settings.BASE_DIR)


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def _rule(css, selector):
    match = re.search(r"(?:^|\n)" + re.escape(selector) + r" \{([^}]*)\}", css)
    return match.group(1) if match else ""


class CoverReasonTests(SimpleTestCase):
    def test_reason_uses_monthly_rate(self):
        cases = {(27, 57): "月賣約 19 台", (5, 4): "月賣約 1.3 台", (3, 3): "月賣約 1 台", (3, 2): "月賣不到 1 台",
                 (0, 3): "沒有庫存・月賣約 1 台", (2, 0): ""}
        for (on_hand, sold), text in cases.items():
            with self.subTest(on_hand=on_hand, sold=sold):
                self.assertEqual(operations_cockpit._cover_reason(on_hand, sold), text)


class StockCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("t303-admin", password="test-only")
        cls.model = VehicleModel.objects.create(brand="測試", name="T303 機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.ev = VehicleModel.objects.create(brand="測試", name="T303 電車", energy_type="electric")
        cls.ev_color = VehicleColor.objects.create(vehicle_model=cls.ev, name="藍")

    def setUp(self):
        cache.clear()
        today = timezone.localdate()
        for number in (1, 2):
            make_vehicle(self.model, self.color, "available", number, received_on=today - timedelta(days=95))
        make_vehicle(self.model, self.color, "reserved", 3, received_on=today - timedelta(days=10))
        for offset in (1, 20, 40):   # 電車近 90 天賣 3 台、在庫 0 → 缺貨風險
            SalesOrder.objects.create(
                owner_name="T303 合成", owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
                vehicle_model=self.ev, color=self.ev_color, registration_date=today - timedelta(days=offset),
                established_on=today - timedelta(days=offset), status="completed", vehicle_price=80000,
                registration_completed_at=timezone.now())

    def card(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("operations_report")).content.decode()
        start = html.index('aria-labelledby="ops-stock-title"')
        return html[start:html.index("</section>", start)]

    def test_aging_share_and_reason_fields(self):
        stock = operations_cockpit.build("month", timezone.localdate())["stock"]
        self.assertEqual([(bucket["count"], bucket["share"]) for bucket in stock["aging"]],
                         [(1, 33), (0, 0), (0, 0), (2, 67)])
        rows = {row["name"]: row for row in stock["models"]}
        self.assertEqual(rows["T303 電車"]["reason"], "沒有庫存・月賣約 1 台")
        self.assertEqual(rows["T303 機種"]["reason"], "")

    def test_aging_segments_focusable_labelled_and_linked_to_legend(self):
        html = self.card()
        self.assertIn('<div class="ops-bar ops-age" role="group" aria-labelledby="ops-age-title" data-ops-age-bar>', html)
        self.assertIn('<span id="ops-age-title">庫齡 <small>實際已放多久・從進車日算</small></span>', html)  # T-304 改字
        segments = re.findall(r'<span class="ops-bar__seg ops-bar__seg--\d[^"]*" style="flex-grow: \d+"([^>]*)>', html)
        self.assertEqual(len(segments), 4)
        self.assertIn('role="img" tabindex="0" aria-label="未滿 30 天 1 台，佔 33%" data-ops-age="1"', segments[0])
        self.assertIn('aria-label="90 天以上 2 台，佔 67%" data-ops-age="4"', segments[3])
        for empty in segments[1:3]:   # 0 台的段不給焦點，讀螢幕軟體略過
            self.assertEqual(empty, ' aria-hidden="true"')
        self.assertEqual(re.findall(r'<li class="[^"]*" data-ops-age="(\d)">', html), ["1", "4"])
        self.assertIn('data-ops-age-readout data-empty aria-hidden="true" hidden>指到或點色塊看台數</span>', html)

    def test_cover_column_has_no_bar_and_shows_reason_with_tags(self):
        html = self.card()
        self.assertNotIn("ops-cover__bar", html)
        self.assertIn('<b class="ops-cover__value">0 天</b><em class="ops-tag ops-tag--red">缺貨風險</em></span>'
                      '<small class="ops-cover__why">沒有庫存・月賣約 1 台</small>', html)
        self.assertIn('<span class="ops-cover__main"><em class="ops-tag ops-tag--amber">滯銷</em></span>'
                      '<small class="ops-cover__why">近 90 天沒賣出</small></span>', html)  # T-304 改字

    def test_formula_hint_is_one_sentence(self):
        html = self.card()
        self.assertIn('<p class="ops-hint">庫齡＝實際已放幾天；預估可銷天數＝照近 90 天賣速推估還能賣幾天。'
                      '預估超過 90 天或 90 天沒賣出＝滯銷。</p>', html)  # T-304 改字
        self.assertNotIn("平均每天領牌台數", html)

    def test_money_card_aging_bar_unchanged(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("operations_report")).content.decode()
        start = html.index('aria-labelledby="ops-money-title"')
        money = html[start:html.index("</section>", start)]
        self.assertNotIn("ops-age", money)
        self.assertNotIn("data-ops-age", money)


class StockCardAssetTests(SimpleTestCase):
    def test_css_removes_cover_bar_and_scopes_age_interaction(self):
        css = _read("static/css/operations.css").replace("\r\n", "\n")
        self.assertNotIn(".ops-cover__bar", css)
        self.assertNotIn("--cover", css)
        self.assertIn("overflow: hidden", _rule(css, ".ops-bar"))           # 錢卡長條照舊
        self.assertIn("overflow: visible", _rule(css, ".ops-bar.ops-age"))  # 貨卡長條聚焦外框不被裁掉
        self.assertIn("outline: 2px solid var(--focus-ring)", _rule(css, ".ops-age .ops-bar__seg:focus-visible"))
        self.assertIn("opacity: .3", _rule(css, ".ops-age.has-active .ops-bar__seg:not(.is-active)"))
        self.assertRegex(css, r"@media \(prefers-reduced-motion: reduce\) \{\n  \.ops-age \.ops-bar__seg,\n"
                              r"  \.ops-legend--linked li \{\n    transition: none;")

    def test_js_links_bar_legend_focus_and_tap(self):
        js = _read("static/js/operations.js")
        for snippet in ('querySelectorAll("[data-ops-age-bar]")', 'addEventListener("pointerover"',
                        'addEventListener("focusin"', 'addEventListener("focusout"', 'area.addEventListener("click"',
                        "readout.hidden = false;", '"・佔 " + seg.getAttribute("data-share") + "%"'):
            self.assertIn(snippet, js)
