"""車色色碼（T-223）：欄位、顯示「名稱 色碼」、機種與售價可編輯、apply_color_codes 指令。"""
import csv
import tempfile
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderChange, SalesOrder, Store, VehicleColor,
    VehicleInventory, VehicleModel,
)
from sales.services.order_search import build_order_search_payload
from sales.services.vehicle_model_copy import execute_new_year


def make_order(model, color, **kwargs):
    fields = dict(
        source_type="store", order_date=date(2026, 9, 1), owner_type="local", owner_name="色碼測試",
        owner_id_number="A123456789", owner_phone="0912345678", owner_address="測試地址",
        vehicle_model=model, color=color, vehicle_price=Decimal("79800"), plate_insurance_fee=Decimal("2350"),
        payment_type="cash", delivery_method="store_pickup",
    )
    fields.update(kwargs)
    order = SalesOrder(**fields)
    order.calculated_balance = order.calculate_balance()
    order.actual_balance = order.calculated_balance
    order.save()
    return order


class ColorCodeDisplayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", model_number="UC125", energy_type="gas",
                                                model_year=2026, model_code="drum", displacement_cc=125)
        cls.coded = VehicleColor.objects.create(vehicle_model=cls.model, name="帕瑪森白", code="W17")
        cls.plain = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_label_shows_code_only_when_present(self):
        self.assertEqual(self.coded.label, "帕瑪森白 W17")
        self.assertEqual(self.plain.label, "白")
        self.assertEqual(VehicleColor.objects.get(pk=self.plain.pk).code, "")

    def test_order_detail_and_list_show_name_and_code(self):
        order = make_order(self.model, self.coded)
        self.assertContains(self.client.get(reverse("order_detail", args=[order.pk])), "帕瑪森白 W17")
        self.assertContains(self.client.get(reverse("order_list")), "帕瑪森白 W17")
        plain_order = make_order(self.model, self.plain)
        response = self.client.get(reverse("order_detail", args=[plain_order.pk]))
        self.assertContains(response, "<strong>白</strong>", html=True)

    def test_color_options_api_and_search_payload_use_label(self):
        response = self.client.get(reverse("vehicle_colors"), {"model": self.model.pk})
        self.assertCountEqual(response.json()["results"], [
            {"id": self.plain.pk, "name": "白"}, {"id": self.coded.pk, "name": "帕瑪森白 W17"},
        ])
        order = make_order(self.model, self.coded)
        payload = build_order_search_payload(SalesOrder.objects.get(pk=order.pk))
        self.assertIn("帕瑪森白 W17", [item.get("value") for item in payload if item.get("label") == "車色"])

    def test_vehicle_model_form_edits_code(self):
        url = reverse("vehicle_model_edit", args=[self.model.pk])
        page = self.client.get(url)
        self.assertContains(page, 'name="colors-0-code"')
        form = page.context["form"]
        formset = page.context["color_formset"]
        data = {key: value for key, value in form.initial.items() if value is not None and not isinstance(value, (list, tuple))}
        data.update({"action": "save_model", "name": self.model.name, "brand": self.model.brand,
                     "model_number": self.model.model_number, "energy_type": "gas"})
        for name, field in form.fields.items():
            value = form.initial.get(name, field.initial)
            if value not in (None, "") and name not in data and not isinstance(value, (list, tuple)):
                data[name] = value
        data.update({"colors-TOTAL_FORMS": "2", "colors-INITIAL_FORMS": "2", "colors-MIN_NUM_FORMS": "0",
                     "colors-MAX_NUM_FORMS": "1000"})
        for index, color_form in enumerate(formset.forms):
            color = color_form.instance
            data.update({f"colors-{index}-id": color.pk, f"colors-{index}-name": color.name,
                         f"colors-{index}-code": " w 17 " if color.pk == self.plain.pk else color.code,
                         f"colors-{index}-active": "on"})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.code, "W17")

    def test_copy_to_new_year_keeps_code(self):
        execute_new_year(entries=[(self.model.pk, 2027)], effective_from=timezone.localdate(), datasets=[],
                         extras=["colors"], activate=False, actor=self.admin)
        new_model = VehicleModel.objects.get(name="SUI 125", model_year=2027)
        self.assertEqual(dict(new_model.colors.values_list("name", "code")), {"帕瑪森白": "W17", "白": ""})


class ApplyColorCodesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.store = Store.objects.create(name="色碼店", code="T223")
        cls.sui = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", model_number="UC125", energy_type="gas")
        cls.white = VehicleColor.objects.create(vehicle_model=cls.sui, name="白")
        cls.black = VehicleColor.objects.create(vehicle_model=cls.sui, name="黑", active=False)
        cls.fun = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV062", energy_type="electric")
        cls.fun_white = VehicleColor.objects.create(vehicle_model=cls.fun, name="白")
        cls.gogoro = VehicleModel.objects.create(brand="GOGORO", name="EZZY", energy_type="electric")
        cls.gogoro_white = VehicleColor.objects.create(vehicle_model=cls.gogoro, name="白")
        cls.batch = LegacyImportBatch.objects.create(
            import_type="operations", source_file=SimpleUploadedFile("t223.xlsx", b"x"), original_filename="t223.xlsx",
            file_sha256="0" * 64, file_size=1, uploaded_by="tester",
        )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rows = 0

    def legacy_order(self, model, color, identifier):
        order = make_order(model, color)
        self.rows += 1
        row = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=self.rows,
                                             fingerprint=f"{self.rows:064d}", action=LegacyImportRow.Action.CREATE,
                                             mapped_data={"identifier": identifier})
        LegacySalesSnapshot.objects.create(order=order, import_row=row, vehicle_identifier=identifier)
        return order

    def mapping(self, rows):
        path = Path(self.tmp.name) / "mapping.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["車型", "引擎號碼（電動車為車身號碼）", "顏色代碼", "廣告色", "廣告色來源", "網站目錄"])
            writer.writerows(rows)
        return path

    def run_command(self, mapping, *extra):
        output = Path(self.tmp.name) / "preview.csv"
        out = StringIO()
        call_command("apply_color_codes", str(mapping), "--output", str(output), *extra, stdout=out)
        with output.open(encoding="utf-8-sig", newline="") as handle:
            preview = {int(row["訂單ID"]): row for row in csv.DictReader(handle)}
        return out.getvalue(), preview

    def build_fixture(self):
        orders = {
            "new": self.legacy_order(self.sui, self.white, "DL01-117210"),
            "same_new": self.legacy_order(self.sui, self.white, "DL01 117211"),
            "fill": self.legacy_order(self.sui, self.white, "DL01-117212"),
            "fun": self.legacy_order(self.fun, self.fun_white, "RFDEV062TLT000018"),
            "gogoro": self.legacy_order(self.gogoro, self.gogoro_white, "RFDGSDTF0T0001180"),
            "missing": self.legacy_order(self.sui, self.white, "DL01-999999"),
            "nocode": self.legacy_order(self.fun, self.fun_white, "RFDEV062TNT000176"),
        }
        vehicle = VehicleInventory.objects.create(vehicle_model=self.sui, color=self.white, engine_number="DL01-117213",
                                                  ownership_store=self.store, location_store=self.store)
        orders["allocated"] = make_order(self.sui, self.white, allocated_vehicle=vehicle)
        mapping = self.mapping([
            ["SUZUKI SUI 125", "DL01 117210", "W17", "帕瑪森白", "網站目錄", "UC125"],
            ["SUZUKI SUI 125", "DL01 117211", "W17", "帕瑪森白", "網站目錄", "UC125"],
            ["SUZUKI SUI 125", "DL01 117212", "YVB", "黑", "AutoDMS", "UC125"],
            ["SUZUKI SUI 125", "DL01 117213", "W17", "帕瑪森白", "網站目錄", "UC125"],
            ["eReady Fun", "RFDEV062TLT000018", "T82", "紅銀", "AutoDMS", "EV062"],
            ["GOGORO EZZY", "RFDGSDTF0T0001180", "", "", "", ""],
            ["eReady Fun", "RFDEV062TNT000176", "", "", "", ""],
        ])
        return orders, mapping

    def test_dry_run_writes_preview_without_changes(self):
        orders, mapping = self.build_fixture()
        before_colors = VehicleColor.objects.count()
        out, preview = self.run_command(mapping)
        self.assertIn("dry-run：未寫入", out)
        self.assertEqual(VehicleColor.objects.count(), before_colors)
        self.assertFalse(OrderChange.objects.filter(actor_name="PM（使用者指示）").exists())
        self.assertEqual(SalesOrder.objects.get(pk=orders["new"].pk).color_id, self.white.pk)
        row = preview[orders["new"].pk]
        self.assertEqual((row["原車色"], row["新車色"], row["色碼"], row["車色處理"], row["結果"]),
                         ("白", "帕瑪森白", "W17", "新建（停用）", "更新"))
        self.assertEqual(preview[orders["fill"].pk]["車色處理"], "沿用（補色碼）")
        self.assertEqual(preview[orders["gogoro"].pk]["略過原因"], "非台鈴品牌")
        self.assertEqual(preview[orders["missing"].pk]["略過原因"], "對應表查無此號碼")
        self.assertEqual(preview[orders["nocode"].pk]["略過原因"], "查無色碼")
        self.assertEqual(preview[orders["allocated"].pk]["已配庫存車車色"], "不同：白（未改）")
        self.assertIn("更新 5", out)

    def test_apply_creates_inactive_colors_fills_codes_and_logs_changes(self):
        orders, mapping = self.build_fixture()
        out, _ = self.run_command(mapping, "--apply")
        self.assertIn("新建車色 2 個、補色碼 1 個、更新訂單 5 張", out)
        parmesan = VehicleColor.objects.get(vehicle_model=self.sui, name="帕瑪森白")
        self.assertEqual((parmesan.code, parmesan.active), ("W17", False))
        self.black.refresh_from_db()
        self.assertEqual((self.black.code, self.black.active), ("YVB", False))
        self.assertEqual(VehicleColor.objects.get(vehicle_model=self.fun, name="紅銀").code, "T82")
        self.white.refresh_from_db()
        self.assertEqual((self.white.code, self.white.active), ("", True))
        for key in ("new", "same_new", "allocated"):
            self.assertEqual(SalesOrder.objects.get(pk=orders[key].pk).color_id, parmesan.pk)
        self.assertEqual(SalesOrder.objects.get(pk=orders["fill"].pk).color_id, self.black.pk)
        for key in ("gogoro", "missing", "nocode"):
            self.assertEqual(SalesOrder.objects.get(pk=orders[key].pk).color_id, orders[key].color_id)
        vehicle = VehicleInventory.objects.get(engine_number="DL01-117213")
        self.assertEqual(vehicle.color_id, self.white.pk)
        change = OrderChange.objects.get(order=orders["new"], actor_name="PM（使用者指示）")
        self.assertIn("T-223", change.reason)
        self.assertEqual(change.changes, {"車色": {"before": "白", "after": "帕瑪森白 W17"}})
        self.assertEqual(OrderChange.objects.filter(actor_name="PM（使用者指示）").count(), 5)

    def test_apply_twice_is_idempotent(self):
        orders, mapping = self.build_fixture()
        self.run_command(mapping, "--apply")
        colors = list(VehicleColor.objects.order_by("pk").values_list("pk", "name", "code", "active"))
        out, preview = self.run_command(mapping, "--apply")
        self.assertIn("更新 0", out)
        self.assertEqual(preview[orders["new"].pk]["結果"], "不變")
        self.assertEqual(list(VehicleColor.objects.order_by("pk").values_list("pk", "name", "code", "active")), colors)
        self.assertEqual(OrderChange.objects.filter(actor_name="PM（使用者指示）").count(), 5)

    def test_conflicting_codes_are_skipped(self):
        first = self.legacy_order(self.sui, self.white, "DL02-1")
        second = self.legacy_order(self.sui, self.white, "DL02-2")
        coded = VehicleColor.objects.create(vehicle_model=self.sui, name="鈦灰", code="G27")
        third = self.legacy_order(self.sui, self.white, "DL02-3")
        mapping = self.mapping([
            ["SUZUKI SUI 125", "DL02-1", "N34", "盧卡綠", "", ""],
            ["SUZUKI SUI 125", "DL02-2", "T94", "盧卡綠", "", ""],
            ["SUZUKI SUI 125", "DL02-3", "G99", "鈦灰", "", ""],
        ])
        _, preview = self.run_command(mapping, "--apply")
        self.assertEqual(preview[first.pk]["略過原因"], "同車型同廣告色有多個色碼（N34、T94）")
        self.assertEqual(preview[second.pk]["略過原因"], "同車型同廣告色有多個色碼（N34、T94）")
        self.assertEqual(preview[third.pk]["略過原因"], "同名車色已有其他色碼 G27")
        self.assertFalse(VehicleColor.objects.filter(name="盧卡綠").exists())
        coded.refresh_from_db()
        self.assertEqual(coded.code, "G27")

    def test_corrected_identifier_uses_filled_row_over_blank_old_row(self):
        order = self.legacy_order(self.fun, self.fun_white, "RFDEV062TMT000176")
        LegacyImportRow.objects.filter(sales_snapshot__order=order).update(mapped_data={"identifier": "RFDEV062TNT000176"})
        mapping = self.mapping([
            ["eReady Fun", "RFDEV062TNT000176", "", "", "", ""],
            ["eReady Fun", "RFDEV062TMT000176", "W13", "盛夏白", "AutoDMS（車牌）＋網站色表", "EV062"],
        ])
        _, preview = self.run_command(mapping, "--apply")
        self.assertEqual((preview[order.pk]["新車色"], preview[order.pk]["色碼"], preview[order.pk]["結果"]),
                         ("盛夏白", "W13", "更新"))
        self.assertEqual(SalesOrder.objects.get(pk=order.pk).color.label, "盛夏白 W13")

    def test_model_mismatch_is_skipped(self):
        order = self.legacy_order(self.sui, self.white, "DL03-1")
        mapping = self.mapping([["SUZUKI Saluto 125", "DL03-1", "C11", "卡拉拉白", "", ""]])
        _, preview = self.run_command(mapping)
        self.assertEqual(preview[order.pk]["略過原因"], "車型與對應表不符")
