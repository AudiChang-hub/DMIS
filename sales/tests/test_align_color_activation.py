"""align_color_activation（T-227）：車色啟用狀態對齊原廠官網、目錄名稱色統一到官網名稱。"""
import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from sales.models import (
    OrderChange, SalesOrder, Store, VehicleColor, VehicleInventory, VehicleInventoryHistory, VehicleModel,
)
from sales.tests.test_vehicle_color_code import make_order

COLOR_HEADER = ["車型ID", "車型", "車色", "新建", "啟用", "色碼", "照片來源", "統一到"]
ACTOR = "PM（使用者指示）"


class AlignColorActivationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.store = Store.objects.create(name="對齊店", code="T227")
        cls.swish = VehicleModel.objects.create(brand="SUZUKI", name="Swish 125", model_number="UG125DA",
                                                energy_type="gas", model_year=2026)
        cls.glossy = VehicleColor.objects.create(vehicle_model=cls.swish, name="亮光黑")
        cls.double = VehicleColor.objects.create(vehicle_model=cls.swish, name="雙黑", code="YVB", active=False)
        cls.generic = VehicleColor.objects.create(vehicle_model=cls.swish, name="黑")
        cls.belt = VehicleModel.objects.create(brand="eReady", name="70 Belt", model_number="EV070V",
                                               energy_type="electric", model_year=2023)
        cls.belt_white = VehicleColor.objects.create(vehicle_model=cls.belt, name="白")
        cls.aurora = VehicleColor.objects.create(vehicle_model=cls.belt, name="極光白", code="W14", active=False)
        VehicleColor.objects.filter(pk=cls.belt_white.pk).update(catalog_image="catalog/colors/white.png")
        cls.gogoro = VehicleModel.objects.create(brand="GOGORO", name="EZZY", energy_type="electric")
        cls.gogoro_white = VehicleColor.objects.create(vehicle_model=cls.gogoro, name="白")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, header, rows):
        path = Path(self.tmp.name) / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def plan_rows(self):
        return [
            [self.swish.pk, "SUZUKI Swish 125 UG125DA 2026", "亮光黑", "", "是", "YVB", "", ""],
            [self.swish.pk, "SUZUKI Swish 125 UG125DA 2026", "雙黑", "", "否", "", "", "亮光黑"],
            [self.swish.pk, "SUZUKI Swish 125 UG125DA 2026", "黑", "", "否", "", "", ""],
            [self.belt.pk, "eReady 70 Belt EV070V 2023", "白", "", "否", "", "", ""],
            [self.belt.pk, "eReady 70 Belt EV070V 2023", "極光白", "", "是", "", "白", ""],
            [self.belt.pk, "eReady 70 Belt EV070V 2023", "午夜黑", "是", "是", "YVB", "", ""],
        ]

    def run_command(self, rows, *extra, vehicles=None):
        plan = self.write("plan.csv", COLOR_HEADER, rows)
        output = Path(self.tmp.name) / "preview.csv"
        args = [str(plan), "--output", str(output), *extra]
        if vehicles is not None:
            args += ["--vehicles", str(self.write("vehicles.csv", ["引擎／車身號碼", "車型ID", "改成車色"], vehicles))]
        out = StringIO()
        call_command("align_color_activation", *args, stdout=out)
        with output.open(encoding="utf-8-sig", newline="") as handle:
            return out.getvalue(), list(csv.DictReader(handle))

    def fixture(self):
        orders = [make_order(self.swish, self.double), make_order(self.swish, self.double)]
        sold = VehicleInventory.objects.create(vehicle_model=self.swish, color=self.double, engine_number="DL03-100113",
                                               ownership_store=self.store, location_store=self.store,
                                               status=VehicleInventory.Status.SOLD)
        allocated = VehicleInventory.objects.create(vehicle_model=self.swish, color=self.double,
                                                    engine_number="DL03-100114", ownership_store=self.store,
                                                    location_store=self.store)
        orders.append(make_order(self.swish, self.double, allocated_vehicle=allocated))
        stray = VehicleInventory.objects.create(vehicle_model=self.belt, color=self.belt_white,
                                                frame_number="RFDEV070VTT000001", ownership_store=self.store,
                                                location_store=self.store)
        return orders, sold, allocated, stray

    def test_dry_run_previews_without_writing(self):
        orders, sold, allocated, stray = self.fixture()
        out, preview = self.run_command(self.plan_rows(), vehicles=[["RFDEV070VTT000001", self.belt.pk, "午夜黑"]])
        self.assertIn("dry-run", out)
        self.assertIn("新建車色 1、啟用車色 1、停用車色 2、補色碼 1、搬照片 1、訂單改色 3、庫存車改色 3（要更新的項目共 12）", out)
        updated = [row for row in preview if row["結果"] == "更新"]
        self.assertIn(("訂單", orders[0].number, "雙黑 YVB→亮光黑"), [(r["類別"], r["對象"], r["內容"]) for r in updated])
        self.assertFalse(VehicleColor.objects.filter(name="午夜黑").exists())
        self.assertEqual(SalesOrder.objects.get(pk=orders[0].pk).color_id, self.double.pk)
        self.assertFalse(OrderChange.objects.filter(actor_name=ACTOR).exists())
        self.assertTrue(VehicleColor.objects.get(pk=self.glossy.pk).active)
        self.assertEqual(VehicleColor.objects.get(pk=self.belt_white.pk).catalog_image.name, "catalog/colors/white.png")

    def test_apply_aligns_colors_moves_records_and_photo(self):
        orders, sold, allocated, stray = self.fixture()
        out, _ = self.run_command(self.plan_rows(), "--apply",
                                  vehicles=[["RFDEV070VTT000001", self.belt.pk, "午夜黑"]])
        self.assertIn("完成", out)
        glossy = VehicleColor.objects.get(pk=self.glossy.pk)
        self.assertEqual((glossy.label, glossy.active), ("亮光黑 YVB", True))
        self.assertFalse(VehicleColor.objects.get(pk=self.double.pk).active)
        self.assertFalse(VehicleColor.objects.get(pk=self.generic.pk).active)
        self.assertFalse(VehicleColor.objects.get(pk=self.belt_white.pk).active)
        aurora = VehicleColor.objects.get(pk=self.aurora.pk)
        self.assertEqual((aurora.active, aurora.catalog_image.name), (True, "catalog/colors/white.png"))
        self.assertEqual(VehicleColor.objects.get(pk=self.belt_white.pk).catalog_image.name, "")
        midnight = VehicleColor.objects.get(vehicle_model=self.belt, name="午夜黑")
        self.assertEqual((midnight.code, midnight.active), ("YVB", True))
        for order in orders:
            self.assertEqual(SalesOrder.objects.get(pk=order.pk).color_id, glossy.pk)
            change = OrderChange.objects.get(order=order, actor_name=ACTOR)
            self.assertIn("T-227", change.reason)
            self.assertEqual(change.changes["車色"], {"before": "雙黑 YVB", "after": "亮光黑 YVB"})
        self.assertEqual(OrderChange.objects.get(order=orders[2], actor_name=ACTOR).changes["已配庫存車車色"],
                         {"before": "雙黑 YVB", "after": "亮光黑 YVB"})
        for vehicle, color in ((sold, glossy), (allocated, glossy), (stray, midnight)):
            vehicle.refresh_from_db()
            self.assertEqual(vehicle.color_id, color.pk)
            history = VehicleInventoryHistory.objects.get(vehicle=vehicle, actor_name=ACTOR)
            self.assertEqual(history.event_type, VehicleInventoryHistory.EventType.UPDATED)
            self.assertEqual(history.changes["車色"]["after"], color.label)
        self.assertIn(orders[2].number, VehicleInventoryHistory.objects.get(vehicle=allocated).reason)
        self.assertIn("零件目錄", VehicleInventoryHistory.objects.get(vehicle=stray).reason)

    def test_apply_twice_is_idempotent(self):
        self.fixture()
        vehicles = [["RFDEV070VTT000001", self.belt.pk, "午夜黑"]]
        self.run_command(self.plan_rows(), "--apply", vehicles=vehicles)
        out, preview = self.run_command(self.plan_rows(), vehicles=vehicles)
        self.assertIn("要更新的項目共 0", out)
        self.assertFalse([row for row in preview if row["結果"] == "更新"])
        self.run_command(self.plan_rows(), "--apply", vehicles=vehicles)
        self.assertEqual(OrderChange.objects.filter(actor_name=ACTOR).count(), 3)
        self.assertEqual(VehicleInventoryHistory.objects.filter(actor_name=ACTOR).count(), 3)
        self.assertEqual(VehicleColor.objects.filter(vehicle_model=self.belt, name="午夜黑").count(), 1)

    def assert_refused(self, rows, message):
        with self.assertRaisesMessage(CommandError, message):
            self.run_command(rows, "--apply")
        self.assertTrue(VehicleColor.objects.get(pk=self.generic.pk).active)
        self.assertFalse(OrderChange.objects.filter(actor_name=ACTOR).exists())

    def test_model_text_mismatch_is_refused(self):
        rows = self.plan_rows()
        rows[0][1] = "SUZUKI Swish 125 UG125DA 2025"
        self.assert_refused(rows, "跟計畫的「SUZUKI Swish 125 UG125DA 2025」不符")

    def test_other_brand_is_refused(self):
        self.assert_refused(self.plan_rows() + [[self.gogoro.pk, "", "白", "", "否", "", "", ""]], "不是 SUZUKI／eReady")

    def test_code_conflict_is_refused(self):
        rows = self.plan_rows() + [[self.belt.pk, "", "極光白", "", "", "W99", "", ""]]
        self.assert_refused(rows[:4] + rows[5:], "已有色碼 W14，計畫是 W99")

    def test_active_model_left_without_active_color_is_refused(self):
        rows = [
            [self.swish.pk, "", "亮光黑", "", "否", "", "", ""],
            [self.swish.pk, "", "黑", "", "否", "", "", ""],
        ]
        self.assert_refused(rows, "照計畫會沒有任何啟用車色")

    def test_missing_color_without_create_is_refused(self):
        self.assert_refused([[self.belt.pk, "", "馬丁綠", "", "是", "N36", "", ""]], "沒有「馬丁綠」")

    def test_photo_target_with_other_image_is_not_overwritten(self):
        VehicleColor.objects.filter(pk=self.aurora.pk).update(catalog_image="catalog/colors/aurora.png")
        with self.assertRaisesMessage(CommandError, "已有其他照片"):
            self.run_command(self.plan_rows(), "--apply")
        self.assertTrue(VehicleColor.objects.get(pk=self.generic.pk).active)
        self.assertEqual(VehicleColor.objects.get(pk=self.belt_white.pk).catalog_image.name, "catalog/colors/white.png")

    def test_deactivating_color_with_stock_warns(self):
        VehicleInventory.objects.create(vehicle_model=self.swish, color=self.generic, engine_number="DL03-200000",
                                        ownership_store=self.store, location_store=self.store)
        out, _ = self.run_command(self.plan_rows())
        self.assertIn("「黑」停用後還有 1 台在庫車", out)
