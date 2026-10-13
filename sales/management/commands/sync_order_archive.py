"""把訂單檔案同步到 NAS（ORDER_ARCHIVE_DIR）；部署後補同步全部，或指定單號重做；--verify 只核對不寫入。"""
from django.core.management.base import BaseCommand, CommandError

from sales.models import OrderArchiveRecord, SalesOrder
from sales.services.order_archive import (
    ARCHIVE_FOLDER, archive_root, keeps_empty_folder, order_files, order_folder, sync_order,
)


class Command(BaseCommand):
    help = "依「車型／年／月／車行_車主_車型_訂單編號」把訂單檔案同步到 NAS。"

    def add_arguments(self, parser):
        parser.add_argument("numbers", nargs="*", help="只處理這些訂單編號；不填則處理全部訂單")
        parser.add_argument("--verify", action="store_true", help="只核對 NAS 與系統是否一致，不寫入")

    def handle(self, *args, numbers, verify, **options):
        root = archive_root()
        if root is None:
            raise CommandError("尚未設定 DMIS_ORDER_ARCHIVE_DIR，無法同步。")
        orders = SalesOrder.all_objects.order_by("pk")
        if numbers:
            orders = orders.filter(number__in=numbers)
        if verify:
            return self.verify(root, orders)
        synced = skipped = 0
        for order_id in orders.values_list("pk", flat=True).iterator():
            if sync_order(order_id):
                synced += 1
            else:
                skipped += 1
        self.stdout.write(f"同步 {synced} 張訂單；{skipped} 張沒有檔案或同步失敗（失敗原因記在訂單同步紀錄）。")

    def verify(self, root, orders):
        problems, checked, expected_folders = [], 0, set()
        for order in orders.select_related("vehicle_model__family", "source").iterator():
            files = order_files(order)
            if not files and not keeps_empty_folder(order):
                continue
            checked += 1
            relative = order_folder(order)
            expected_folders.add(relative)
            folder = root / relative
            if not folder.is_dir():
                problems.append(f"{order.number}：找不到資料夾 {relative}")
                continue
            for name, field_file in files:
                target = folder / name
                try:
                    if not target.exists():
                        problems.append(f"{order.number}：缺檔案 {name}")
                    elif target.stat().st_size != field_file.size:
                        problems.append(f"{order.number}：檔案大小不同 {name}")
                except OSError as exc:
                    problems.append(f"{order.number}：無法讀取 {name}（{exc}）")
        for record in OrderArchiveRecord.objects.exclude(last_error=""):
            problems.append(f"{record.order.number}：最近同步錯誤 {record.last_error}")
        base = root / ARCHIVE_FOLDER
        if base.is_dir() and not getattr(orders, "_filtered_numbers", False):
            for folder in sorted(path for path in base.glob("*/*/*/*") if path.is_dir()):
                relative = folder.relative_to(root).as_posix()
                if relative not in expected_folders and folder.name.split("_")[-1].startswith("SO"):
                    problems.append(f"多出的資料夾（系統沒有對應）：{relative}")
            for folder in sorted(path for path in (base / "_已刪除訂單").glob("*") if path.is_dir()):
                relative = folder.relative_to(root).as_posix()
                if relative not in expected_folders:
                    problems.append(f"多出的資料夾（系統沒有對應）：{relative}")
        self.stdout.write(f"核對 {checked} 張有檔案的訂單。")
        for line in problems:
            self.stdout.write(f"- {line}")
        self.stdout.write("全部一致。" if not problems else f"共 {len(problems)} 項不一致。")
