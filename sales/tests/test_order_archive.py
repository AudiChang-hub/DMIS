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

    def test_archive_worker_can_read_media_and_write_nas(self):
        # 1.74.1：處理 archive 佇列的 search-worker 必須掛載系統檔案區（唯讀）與 NAS，否則讀不到原檔。
        import re
        base = Path("docker-compose.django.yml").read_text(encoding="utf-8")
        prod = Path("docker-compose.django.prod.yml").read_text(encoding="utf-8")
        pattern = re.compile(r"^  search-worker:\n(.*?)^  [a-z-]+:", re.S | re.M)
        worker = pattern.search(base).group(1)
        self.assertIn("archive", worker)
        self.assertIn(":/app/media:ro", worker)
        prod_worker = pattern.search(prod).group(1)
        self.assertIn(":/app/order-archive", prod_worker)

    def test_deleted_orders_move_out_of_model_tree_and_back_on_restore(self):
        # 1.74.2：回收區的訂單移到「_已刪除訂單」，不留在車型／年月目錄；還原後搬回原位。
        from django.utils import timezone
        order = self.create_order()
        active = sync_order(order.pk)
        SalesOrder.all_objects.filter(pk=order.pk).update(deleted_at=timezone.now())
        moved = sync_order(order.pk)
        self.assertEqual(moved.parent, self.root / "DMIS訂單" / "_已刪除訂單")
        self.assertFalse(active.exists())
        self.assertFalse(active.parent.exists(), "空的年月資料夾一併清掉")
        self.assertTrue((moved / "車主證件正面.png").exists())
        SalesOrder.all_objects.filter(pk=order.pk).update(deleted_at=None)
        self.assertEqual(sync_order(order.pk), active)
        self.assertFalse(moved.exists())

    def test_open_orders_get_folder_even_without_files(self):
        # 1.74.2：未結案訂單沒有檔案也建資料夾（黃康洺這類匯入舊單）；已結案或已取消且沒檔案的不建。
        order = self.create_order()
        SalesOrder.objects.filter(pk=order.pk).update(id_front="", id_back="")
        OrderArchiveRecord.objects.filter(order=order).delete()
        folder = sync_order(order.pk)
        self.assertTrue(folder.is_dir(), "沒有檔案的未結案訂單也有資料夾")
        for status in (SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED):
            closed = self.create_order()
            SalesOrder.objects.filter(pk=closed.pk).update(id_front="", id_back="", status=status)
            OrderArchiveRecord.objects.filter(order=closed).delete()
            self.assertIsNone(sync_order(closed.pk), status)

    def test_verify_command_reports_consistency(self):
        from io import StringIO
        from django.core.management import call_command
        order = self.create_order()
        sync_order(order.pk)
        out = StringIO()
        call_command("sync_order_archive", "--verify", stdout=out)
        self.assertIn("全部一致", out.getvalue())
        (self.root / order_folder(order) / "車主證件正面.png").unlink()
        out = StringIO()
        call_command("sync_order_archive", "--verify", stdout=out)
        self.assertIn("缺檔案 車主證件正面.png", out.getvalue())

    def test_full_sync_prunes_leftover_empty_folders_only(self):
        from io import StringIO
        from django.core.management import call_command
        order = self.create_order()
        sync_order(order.pk)
        leftover = self.root / "DMIS訂單" / "舊車型" / "2026" / "09"
        leftover.mkdir(parents=True)
        out = StringIO()
        call_command("sync_order_archive", stdout=out)
        self.assertFalse((self.root / "DMIS訂單" / "舊車型").exists())
        self.assertTrue((self.root / order_folder(order)).is_dir(), "有效訂單資料夾不受影響")
        self.assertIn("清除 3 個空資料夾", out.getvalue())
