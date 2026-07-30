from django.core.management.base import BaseCommand

from sales.models import SalesOrder
from sales.services.order_search import rebuild_order_search_index


class Command(BaseCommand):
    help = "重建所有訂單的全欄位搜尋索引"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=200)

    def handle(self, *args, **options):
        order_ids = SalesOrder.objects.order_by("pk").values_list("pk", flat=True)
        total = order_ids.count()
        for index, order_id in enumerate(
            order_ids.iterator(chunk_size=options["batch_size"]), start=1
        ):
            rebuild_order_search_index(order_id)
            if index % options["batch_size"] == 0:
                self.stdout.write(f"已重建 {index}/{total}")
        self.stdout.write(self.style.SUCCESS(f"完成，共重建 {total} 筆訂單索引。"))
