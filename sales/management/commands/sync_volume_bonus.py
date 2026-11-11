from django.core.management.base import BaseCommand

from sales.services.volume_bonus import sync_all


class Command(BaseCommand):
    help = "依規則重算全部台數獎金；統計期間已結束的自動入帳到傭金支出（每日排程，可重複執行）。"

    def handle(self, *args, **options):
        changed = sync_all()
        self.stdout.write(f"台數獎金同步完成：{changed} 張訂單的已入帳獎金有變動。")
