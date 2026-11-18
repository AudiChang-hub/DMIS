"""T-229：apply_inventory_color_codes 把台鈴歷史庫存車改指到同車型、同色碼的車色。"""
import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from sales.models import Store, VehicleColor, VehicleInventory, VehicleInventoryHistory, VehicleModel
from sales.tests.test_vehicle_color_code import make_order

SOLD = VehicleInventory.Status.SOLD


class ApplyInventoryColorCodesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.store = Store.objects.create(name="總店", code="MAIN")

        def model(brand, name, number):
            return VehicleModel.objects.create(brand=brand, name=name, model_number=number, energy_type="gas",
                                               model_year=2026, model_code="std", displacement_cc=125)

        cls.sui = model("SUZUKI", "SUI 125", "UC125")
        cls.swish = model("SUZUKI", "Swish 125", "UU125")
        cls.fun = model("eReady", "Fun", "EV062")
        cls.fun.energy_type = "electric"
        cls.fun.save()
        cls.gogoro = model("GOGORO", "EZZY", "GSDT")
        cls.white = VehicleColor.objects.create(vehicle_model=cls.sui, name="白", active=False)
        cls.parmesan = VehicleColor.objects.create(vehicle_model=cls.sui, name="帕瑪森白", code="W17")
        cls.titan = VehicleColor.objects.create(vehicle_model=cls.sui, name="鈦灰", code="GXT")
        cls.black = VehicleColor.objects.create(vehicle_model=cls.swish, name="黑", active=False)
        # T-227 後：同色碼的目錄名稱色停用、官網名稱色啟用。
        cls.double_black = VehicleColor.objects.create(vehicle_model=cls.swish, name="雙黑", code="YVB", active=False)
        cls.gloss_black = VehicleColor.objects.create(vehicle_model=cls.swish, name="亮光黑", code="YVB")
        cls.fun_white = VehicleColor.objects.create(vehicle_model=cls.fun, name="白", active=False)
        cls.fun_silver = VehicleColor.objects.create(vehicle_model=cls.fun, name="紅銀", code="T82")
        cls.gogoro_white = VehicleColor.objects.create(vehicle_model=cls.gogoro, name="白")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def vehicle(self, model, color, engine="", frame="", status=SOLD):
        return VehicleInventory.objects.create(vehicle_model=model, color=color, engine_number=engine,
                                               frame_number=frame, status=status,
                                               ownership_store=self.store, location_store=self.store)

    def mapping(self, rows):
        path = Path(self.tmp.name) / "mapping.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["車型", "引擎號碼", "顏色代碼", "廣告色"])
            writer.writerows(rows)
        return path

    def run_command(self, mapping, *extra):
        output = Path(self.tmp.name) / "preview.csv"
        out = StringIO()
        call_command("apply_inventory_color_codes", str(mapping), "--output", str(output), *extra, stdout=out)
        with output.open(encoding="utf-8-sig", newline="") as handle:
            preview = {int(row["庫存ID"]): row for row in csv.DictReader(handle)}
        return out.getvalue(), preview

    def build_fixture(self):
        vehicles = {
            "white": self.vehicle(self.sui, self.white, engine="DL01-117210"),
            "white2": self.vehicle(self.sui, self.white, engine="DL01-117211"),
            "black": self.vehicle(self.swish, self.black, engine="UU01-000001"),
            "double": self.vehicle(self.swish, self.double_black, engine="UU01-000002"),
            "fun": self.vehicle(self.fun, self.fun_white, frame="RFDEV062TLT000018"),
            "missing": self.vehicle(self.sui, self.white, engine="DL01-999999"),
            "coded_missing": self.vehicle(self.sui, self.titan, engine="DL01-888888"),
            "no_color": self.vehicle(self.sui, self.white, engine="DL01-117212"),
            "other_code": self.vehicle(self.sui, self.titan, engine="DL01-117213"),
            "wrong_model": self.vehicle(self.sui, self.white, engine="DL01-117214"),
            "gogoro": self.vehicle(self.gogoro, self.gogoro_white, engine="GSDT-1"),
        }
        mapping = self.mapping([
            ["SUZUKI SUI 125", "DL01 117210", "W17", "帕瑪森白"],
            ["SUZUKI SUI 125", "DL01117211", "W17", "帕瑪森白"],
            ["SUZUKI Swish 125", "UU01 000001", "YVB", "雙黑"],
            ["SUZUKI Swish 125", "UU01 000002", "YVB", "雙黑"],
            ["eReady Fun", "RFDEV062TLT000018", "T82", "紅銀"],
            ["SUZUKI SUI 125", "DL01 117212", "R44", "蒙地拿紅"],
            ["SUZUKI SUI 125", "DL01 117213", "W17", "帕瑪森白"],
            ["SUZUKI SALUTO 125", "DL01 117214", "W17", "帕瑪森白"],
            ["GOGORO EZZY", "GSDT 1", "W01", "白"],
        ])
        return vehicles, mapping

    def test_dry_run_lists_changes_and_unmatched_without_writing(self):
        vehicles, mapping = self.build_fixture()
        before_colors = VehicleColor.objects.count()
        out, preview = self.run_command(mapping)
        self.assertIn("dry-run：未寫入", out)
        self.assertEqual(VehicleInventory.objects.get(pk=vehicles["white"].pk).color_id, self.white.pk)
        self.assertFalse(VehicleInventoryHistory.objects.exists())
        self.assertEqual(VehicleColor.objects.count(), before_colors)
        self.assertNotIn(vehicles["gogoro"].pk, preview)
        row = preview[vehicles["white"].pk]
        self.assertEqual((row["原車色"], row["新車色"], row["色碼"], row["結果"]), ("白", "帕瑪森白 W17", "W17", "更新"))
        self.assertIn("台鈴庫存車 10 台：更新 5、不變 1、略過 4", out)
        self.assertIn("SUZUKI SUI 125 2026：白 → 帕瑪森白 W17：2 台", out)
        self.assertIn("SUZUKI Swish 125 2026：黑 → 亮光黑 YVB：1 台", out)
        self.assertIn("SUZUKI Swish 125 2026：雙黑 YVB → 亮光黑 YVB：1 台", out)
        self.assertIn("eReady Fun 2026：白 → 紅銀 T82：1 台", out)
        self.assertEqual(preview[vehicles["coded_missing"].pk]["結果"], "不變")
        self.assertEqual(preview[vehicles["missing"].pk]["略過原因"], "對應表查無此號碼")
        self.assertEqual(preview[vehicles["no_color"].pk]["略過原因"], "車型沒有這個色碼的車色：蒙地拿紅 R44")
        self.assertEqual(preview[vehicles["other_code"].pk]["略過原因"], "現車色已有其他色碼：GXT，對應表 W17")
        self.assertEqual(preview[vehicles["wrong_model"].pk]["略過原因"], "車型與對應表不符")
        self.assertIn("DL01-999999 白｜對應表查無此號碼", out)

    def test_apply_repoints_vehicles_logs_history_and_is_idempotent(self):
        vehicles, mapping = self.build_fixture()
        before_colors = VehicleColor.objects.count()
        out, _ = self.run_command(mapping, "--apply")
        self.assertIn("完成：庫存車改指車色 5 台", out)
        self.assertEqual(VehicleColor.objects.count(), before_colors)
        self.assertEqual(VehicleInventory.objects.get(pk=vehicles["white"].pk).color_id, self.parmesan.pk)
        self.assertEqual(VehicleInventory.objects.get(pk=vehicles["black"].pk).color_id, self.gloss_black.pk)
        self.assertEqual(VehicleInventory.objects.get(pk=vehicles["double"].pk).color_id, self.gloss_black.pk)
        self.assertEqual(VehicleInventory.objects.get(pk=vehicles["fun"].pk).color_id, self.fun_silver.pk)
        self.assertEqual(VehicleInventory.objects.get(pk=vehicles["fun"].pk).status, SOLD)
        history = VehicleInventoryHistory.objects.get(vehicle=vehicles["white"])
        self.assertEqual(history.changes, {"車色": {"before": "白", "after": "帕瑪森白 W17"}})
        self.assertIn("T-229", history.reason)
        self.assertEqual(VehicleInventoryHistory.objects.count(), 5)
        self.assertEqual(VehicleColor.objects.get(pk=self.double_black.pk).active, False)
        out, _ = self.run_command(mapping, "--apply")
        self.assertIn("更新 0、不變 6", out)
        self.assertEqual(VehicleInventoryHistory.objects.count(), 5)

    def test_same_code_tie_breaks_by_usage_then_skips(self):
        # 停用車型上兩個同色碼車色都停用時，用被指到較多次的那個；平手就略過。
        self.gloss_black.active = False
        self.gloss_black.save()
        target = self.vehicle(self.swish, self.black, engine="UU01-000003")
        self.vehicle(self.swish, self.gloss_black, engine="UU01-000099")
        mapping = self.mapping([["SUZUKI Swish 125", "UU01 000003", "YVB", "雙黑"]])
        _, preview = self.run_command(mapping)
        self.assertEqual(preview[target.pk]["新車色"], "亮光黑 YVB")
        self.vehicle(self.swish, self.double_black, engine="UU01-000098")
        _, preview = self.run_command(mapping)
        self.assertEqual(preview[target.pk]["略過原因"], "同車型有多個同色碼車色無法判斷：雙黑 YVB、亮光黑 YVB")

    def test_allocated_vehicle_follows_order_color(self):
        mismatch = self.vehicle(self.sui, self.white, engine="DL01-117220", status=VehicleInventory.Status.RESERVED)
        order = make_order(self.sui, self.white, allocated_vehicle=mismatch)
        aligned = self.vehicle(self.sui, self.white, engine="DL01-117221", status=VehicleInventory.Status.RESERVED)
        make_order(self.sui, self.parmesan, allocated_vehicle=aligned, owner_id_number="B123456789")
        mapping = self.mapping([
            ["SUZUKI SUI 125", "DL01 117220", "W17", "帕瑪森白"],
            ["SUZUKI SUI 125", "DL01 117221", "W17", "帕瑪森白"],
        ])
        _, preview = self.run_command(mapping, "--apply")
        self.assertEqual(preview[mismatch.pk]["略過原因"], f"已配訂單且訂單車色不同，由訂單處理：{order.number} 白")
        self.assertEqual(VehicleInventory.objects.get(pk=mismatch.pk).color_id, self.white.pk)
        self.assertEqual(VehicleInventory.objects.get(pk=aligned.pk).color_id, self.parmesan.pk)
