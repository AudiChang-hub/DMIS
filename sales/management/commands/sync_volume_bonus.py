from django.core.management.base import BaseCommand

from sales.services.volume_bonus import sync_all


class Command(BaseCommand):
    help = "依規則重算全部台數獎金的試算（每日排程，可重複執行）；不入帳，結算在給付頁手動按（T-203）。"

    def handle(self, *args, **options):
        changed = sync_all()
        self.stdout.write(f"台數獎金試算同步完成：{changed} 張訂單的傭金支出有變動。")
