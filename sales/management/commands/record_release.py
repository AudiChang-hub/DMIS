"""健康驗證後記錄正式版本首次發布時間；可重跑，不回寫舊版本。"""
from django.core.management.base import BaseCommand
from config.release_notes import CURRENT_VERSION
from sales.models import ReleasePublication


class Command(BaseCommand):
    help = "記錄目前正式版本的首次成功發布時間"

    def handle(self, *args, **options):
        item, created = ReleasePublication.objects.get_or_create(version=CURRENT_VERSION)
        self.stdout.write(f"{item.version}: {item.published_at.isoformat()} ({'新增' if created else '保留原時間'})")
