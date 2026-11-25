"""T-317 B：車輛庫存列表 1280 寬不出現水平捲軸、「實際位置」可以打字篩選（使用者 2026-11-25 選 B）。

- 問題 1（併欄，11 欄→8 欄）：出廠年月併到進車日期下一行、品牌併到車型下一行（「SUZUKI · 白」）、
  車況併到狀態下面；進車日期改成 2026/11/14；品牌排序連結放在車型表頭第二行。
- 問題 2（專用位置選擇器）：按鈕與面板由 inventory-location.js 產生；每列原生 <select> 保留給沒有 JS 時用，
  伺服器端（T-308）不變，所以這裡只驗模板。
"""
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel


class InventoryListT317Tests(TestCase):
    def setUp(self):
        self.root = get_user_model().objects.create_superuser("admin", password="Local-t317-553!")
        self.client.force_login(self.root)
        self.store = Store.objects.create(name="馭盛", code="HQ")
        SalesSource.objects.create(name="示範車行甲", source_type=SalesSource.SourceType.DEALER)
        self.model = VehicleModel.objects.create(
            brand="SYM", name="JET SL 125", model_number="T317",
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125,
        )
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="消光黑")
        self.car = self.make_car("T317-0001", received_on=date(2026, 11, 4), manufactured_year_month="2026/09")
        self.reserved = self.make_car("T317-0002", status=VehicleInventory.Status.RESERVED)

    def make_car(self, engine, **fields):
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, engine_number=engine,
            ownership_store=self.store, location_store=self.store, **fields,
        )

    def page(self, **params):
        response = self.client.get(reverse("inventory_list"), params)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    @staticmethod
    def head(html):
        return html[html.index("<thead>"):html.index("</thead>")]

    def test_received_date_uses_slashes_and_carries_manufactured_month(self):
        html = self.page()
        self.assertIn(
            '<td data-label="進車日期／出廠" class="inventory-received-cell">2026/11/04<small class="inventory-cell-sub">出廠 2026/09</small></td>',
            html,
        )
        self.assertNotIn("2026年11月4日", html)
        self.assertNotIn('data-label="出廠年月"', html)
        self.assertIn('<small class="inventory-th-sub">／出廠</small></th>', self.head(html))

    def test_brand_sits_with_colour_under_model_and_stays_sortable(self):
        html = self.page()
        self.assertNotIn('data-label="品牌"', html)
        self.assertIn('<td data-label="車型／品牌・車色"><strong>JET SL 125</strong><span class="inventory-model-sub">SYM · <span>消光黑</span></span></td>', html)
        header = re.search(r'<th scope="col" aria-sort="none"><span class="inventory-sort-pair">(.*?)</th>', html, re.S).group(1)
        pair, second = header.split('<small class="inventory-th-sub">')
        self.assertIn("sort=model", pair)
        self.assertIn("sort=color", pair)
        self.assertNotIn("sort=brand", pair)
        self.assertIn('class="inventory-sort-link" href="', second)
        self.assertIn("sort=brand", second)
        # 用品牌排序時，合併欄的表頭標示排序方向；舊網址 sort=brand 照常可用。
        self.assertRegex(self.page(sort="brand"), r'<th scope="col" aria-sort="ascending"><span class="inventory-sort-pair">')

    def test_condition_merges_under_status(self):
        self.car.condition_note = "右側車殼刮傷"
        self.car.save(update_fields=["condition_note"])
        issue = self.make_car("T317-0003", status=VehicleInventory.Status.CONDITION_ISSUE, condition_note="待補漆")
        html = self.page()
        self.assertNotIn('data-label="車況"', html)
        self.assertIn('<small class="inventory-th-sub">／車況</small></th>', self.head(html))
        rows = {vehicle: re.search(rf'<tr[^>]*>(?:(?!</tr>).)*?{vehicle.identifier}.*?</tr>', html, re.S).group(0)
                for vehicle in (self.car, issue, self.reserved)}
        # 車況異常：膠囊縮短成「車況異常」，下面一行「暫停配車」，再下面是備註。
        self.assertIn(
            '<span class="status-pill status-condition_issue">車況異常</span><small class="inventory-status-hold">暫停配車</small>',
            rows[issue],
        )
        self.assertNotIn("車況異常（暫停配車）", html)
        self.assertIn('<small class="inventory-condition-note">待補漆</small>', rows[issue])
        self.assertNotIn("有備註", rows[issue])
        # 一般狀態但車況有備註：加「有備註」和備註。
        self.assertIn('<span class="inventory-condition has-note">有備註</span><small class="inventory-condition-note">右側車殼刮傷</small>', rows[self.car])
        # 車況正常：不另外顯示。
        self.assertNotIn("inventory-condition", rows[self.reserved])
        self.assertNotIn(">正常<", html)

    def test_columns_and_empty_row_span(self):
        html = self.page(q="沒有這台車")
        self.assertEqual(self.head(html).count('<th scope="col"'), 8)
        self.assertIn('<tr><td colspan="8">', html)
        for scope in ("history", "sold"):
            other = self.page(scope=scope, q="沒有這台車")
            self.assertEqual(self.head(other).count('<th scope="col"'), 6, scope)
            self.assertIn('<tr><td colspan="6">', other)

    def test_empty_row_span_without_transfer_out_column(self):
        viewer = get_user_model().objects.create_user("viewer", password="Local-t317-553!")
        UserAccessState.objects.create(user=viewer, configured=True)
        ScreenAccessGrant.objects.create(user=viewer, screen_key="inventory", view=True)
        self.client.force_login(viewer)
        html = self.page(q="沒有這台車")
        self.assertNotIn("data-transfer-out-table", html)
        self.assertEqual(self.head(html).count('<th scope="col"'), 7)
        self.assertIn('<tr><td colspan="7">', html)

    def test_row_actions_stay_text_buttons(self):
        html = self.page()
        self.assertIn(f'aria-label="調出 {self.car.identifier}">調出</button>', html)
        self.assertIn('title="已配給訂單，不能調出">已配車</button>', html)
        self.assertIn(f'href="{reverse("inventory_edit", args=[self.car.pk])}">查看／編輯</a>', html)
        self.assertNotIn("inventory-action-icon", html)

    def test_location_keeps_native_select_for_no_js_and_loads_picker(self):
        html = self.page()
        row = re.search(rf'<select id="inventory-location-{self.car.pk}"[^>]*>', html).group(0)
        self.assertIn('class="inventory-location__select" name="location"', row)
        self.assertNotIn("data-searchable-select", row)
        self.assertIn(f'aria-label="實際位置 {self.car.identifier}（選了就存）"', row)
        self.assertEqual(html.count('data-searchable-select="1"'), 4, "只有上方篩選用搜尋選單")
        self.assertIn('<script src="/static/js/inventory-location.js" defer></script>', html)
