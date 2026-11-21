"""T-265（使用者 2026-11-21）：全部訂單的「刪除訂單」改成回收桶圖示鈕；電腦版「顏色」併進「機種」欄。

- 圖示鈕電腦版表格與手機卡片都改，保留 aria-label／title「刪除訂單」、紅色警示樣式與 44px 觸控區；
  位置與權限照 T-264（表格最後一欄、卡片最下面靠右）。
- 機種欄由上到下：機種名稱 → 引擎／車身號碼（未配車不輸出）→ 顏色，缺值不留空行；
  顏色排序改成機種表頭下方的小連結（比照姓名欄的「訂單編號排序」）。
- 手機卡片（使用者追加）：顏色也併到機種底下，排法同電腦版；卡片上原本獨立的「顏色」欄位拿掉。
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import SalesOrder, Store, VehicleColor, VehicleInventory, VehicleModel
from sales.tests.test_order_list_delete_column_t264 import DesktopTable


class OrderListIconAndColorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 只有 username 為 admin 的帳號是 root，才有刪除權限。
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.store = Store.objects.create(name="T265 測試店", code="T265")
        cls.model = VehicleModel.objects.create(brand="測試", name="T265 機種", energy_type="gas", displacement_cc=125)
        cls.white = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.black = VehicleColor.objects.create(vehicle_model=cls.model, name="黑")

    def make_order(self, owner, color, engine=None):
        vehicle = None
        if engine:
            vehicle = VehicleInventory.objects.create(
                vehicle_model=self.model, color=color, engine_number=engine,
                ownership_store=self.store, location_store=self.store, status=VehicleInventory.Status.RESERVED)
        return SalesOrder.objects.create(
            owner_name=owner, owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=self.model, color=color, allocated_vehicle=vehicle)

    def staff_without_delete(self):
        user = get_user_model().objects.create_user("t265-staff", password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        ScreenAccessGrant.objects.create(user=user, screen_key="orders", view=True)
        return user

    def page(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(reverse("order_list"), {"tab": "all", **params})
        self.assertEqual(response.status_code, 200)
        return response

    def table(self, html):
        parser = DesktopTable()
        parser.feed(html)
        self.assertTrue(parser.head, "找不到電腦版表格")
        return parser

    @staticmethod
    def column(table, label):
        return next(index for index, th in enumerate(table.head) if th["text"].strip().startswith(label))

    def test_delete_is_trash_icon_with_label_in_table_and_card(self):
        order = self.make_order("圖示合成車主", self.white)
        html = self.page(self.admin).content.decode()
        url = reverse("order_delete", args=[order.pk])
        icon_link = (f'href="{url}" aria-label="刪除訂單 {order.number}" title="刪除訂單">'
                     '<svg class="icon-trash" aria-hidden="true" focusable="false"')
        self.assertEqual(html.count(icon_link), 2)  # 電腦版表格＋手機卡片
        # 紅色警示樣式與位置照 T-264：表格是最後一欄，卡片是最下面的 footer
        self.assertIn(f'<td class="order-table-delete"><small><a class="button danger-outline small" {icon_link}', html)
        self.assertIn(f'<div class="order-row-footer"><a class="button danger-outline small order-row-delete" {icon_link}', html)
        # 畫面上只剩圖示：「刪除訂單」只留在螢幕報讀用的隱藏文字
        self.assertEqual(html.count('<span class="visually-hidden">刪除訂單</span></a>'), 2)
        table = self.table(html)
        self.assertEqual(table.head[-1]["text"].strip(), "刪除")
        self.assertEqual(table.rows[0][-1]["links"][0]["title"], "刪除訂單")

    def test_no_delete_permission_has_no_icon(self):
        self.make_order("無權限合成車主", self.white)
        html = self.page(self.staff_without_delete()).content.decode()
        self.assertNotIn("icon-trash", html)
        self.assertNotIn("order-row-footer", html)
        table = self.table(html)
        self.assertFalse(any(th["text"].strip() == "刪除" for th in table.head))
        for row in table.rows:
            self.assertEqual(len(row), len(table.head))

    def test_icon_button_keeps_44px_touch_target(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "order-list-delete.css").read_text(encoding="utf-8")
        self.assertIn(".order-sort-table td.order-table-delete .button { min-width: 44px; min-height: 44px; padding: 0; }", css)
        self.assertIn(".order-row-footer .order-row-delete { min-height: 44px; min-width: 44px; padding: 0;", css)

    def test_machine_cell_shows_name_number_then_color_without_blank_lines(self):
        allocated = self.make_order("配車合成車主", self.black, engine="ENG  0265")
        unallocated = self.make_order("未配車合成車主", self.white)
        html = self.page(self.admin).content.decode()
        table = self.table(html)
        machine = self.column(table, "機種")
        cells = {}
        for row in table.rows:
            owner = row[self.column(table, "姓名")]["text"]
            cells["配車" if "配車合成車主" in owner and "未" not in owner else "未配車"] = row[machine]
        # 原始 HTML 依序檢查：機種名稱 → 號碼 → 顏色
        start = html.index('<td class="order-table-machine">', html.index(allocated.number))
        cell = html[start:html.index("</td>", start)]
        name, number, color = cell.index("T265 機種"), cell.index("ENG  0265"), cell.index('class="order-machine-color"')
        self.assertLess(name, number)
        self.assertLess(number, color)
        self.assertIn('<small class="order-machine-color"><span class="visually-hidden">顏色：</span>黑</small>', cell)
        # 未配車：沒有號碼那一行，也沒有空的 small，顏色直接接在機種名稱下方
        start = html.index('<td class="order-table-machine">', html.index(unallocated.number))
        cell = html[start:html.index("</td>", start)]
        self.assertNotIn("order-vehicle-number", cell)
        self.assertIn('<small class="order-machine-color"><span class="visually-hidden">顏色：</span>白</small>', cell)
        self.assertNotRegex(cell, r"<small[^>]*>\s*</small>")
        self.assertIn("顏色：黑", cells["配車"]["text"])
        self.assertIn("顏色：白", cells["未配車"]["text"])

    def test_color_column_removed_and_columns_consistent(self):
        self.make_order("欄數合成車主", self.white)
        for user in (self.admin, self.staff_without_delete()):
            table = self.table(self.page(user).content.decode())
            labels = [th["text"].strip() for th in table.head]
            self.assertFalse(any(label.startswith("顏色") for label in labels), labels)
            self.assertEqual(len(labels), 10 if user == self.admin else 9)
            for row in table.rows:
                self.assertEqual(len(row), len(table.head))
            self.assertNotIn({"text": "白", "attrs": {}, "links": []}, table.rows[0])  # 沒有只放顏色的儲存格
        empty = self.table(self.page(self.admin, q="查無此單的合成字串").content.decode())
        self.assertEqual(empty.rows[0][0]["attrs"].get("colspan"), str(len(empty.head)))

    def test_color_sort_link_under_machine_header_still_sorts(self):
        white = self.make_order("白色合成車主", self.white)
        black = self.make_order("黑色合成車主", self.black)
        response = self.page(self.admin)
        table = self.table(response.content.decode())
        machine = table.head[self.column(table, "機種")]
        color_links = [link for link in machine["links"] if link.get("data-order-sort-key") == "color"]
        self.assertEqual(len(color_links), 1)
        self.assertIn("order-color-sort", color_links[0]["class"])
        self.assertIn("sort=color", color_links[0]["href"])
        self.assertIn("顏色排序", machine["text"])
        # 依顏色排序：白 → 黑 → 正序；反序時機種表頭標示 aria-sort
        ascending = [order.pk for order in self.page(self.admin, sort="color").context["orders"]]
        self.assertEqual(ascending, [black.pk, white.pk] if "黑" < "白" else [white.pk, black.pk])
        descending = self.page(self.admin, sort="-color")
        self.assertEqual([order.pk for order in descending.context["orders"]], list(reversed(ascending)))
        self.assertEqual(descending.context["sort_color_column"]["rank"], 1)
        table = self.table(descending.content.decode())
        self.assertEqual(table.head[self.column(table, "機種")]["attrs"].get("aria-sort"), "descending")
        self.assertIn("顏色 · 反序 · 1", table.head[self.column(table, "機種")]["text"])
        # 手機排序面板與已套用的排序標籤照舊有顏色
        html = descending.content.decode()
        self.assertIn("1. 顏色：反序", html)

    def card_machine(self, html, order):
        cards = html[html.index('<div class="order-list order-sort-cards">'):]
        card = cards[cards.rindex('<div class="order-row order-row--detailed">', 0, cards.index(order.number)):]
        start = card.index('<div class="order-fact order-fact--machine">')
        return card, card[start:card.index('<span class="order-fact', start)]  # 機種欄到下一個欄位為止

    def test_mobile_card_machine_shows_name_number_then_color(self):
        allocated = self.make_order("卡片配車合成車主", self.black, engine="CARD 0265")
        unallocated = self.make_order("卡片未配車合成車主", self.white)
        html = self.page(self.admin).content.decode()
        card, machine = self.card_machine(html, allocated)
        name, number, color = machine.index("T265 機種"), machine.index("CARD 0265"), machine.index('class="order-machine-color"')
        self.assertLess(name, number)
        self.assertLess(number, color)
        self.assertIn('<small class="order-machine-color"><span class="visually-hidden">顏色：</span>黑</small>', machine)
        # 卡片上原本獨立的「顏色」欄位拿掉，其他欄位照舊
        self.assertNotIn("<small>顏色</small>", card)
        for label in ("領牌日期", "訂單成立日期", "車號", "淨利", "車行", "備註"):
            self.assertIn(f"<small>{label}</small>", card)
        # 未配車：沒有號碼那一行、沒有空行，顏色直接接在機種名稱下方
        _, machine = self.card_machine(html, unallocated)
        self.assertNotIn("order-vehicle-number", machine)
        self.assertIn('<small class="order-machine-color"><span class="visually-hidden">顏色：</span>白</small>', machine)
        self.assertNotRegex(machine, r"<small[^>]*>\s*</small>")
        self.assertLess(machine.index("T265 機種"), machine.index('class="order-machine-color"'))
        self.assertNotIn("<small>顏色</small>", html[html.index('<div class="order-list order-sort-cards">'):])

    def test_mobile_card_color_style_and_tablet_grid(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "order-vehicle-number.css").read_text(encoding="utf-8")
        self.assertIn(".order-fact--machine .order-machine-color {", css)
        app = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")
        # 600–860px 卡片欄位一列排：少了顏色，欄寬比例跟著少一格
        self.assertIn("  grid-template-columns: 1.05fr .8fr .75fr .8fr .9fr 1.55fr;", app)
