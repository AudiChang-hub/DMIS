"""T-307 訂單總覽重新編排：重點摘要四格、卡片一列兩張、空白欄位縮小留在原位、備註改成標題區便條紙。

彈窗（訂單頁、全部訂單）與「新分頁開啟」的完整頁面一起改；「複製全部」的內容與順序不變。
"""
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder
from sales.services.order_overview import build_order_overview
from sales.tests import test_order_lifecycle as lifecycle

STATIC = Path(settings.BASE_DIR) / "static"


class OrderOverviewRedesignTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def order(self, **fields):
        order, _vehicle = self.make_order()
        if fields:
            SalesOrder.objects.filter(pk=order.pk).update(**fields)
        return SalesOrder.objects.get(pk=order.pk)

    def glances(self, order):
        return {glance["key"]: glance for glance in build_order_overview(order)["glances"]}

    def fragment(self, order):
        self.client.force_login(self.user)
        return self.client.get(reverse("order_overview", args=[order.pk]) + "?fragment=1").content.decode()

    # ── 重點摘要 ──
    def test_glances_show_owner_vehicle_registration_and_trade_in(self):
        order = self.order()
        glances = self.glances(order)
        self.assertEqual(list(glances), ["owner", "vehicle", "registration", "trade_in"])
        lines = lambda key: {line["label"]: line["value"] for line in glances[key]["lines"]}
        self.assertEqual(glances["owner"]["main"], "王小明")
        self.assertEqual(lines("owner"), {"電話": "0912345678"})
        self.assertEqual(glances["vehicle"]["main"], f"{order.vehicle_model.brand} {order.vehicle_model.name}")
        self.assertEqual(lines("vehicle")["引擎"], order.allocated_vehicle.engine_number)
        self.assertEqual(lines("registration"), {"車牌": "—", "領牌": "—"})
        self.assertEqual((glances["trade_in"]["main"], glances["trade_in"]["none"]), ("無汰舊", True))
        self.assertEqual(lines("trade_in"), {"舊車車牌": "—"})

    def test_registration_glance_states(self):
        planned = self.glances(self.order(registration_date=date(2026, 11, 28)))["registration"]
        self.assertEqual([(line["value"], line["tone"]) for line in planned["lines"]][1], ("預計 2026/11/28", "plan"))
        done = self.glances(self.order(registration_date=date(2026, 11, 15), registration_completed_at=timezone.now(),
                                       final_plate_number="MBC-8888"))["registration"]
        self.assertEqual([(line["value"], line["tone"]) for line in done["lines"]], [("MBC-8888", ""), ("已領牌 2026/11/15", "done")])
        trade_in = self.glances(self.order(is_trade_in_subsidy=True, trade_in_plate="KLM-321"))["trade_in"]
        self.assertEqual((trade_in["main"], trade_in["none"], trade_in["lines"][0]["value"]), ("有汰舊", False, "KLM-321"))

    def test_glances_render_on_top_and_stay_out_of_copy_all(self):
        order = self.order(registration_date=date(2026, 11, 28))
        page = self.fragment(order)
        glances = page.split('data-overview-glances', 1)[1].split('class="order-overview__pairs"', 1)[0]
        self.assertEqual(re.findall(r'href="#overview-(\w+)" data-overview-glance', glances), ["owner", "vehicle", "registration", "trade_in"])
        self.assertIn('class="is-plan"', glances)
        self.assertLess(page.index("data-overview-glances"), page.index('class="order-overview__pairs"'))
        # 摘要只顯示：「複製全部」與改版前一樣，沒有摘要字樣。
        plain = build_order_overview(order)["plain_text"]
        for text in ("無汰舊", "預計 2026/11/28", "重點摘要"):
            self.assertNotIn(text, plain)

    def test_copy_all_keeps_every_section_in_original_order(self):
        overview = build_order_overview(self.order(note="週六下午交車"))
        titles = re.findall(r"【(.+?)】", overview["plain_text"])
        legacy = ["訂單", "車主", "車輛", "選號與領牌", "車行獎勵", "金額與付款", "分期", "汰舊", "交車", "取消與退款", "備註"]
        sections = [title for title in titles if title in legacy]
        self.assertEqual(sections, sorted(sections, key=legacy.index))
        self.assertEqual(sections[:4], ["訂單", "車主", "車輛", "選號與領牌"])
        self.assertIn("【備註】\n備註：週六下午交車", overview["plain_text"])

    # ── 備註便條紙 ──
    def test_fragment_puts_note_on_sticky_note_not_a_card(self):
        page = self.fragment(self.order(note="客人希望週末交車\n先電話聯絡"))
        self.assertEqual(page.count("data-overview-note "), 1)
        note = page.split("<aside", 1)[1].split("</aside>", 1)[0]
        self.assertIn('class="order-overview-note"', note)
        self.assertIn('data-copy="客人希望週末交車\n先電話聯絡"', note)
        self.assertIn("data-overview-note-more hidden", note)
        self.assertIn("看全文", note)
        self.assertIn('data-overview-copy aria-label="複製備註"', note)
        self.assertNotIn('id="overview-note"', page)
        self.assertNotIn('href="#overview-note"', page)
        # 搬到標題區前放在片段最前面，工具列之前。
        self.assertLess(page.index("<aside"), page.index("order-overview__tools"))

    def test_empty_note_says_no_note(self):
        page = self.fragment(self.order(note=""))
        note = page.split("<aside", 1)[1].split("</aside>", 1)[0]
        self.assertIn('class="order-overview-note is-empty"', note)
        self.assertIn("無備註", note)
        self.assertNotIn("看全文", note)
        self.assertNotIn("data-overview-copy", note)

    def test_full_page_puts_note_in_hero_between_title_and_copy_all(self):
        order = self.order(note="週六下午交車")
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_overview", args=[order.pk])).content.decode()
        self.assertEqual(page.count("<aside class=\"order-overview-note"), 1)
        hero = page.split('order-overview-hero', 1)[1].split("</section>", 1)[0]
        self.assertLess(hero.index("<h1>"), hero.index("<aside"))
        self.assertLess(hero.index("<aside"), hero.index("data-overview-copy-all"))
        self.assertIn("週六下午交車", hero)

    def test_dialog_moves_note_into_header(self):
        js = (STATIC / "js" / "order-overview.js").read_text(encoding="utf-8")
        self.assertIn('placeNote(body.querySelector("[data-overview-note]"))', js)
        self.assertIn('head.insertBefore(note, head.querySelector(".order-overview-dialog__actions"))', js)
        # 載入中放同尺寸空位；Esc 先收「看全文」浮層；搜尋符合時標亮便條紙。
        self.assertIn("is-loading", js)
        self.assertIn('event.key !== "Escape"', js)
        self.assertIn('note.classList.toggle("is-match", match)', js)
        # 摘要四格與跳轉按鈕共用面板內捲動。
        self.assertIn('[data-overview-jump], [data-overview-glance]', js)

    # ── 樣式 ──
    def test_css_pairs_empty_rows_and_note_sizes(self):
        css = (STATIC / "css" / "order-overview.css").read_text(encoding="utf-8")
        self.assertIn("@container order-overview-grid (min-width: 640px) { .order-overview__glances { grid-template-columns: repeat(4, minmax(0, 1fr)); } }", css)
        self.assertIn(".order-overview__row.is-empty { min-height: 30px;", css)
        self.assertIn(".order-overview__row.is-empty dt { font-size: var(--text-2xs); font-weight: 500; }", css)
        note = re.search(r"^\.order-overview-note \{([^}]*)\}", css, re.MULTILINE).group(1)
        self.assertIn("height: 104px;", note)
        # 手機：姓名下方一整列、固定兩行高，跟標題區一起固定在頂端。
        self.assertIn('grid-template-areas: "back actions" "title title" "note note";', css)
        self.assertRegex(css, r"\.order-overview-dialog__head \.order-overview-note \{ grid-area: note;[^}]*height: 82px;")
        self.assertIn(".order-overview-dialog__head .order-overview-note__text { -webkit-line-clamp: 2; }", css)
        # 浮層蓋得過固定的搜尋列。
        self.assertIn(".order-overview-dialog__head, .order-overview-hero { position: relative; z-index: 3; }", css)

    def test_accessories_table_is_first_full_width_table(self):
        page = self.fragment(self.order())
        tables = page.split('class="order-overview__tables"', 1)[1]
        self.assertEqual(re.findall(r'<section class="order-overview__card is-table" id="overview-(\w+)"', tables),
                         ["accessories", "fees", "subsidies", "payments"])
        plain = json.loads(re.search(r'<script id="order-overview-text" type="application/json">(.*?)</script>', page, re.S).group(1))
        self.assertIn("【車主】", plain)
