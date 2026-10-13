"""1.74.0：訂單檔案同步到 NAS（車型／年／月／車行_車主_車型_訂單編號）。"""
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from sales.models import OrderArchiveRecord, SalesOrder
from sales.services.order_archive import order_folder, sync_order
from sales.tests import test_order_intake as intake_fixtures


class OrderArchiveTests(TestCase):
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    setUp_intake = intake_fixtures.OrderIntakeTests.setUp

    def setUp(self):
        self.setUp_intake()
        nas = tempfile.TemporaryDirectory()
        self.addCleanup(nas.cleanup)
        self.root = Path(nas.name)
        override = override_settings(ORDER_ARCHIVE_DIR=str(self.root))
        override.enable()
        self.addCleanup(override.disable)

    def create_order(self, **changes):
        from django.urls import reverse
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("order_create"), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        return SalesOrder.objects.latest("pk")

    def test_order_files_land_in_model_year_month_folder(self):
        order = self.create_order()
        order.signed_contract.save("contract.pdf", ContentFile(b"%PDF-contract"), save=True)
        folder = sync_order(order.pk)
        day = order.established_on or order.order_date
        model = order.vehicle_model.family.name if order.vehicle_model.family_id else order.vehicle_model.name
        expected = self.root / "DMIS訂單" / model / f"{day:%Y}" / f"{day:%m}" / f"馭盛_{order.owner_name}_{model}_{order.number}"
        self.assertEqual(folder, expected)
        names = sorted(path.name for path in expected.iterdir())
        self.assertEqual(names, ["車主證件反面.png", "車主證件正面.png", "車輛訂購單.pdf"])
        self.assertEqual((expected / "車輛訂購單.pdf").read_bytes(), b"%PDF-contract")
        record = OrderArchiveRecord.objects.get(order=order)
        self.assertEqual(record.folder, order_folder(order))
        self.assertFalse(record.last_error)

    def test_dealer_label_rename_moves_folder_and_keeps_manual_files(self):
        order = self.create_order(source_type="dealer", source=str(self.dealer.pk))
        first = sync_order(order.pk)
        self.assertTrue(first.name.startswith(f"{self.dealer.name}_"))
        (first / "人員自己放的.txt").write_text("keep", encoding="utf-8")
        SalesOrder.objects.filter(pk=order.pk).update(owner_name="改名車主")
        moved = sync_order(order.pk)
        self.assertIn("改名車主", moved.name)
        self.assertFalse(first.exists())
        self.assertTrue((moved / "人員自己放的.txt").exists(), "人員手動放的檔案跟著搬，不刪除")
        # 系統移除的檔案只刪系統放的那份。
        SalesOrder.objects.filter(pk=order.pk).update(id_back="")
        sync_order(order.pk)
        self.assertFalse((moved / "車主證件反面.png").exists())
        self.assertTrue((moved / "人員自己放的.txt").exists())

    def test_disabled_or_unreachable_nas_never_breaks_orders(self):
        order = self.create_order()
        with override_settings(ORDER_ARCHIVE_DIR=""):
            self.assertIsNone(sync_order(order.pk))
        with override_settings(ORDER_ARCHIVE_DIR=str(self.root / "斷線")):
            self.assertIsNone(sync_order(order.pk))
        self.assertIn("找不到 NAS 根目錄", OrderArchiveRecord.objects.get(order=order).last_error)

    def test_saving_order_schedules_sync_automatically(self):
        order = self.create_order()
        folder = self.root / order_folder(order)
        self.assertTrue((folder / "車主證件正面.png").exists(), "建立訂單後自動同步（無 Redis 時直接同步）")
