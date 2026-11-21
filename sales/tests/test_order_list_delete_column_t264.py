"""T-264（使用者 2026-11-21）：全部訂單的「刪除訂單」移開，離「訂單總覽」遠一點免得誤觸。

電腦版表格：原本放在第一欄日期底下、緊貼「訂單總覽」；改到每列最右邊的獨立欄（淨利之後），
「訂單總覽」留在第一欄，沒有刪除權限的帳號不多出空白欄或表頭。
手機卡片：原本在左欄資料下方；改到卡片最下面靠右、自成一列（order-row-footer），
「訂單總覽」仍在右上角狀態下方，沒有刪除權限時整列不出現。
"""
from html.parser import HTMLParser
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import SalesOrder, VehicleColor, VehicleModel


class DesktopTable(HTMLParser):
    """只收電腦版表格（inventory-table--fit）的表頭與每列儲存格的純文字與原始 HTML 位置。"""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.head, self.rows = [], []
        self.section = self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and "inventory-table--fit" in (attrs.get("class") or ""):
            self.depth = 1
            return
        if not self.depth:
            return
        if tag == "table":
            self.depth += 1
        elif tag in {"thead", "tbody"}:
            self.section = tag
        elif tag == "tr" and self.section == "tbody":
            self.rows.append([])
        elif tag in {"th", "td"}:
            self.cell = {"attrs": attrs, "text": "", "links": []}
            (self.head if self.section == "thead" else self.rows[-1]).append(self.cell)
        elif tag == "a" and self.cell is not None:
            self.cell["links"].append(attrs)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "table":
            self.depth -= 1
        elif tag in {"th", "td"}:
            self.cell = None

    def handle_data(self, data):
        if self.depth and self.cell is not None:
            self.cell["text"] += data


class OrderListDeleteColumnTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 只有 username 為 admin 的帳號是 root（sales.access.is_root），才有刪除與淨利。
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(brand="測試", name="T264 機種", energy_type="gas", displacement_cc=125)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def make_order(self, owner="刪除欄合成車主"):
        return SalesOrder.objects.create(
            owner_name=owner, owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=self.model, color=self.color)

    def staff(self, *grants):
        user = get_user_model().objects.create_user(f"t264-staff-{len(grants)}", password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        ScreenAccessGrant.objects.create(user=user, screen_key="orders", view=True)
        for key in grants:
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=True)
        return user

    def table(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(reverse("order_list"), {"tab": "all", **params})
        self.assertEqual(response.status_code, 200)
        parser = DesktopTable()
        parser.feed(response.content.decode())
        self.assertTrue(parser.head, "找不到電腦版表格")
        return parser

    @staticmethod
    def delete_links(cell):
        return [link for link in cell["links"] if "danger-outline" in (link.get("class") or "")]

    def assert_delete_is_last(self, user):
        orders = [self.make_order("刪除欄甲"), self.make_order("刪除欄乙")]
        table = self.table(user)
        self.assertEqual(table.head[-1]["text"].strip(), "刪除")
        self.assertEqual(table.head[-2]["text"].strip().split()[0][:2], "淨利")
        self.assertEqual(len(table.rows), len(orders))
        urls = {reverse("order_delete", args=[order.pk]) for order in orders}
        found = set()
        for row in table.rows:
            self.assertEqual(len(row), len(table.head))  # 表頭欄數＝每列欄數
            last = self.delete_links(row[-1])
            self.assertEqual(len(last), 1)
            self.assertEqual(row[-1]["text"].strip(), "刪除訂單")
            found.add(last[0]["href"])
            for cell in row[:-1]:
                self.assertEqual(self.delete_links(cell), [], "刪除鈕只能在最後一欄")
            first = row[0]
            self.assertTrue(any("order-overview-link" in (link.get("class") or "") for link in first["links"]),
                            "訂單總覽要留在第一欄")
            self.assertNotIn("刪除訂單", first["text"])
        self.assertEqual(found, urls)

    def test_admin_sees_delete_in_last_column_overview_stays_first(self):
        self.assert_delete_is_last(self.admin)

    def test_staff_with_delete_but_no_profit_still_has_delete_last(self):
        user = self.staff("order_delete")
        self.assert_delete_is_last(user)
        self.assertIn("未授權", self.table(user).head[-2]["text"])  # 淨利鎖住仍佔一欄，刪除在它後面

    def test_staff_without_delete_has_no_extra_column(self):
        self.make_order()
        admin_head = len(self.table(self.admin).head)
        table = self.table(self.staff())
        self.assertEqual(len(table.head), admin_head - 1)
        self.assertNotEqual(table.head[-1]["text"].strip(), "刪除")
        self.assertTrue(table.head[-1]["text"].strip().startswith("淨利"))
        for row in table.rows:
            self.assertEqual(len(row), len(table.head))
            for cell in row:
                self.assertEqual(self.delete_links(cell), [])
        self.assertTrue(any("order-overview-link" in (link.get("class") or "") for link in table.rows[0][0]["links"]))

    def test_empty_row_colspan_matches_header(self):
        for user in (self.admin, self.staff()):
            table = self.table(user, q="查無此單的合成字串")
            self.assertEqual(len(table.rows), 1)
            self.assertEqual(table.rows[0][0]["attrs"].get("colspan"), str(len(table.head)))

    def card(self, user, order):
        self.client.force_login(user)
        html = self.client.get(reverse("order_list"), {"tab": "all"}).content.decode()
        cards = html[html.index('<div class="order-list order-sort-cards">'):]
        detail = reverse("order_detail", args=[order.pk])
        card = cards[cards.rindex('<div class="order-row order-row--detailed">', 0, cards.index(f'href="{detail}"')):]
        return html, card[:card.index('<div class="order-row order-row--detailed">', 1)] if card.count('<div class="order-row order-row--detailed">') > 1 else card[:card.index("<dialog")]

    def test_mobile_card_delete_is_last_row_after_overview(self):
        order = self.make_order("卡片刪除合成車主")
        html, card = self.card(self.admin, order)
        url = reverse("order_delete", args=[order.pk])
        button = f'<a class="button danger-outline small order-row-delete" href="{url}"'
        self.assertIn(f'<div class="order-row-footer">{button}', card)
        footer = card.index('<div class="order-row-footer">')
        # 刪除在卡片最後：在左欄資料、右上角「訂單總覽」與箭頭之後，且不在左欄或狀態欄裡面
        main = card[card.index('<div class="order-main">'):card.index('<span class="order-row-status">')]
        status = card[card.index('<span class="order-row-status">'):card.index('<a class="chevron"')]
        self.assertNotIn("order-row-delete", main)
        self.assertNotIn("order-row-delete", status)
        self.assertIn("order-card-overview", status)
        self.assertLess(card.index("order-card-overview"), footer)
        self.assertLess(card.index('<a class="chevron"'), footer)
        self.assertNotIn("<a ", card[card.index("</div>", footer):])  # 刪除列之後卡片裡沒有其他可點的連結
        self.assertEqual(html.count(f'href="{url}"'), 2)  # 電腦版表格最後一欄＋手機卡片各一個

    def test_mobile_card_without_delete_has_no_footer(self):
        order = self.make_order("卡片無刪除合成車主")
        html, card = self.card(self.staff(), order)
        self.assertNotIn("order-row-footer", html)
        self.assertNotIn("order-row-delete", html)
        self.assertIn("order-card-overview", card)

    def test_mobile_footer_style_has_44px_touch_target(self):
        from django.conf import settings
        css = (Path(settings.BASE_DIR) / "static" / "css" / "order-list-delete.css").read_text(encoding="utf-8")
        self.assertIn(".order-row-footer .order-row-delete { min-height: 44px;", css)
        self.assertIn("grid-column: 2 / -1;", css)
        self.assertIn("justify-content: flex-end;", css)
