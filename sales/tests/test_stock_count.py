"""現有台數表（使用者 2026-11-03 簡報第 7 頁，口徑方案 A）：數字必須與車輛庫存「現有庫存」的篩選結果一致。"""
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from sales.models import SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel
from sales.services.stock_count import CURRENT_STATUSES, build_stock_count

Status = VehicleInventory.Status


class StockCountTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="counter", password="test-pass-123")
        self.store = Store.objects.create(name="總店", code="HQ")
        self.dealer = SalesSource.objects.create(name="車行甲", source_type=SalesSource.SourceType.DEALER)
        self.serial = 0
        self.uc = self.model("SUZUKI", "Address 125", "UC125DA")
        # 同一原廠型號的第二個年份版本：車色依名稱合併。
        self.uc_2025 = self.model("SUZUKI", "Address 125", "UC125DA", year=2025)
        self.gsx = self.model("SUZUKI", "GSX-R150", "GSX-R150")
        self.ev = self.model("eReady", "Run 60", "EV060L", energy=VehicleModel.EnergyType.ELECTRIC)
        self.old = self.model("SUZUKI", "舊車款", "UZ100", active=False)
        self.red = self.color(self.uc, "紅")
        self.grey = self.color(self.uc, "灰")
        self.grey_2025 = self.color(self.uc_2025, "灰")
        self.brown = self.color(self.uc, "棕", active=False)
        self.gsx_black = self.color(self.gsx, "黑")
        self.ev_white = self.color(self.ev, "白")
        self.color(self.old, "白")

        self.vehicle(self.uc, self.red)
        self.vehicle(self.uc, self.grey)
        self.vehicle(self.uc, self.grey, current_dealer=self.dealer)
        self.vehicle(self.uc_2025, self.grey_2025, status=Status.RESERVED)
        self.vehicle(self.uc, self.grey, status=Status.CONDITION_ISSUE)
        self.vehicle(self.gsx, self.gsx_black, current_dealer=self.dealer, status=Status.RESERVED)
        for status in (Status.SOLD, Status.DELIVERED, Status.TRANSFERRED_OUT, Status.INACTIVE):
            self.vehicle(self.uc, self.red, status=status)
            self.vehicle(self.ev, self.ev_white, status=status, current_dealer=self.dealer)
        self.client.force_login(self.user)

    def model(self, brand, name, number, year=2026, energy=VehicleModel.EnergyType.GAS, active=True):
        return VehicleModel.objects.create(
            brand=brand, name=name, model_number=number, model_year=year, energy_type=energy,
            displacement_cc=125 if energy == VehicleModel.EnergyType.GAS else None, active=active,
        )

    def color(self, model, name, active=True):
        return VehicleColor.objects.create(vehicle_model=model, name=name, active=active)

    def vehicle(self, model, color, status=Status.AVAILABLE, current_dealer=None, location_store=None):
        self.serial += 1
        identifier = {"engine_number": f"ENG-{self.serial}"} if model.energy_type == VehicleModel.EnergyType.GAS else {"frame_number": f"FRM-{self.serial}"}
        return VehicleInventory.objects.create(
            vehicle_model=model, color=color, ownership_store=self.store, location_store=location_store or self.store,
            status=status, current_dealer=current_dealer, **identifier,
        )

    def rows(self, data=None):
        data = data or build_stock_count()
        return {
            (group.code, row.name): row
            for block in data["blocks"] for group in block.groups for row in group.rows
        }

    def inventory_count(self, **params):
        response = self.client.get(reverse("inventory_list"), params)
        return response.context["page_obj"].paginator.count

    def test_current_statuses_match_inventory_current_scope(self):
        self.assertEqual(set(CURRENT_STATUSES), {Status.AVAILABLE, Status.RESERVED, Status.CONDITION_ISSUE})
        data = build_stock_count()
        self.assertEqual(data["totals"]["total"], self.inventory_count())
        self.assertEqual(data["totals"]["total"], 6)
        self.assertEqual(data["totals"]["dealer"], 2)
        self.assertEqual(data["totals"]["store"], 4)
        self.assertEqual(data["totals"]["reserved"], 2)
        self.assertEqual(data["totals"]["issue"], 1)

    def test_each_color_matches_inventory_filter(self):
        data = build_stock_count()
        dealer_location = f"dealer-{self.dealer.pk}"
        for block in data["blocks"]:
            for group in block.groups:
                for row in group.rows:
                    params = {"brand": group.brand, "vehicle_family": sorted(group.family_ids), "color": row.name}
                    with self.subTest(code=group.code, color=row.name):
                        self.assertEqual(row.total, self.inventory_count(**params))
                        self.assertEqual(row.dealer, self.inventory_count(**params, location=dealer_location))
                        self.assertEqual(row.store, self.inventory_count(**params, location="store"))

    def test_versions_merge_by_model_number_and_zero_colors_listed(self):
        rows = self.rows()
        grey = rows[("UC125DA", "灰")]
        # 2026 版：本店 1、車行 1、車況異常 1；2025 版：已配車 1 → 合計 4，兩版本只列一列。
        self.assertEqual((grey.total, grey.dealer, grey.reserved, grey.issue), (4, 1, 1, 1))
        self.assertEqual([name for code, name in rows if code == "UC125DA"].count("灰"), 1)
        self.assertEqual(rows[("UC125DA", "紅")].total, 1)  # 已售出／已交車／已調出／停用都不算
        white = rows[("EV060L", "白")]
        self.assertEqual((white.total, white.dealer, white.active), (0, 0, True))

    def test_locations_list_store_then_dealers_with_counts(self):
        """庫位（T-115）：不在車行的寫實際存放門市，門市依主檔順序在前；車行依台數多到少；只算現有庫存，0 台留空。"""
        other = SalesSource.objects.create(name="旭昶", source_type=SalesSource.SourceType.DEALER)
        yongzhan = Store.objects.create(name="永湛", code="YZ")
        Store.objects.create(name="馭盛", code="YS")  # 沒有車的門市不列
        self.vehicle(self.uc, self.grey, current_dealer=other)
        self.vehicle(self.uc, self.grey, current_dealer=other)
        self.vehicle(self.uc, self.grey, current_dealer=other, status=Status.SOLD)
        self.vehicle(self.uc, self.grey, location_store=yongzhan)
        self.vehicle(self.uc, self.grey, location_store=yongzhan, status=Status.DELIVERED)
        rows = self.rows()
        grey = rows[("UC125DA", "灰")]
        store_counts = {"總店": 3, "永湛": 1}
        stores = [(name, store_counts[name], False) for name in Store.objects.values_list("name", flat=True) if name in store_counts]
        self.assertEqual(grey.locations, stores + [("旭昶", 2, True), ("車行甲", 1, True)])
        self.assertEqual(grey.location_text, "、".join(f"{name} {count}" for name, count, _ in grey.locations))
        self.assertNotIn("本店", grey.location_text)
        self.assertEqual(grey.dealer, 3)  # 「車行」欄口徑不變
        self.assertEqual(sum(count for _, count, _ in grey.locations), grey.total)
        self.assertEqual(rows[("GSX-R150", "黑")].location_text, "車行甲 1")
        self.assertEqual(rows[("EV060L", "白")].locations, [])  # 已售出等放在車行的車不算，0 台留空

    def test_location_counts_match_inventory_location_filter(self):
        other = SalesSource.objects.create(name="旭昶", source_type=SalesSource.SourceType.DEALER)
        self.vehicle(self.uc, self.red, current_dealer=other)
        self.vehicle(self.uc, self.red, location_store=Store.objects.create(name="永湛", code="YZ"))
        dealer_ids = {self.dealer.name: self.dealer.pk, other.name: other.pk}
        for block in build_stock_count()["blocks"]:
            for group in block.groups:
                for row in group.rows:
                    params = {"brand": group.brand, "vehicle_family": sorted(group.family_ids), "color": row.name}
                    with self.subTest(code=group.code, color=row.name):
                        # 庫存頁的「本店」篩選＝不在車行；各門市台數加總要對得上。
                        in_stores = sum(count for _, count, at_dealer in row.locations if not at_dealer)
                        self.assertEqual(in_stores, self.inventory_count(**params, location="store"))
                    for place, count, at_dealer in row.locations:
                        if at_dealer:
                            with self.subTest(code=group.code, color=row.name, place=place):
                                self.assertEqual(count, self.inventory_count(**params, location=f"dealer-{dealer_ids[place]}"))

    def test_page_shows_location_column_and_inline_copy(self):
        response = self.client.get(reverse("inventory_stock_count"), {"brand": "SUZUKI"})
        self.assertContains(response, '<th scope="col" class="stock-loc-col">庫位</th>', html=True)
        content = response.content.decode()
        self.assertIn('<span class="stock-loc is-dealer">車行甲<b>1</b></span>', content)
        self.assertIn('<span class="stock-loc">總店<b>3</b></span>', content)
        self.assertNotIn('<span class="stock-loc">本店', content)
        self.assertIn('stock-locs stock-locs--inline', content)

    def test_discontinued_marks_and_hides_inactive_models_without_stock(self):
        rows = self.rows()
        self.assertFalse(rows[("UC125DA", "棕")].active)
        self.assertNotIn(("UZ100", "白"), rows)
        self.vehicle(self.old, self.old.colors.get())
        rows = self.rows()
        self.assertEqual(rows[("UZ100", "白")].total, 1)
        self.assertFalse(rows[("UZ100", "白")].active)

    def test_blocks_split_by_brand_and_category(self):
        titles = [block.title for block in build_stock_count()["blocks"]]
        self.assertIn("SUZUKI 速克達", titles)
        self.assertIn("SUZUKI 擋車", titles)
        self.assertIn("eReady 白牌電車", titles)

    def test_brand_filter_limits_blocks_and_totals(self):
        data = build_stock_count("ereADY")
        self.assertEqual(data["selected_brand"], "eReady")
        self.assertEqual([block.brand for block in data["blocks"]], ["eReady"])
        self.assertEqual(data["totals"]["total"], 0)
        self.assertEqual({item["value"]: item["total"] for item in data["brands"]}, {"SUZUKI": 6, "eReady": 0})
        unknown = build_stock_count("不存在")
        self.assertEqual(unknown["selected_brand"], "")
        self.assertEqual(unknown["totals"]["total"], 6)

    def test_page_renders_counts_links_and_discontinued(self):
        response = self.client.get(reverse("inventory_stock_count"))
        self.assertContains(response, "<h1>現有台數表</h1>", html=True)
        self.assertContains(response, 'data-stock-total>6<')
        self.assertContains(response, "不生產")
        content = response.content.decode()
        self.assertIn(f"{reverse('inventory_list')}?brand=SUZUKI&amp;vehicle_family=", content)

    def test_export_button_follows_export_permission(self):
        url = reverse("inventory_stock_count_export")
        self.assertNotContains(self.client.get(reverse("inventory_stock_count")), url)
        root = get_user_model().objects.create_superuser(username="admin", password="test-pass-123")
        self.client.force_login(root)
        self.assertContains(self.client.get(reverse("inventory_stock_count"), {"brand": "SUZUKI"}), f"{url}?brand=SUZUKI")

    def test_only_stock_hides_zero_rows(self):
        response = self.client.get(reverse("inventory_stock_count"), {"show": "stock"})
        groups = [group for block in response.context["blocks"] for group in block.visible_groups]
        self.assertTrue(all(row.total for group in groups for row in group.visible_rows))
        self.assertNotIn("EV060L", [group.code for group in groups])
        self.assertNotIn("eReady", [block.brand for block in response.context["blocks"]])
        self.assertEqual(response.context["totals"]["total"], 6)

    def test_inventory_page_links_to_stock_count(self):
        self.assertContains(self.client.get(reverse("inventory_list")), reverse("inventory_stock_count"))

    def test_export_matches_page(self):
        response = self.client.get(reverse("inventory_stock_count_export"), {"brand": "SUZUKI"})
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        sheet = load_workbook(BytesIO(response.content)).active
        values = [[cell.value for cell in row] for row in sheet.iter_rows()]
        self.assertIn("現有台數表（SUZUKI）", values[0][0])
        grey = next(row for row in values if row[2] == "灰")
        self.assertEqual(grey[3:5], [4, 1])
        self.assertEqual(grey[5], "總店 3、車行甲 1")
        self.assertIn("已配車 1", grey[6])
        brown = next(row for row in values if row[2] == "棕")
        self.assertIsNone(brown[5])
        self.assertEqual(brown[6], "不生產")
        self.assertIn("庫位", next(row for row in values if row[0] == "車種型號"))
        total = next(row for row in values if row[0] == "總計")
        self.assertEqual(total[3:5], [6, 2])
        self.assertFalse(any(row[0] == "eReady 白牌電車" for row in values))

    def test_mobile_styles_keep_compact_table_and_44px_targets(self):
        css = Path("static/css/stock-count.css").read_text(encoding="utf-8")
        self.assertIn(".inventory-table.stock-count-table thead { display: table-header-group; }", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("@container (max-width: 300px)", css)
        self.assertIn(".inventory-table.stock-count-table .stock-loc-col { display: none; }", css)
