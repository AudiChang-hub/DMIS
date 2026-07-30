import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import SalesOrder, SalesOrderSearchIndex
from sales.services.order_search import build_order_search_query


class Command(BaseCommand):
    help = "以會自動回滾的合成訂單量測搜尋效能，不保留測試資料"

    def add_arguments(self, parser):
        parser.add_argument("--rows", type=int, default=10000)
        parser.add_argument("--runs", type=int, default=20)

    @transaction.atomic
    def handle(self, *args, **options):
        template = SalesOrder.objects.order_by("pk").first()
        if not template:
            raise CommandError("至少需要一張既有訂單作為安全的測試資料範本。")
        rows = max(100, min(options["rows"], 50000))
        runs = max(5, min(options["runs"], 100))
        excluded = {
            "id", "number", "allocated_vehicle", "created_at", "updated_at",
        }
        values = {
            field.attname: getattr(template, field.attname)
            for field in SalesOrder._meta.concrete_fields
            if field.name not in excluded
        }
        orders = [
            SalesOrder(
                number=f"BENCH-{index:06d}",
                allocated_vehicle=None,
                **values,
            )
            for index in range(rows)
        ]
        started = time.perf_counter()
        SalesOrder.objects.bulk_create(orders, batch_size=500)
        SalesOrderSearchIndex.objects.bulk_create(
            [
                SalesOrderSearchIndex(
                    order=order,
                    search_text=f"benchmarkneedle{index} 測試車主",
                    match_payload=[],
                )
                for index, order in enumerate(orders)
            ],
            batch_size=500,
        )
        build_ms = (time.perf_counter() - started) * 1000
        durations = []
        for _ in range(runs):
            started = time.perf_counter()
            SalesOrder.objects.filter(
                build_order_search_query("benchmarkneedle9999")
            ).count()
            durations.append((time.perf_counter() - started) * 1000)
        durations.sort()
        p95 = durations[max(0, int(len(durations) * 0.95) - 1)]
        self.stdout.write(
            self.style.SUCCESS(
                f"rows={rows} build_ms={build_ms:.1f} "
                f"min_ms={durations[0]:.2f} p95_ms={p95:.2f} "
                f"max_ms={durations[-1]:.2f}"
            )
        )
        transaction.set_rollback(True)
