from django.core.management.base import BaseCommand

from sales.models import SalesOrder
from sales.services.operations_sync import sync_order_operations


class Command(BaseCommand):
    help = "建立或更新所有訂單的營運資料與系統收款項目。"

    def handle(self, *args, **options):
        order_ids = SalesOrder.objects.order_by("id").values_list("id", flat=True)
        total = 0
        for order_id in order_ids.iterator(chunk_size=200):
            sync_order_operations(order_id)
            total += 1
        self.stdout.write(self.style.SUCCESS(f"完成，共同步 {total} 張訂單。"))
