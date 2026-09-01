from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from sales.services.price_list_distribution import (
    ensure_distribution_month,
    ensure_scheduled_distribution,
    normalize_month,
)


class Command(BaseCommand):
    help = "建立每月價格表分發清單；每日執行時會補建本月，月底另建立隔月。"

    def add_arguments(self, parser):
        parser.add_argument("--month", help="指定月份，格式 YYYY-MM。")
        parser.add_argument("--sync", action="store_true", help="重新同步指定月份名單。")

    def handle(self, *args, **options):
        month_value = options.get("month")
        if month_value:
            try:
                month = normalize_month(month_value)
            except (TypeError, ValueError) as exc:
                raise CommandError("月份格式必須為 YYYY-MM。") from exc
            distribution, created = ensure_distribution_month(
                month,
                generated_by="管理指令",
                sync=options["sync"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"{distribution.month:%Y-%m}：{distribution.items.count()} 家（{'新建' if created else '已存在／已同步'}）"
                )
            )
            return

        for distribution, created in ensure_scheduled_distribution(today=timezone.localdate()):
            self.stdout.write(
                self.style.SUCCESS(
                    f"{distribution.month:%Y-%m}：{distribution.items.count()} 家（{'新建' if created else '已存在'}）"
                )
            )
