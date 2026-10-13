"""把訂單檔案同步到 NAS（ORDER_ARCHIVE_DIR）；部署後補同步全部，或指定單號重做。"""
from django.core.management.base import BaseCommand, CommandError

from sales.models import SalesOrder
from sales.services.order_archive import archive_root, sync_order


class Command(BaseCommand):
    help = "依「車型／年／月／車行_車主_車型_訂單編號」把訂單檔案同步到 NAS。"

    def add_arguments(self, parser):
        parser.add_argument("numbers", nargs="*", help="只同步這些訂單編號；不填則同步全部訂單")

    def handle(self, *args, numbers, **options):
        if archive_root() is None:
            raise CommandError("尚未設定 DMIS_ORDER_ARCHIVE_DIR，無法同步。")
        orders = SalesOrder.all_objects.order_by("pk")
        if numbers:
            orders = orders.filter(number__in=numbers)
        synced = skipped = 0
        for order_id in orders.values_list("pk", flat=True).iterator():
            if sync_order(order_id):
                synced += 1
            else:
                skipped += 1
        self.stdout.write(f"同步 {synced} 張訂單；{skipped} 張沒有檔案或同步失敗（失敗原因記在訂單同步紀錄）。")
