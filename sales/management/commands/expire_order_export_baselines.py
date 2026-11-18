from django.core.management.base import BaseCommand

from sales.order_exchange.columns import BASELINE_DAYS
from sales.order_exchange.retention import expire_baselines


class Command(BaseCommand):
    help = f"清掉超過 {BASELINE_DAYS} 天的訂單匯出基準值（T-232），只留匯出摘要；可每日排程。"

    def handle(self, *args, **options):
        count = expire_baselines()
        self.stdout.write(f"已清除 {count} 筆超過 {BASELINE_DAYS} 天的匯出基準值。")
