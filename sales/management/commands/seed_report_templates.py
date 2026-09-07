"""首次安裝用的私人模板；不建立訂單、不對其他帳號發布。"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from sales.reporting.models import ReportDefinition, ReportRevision
from sales.reporting.views import initial_config, results


class Command(BaseCommand):
    help = "僅在報表完全空白時建立 admin 私人銷售分析模板，可重跑。"

    @transaction.atomic
    def handle(self, *args, **options):
        admin = get_user_model().objects.select_for_update().filter(username="admin", is_active=True, is_superuser=True).first()
        if admin is None:
            raise CommandError("找不到啟用中的 admin 管理帳號。")
        if ReportDefinition.objects.exists():
            self.stdout.write("已有報表，未新增或覆蓋任何內容。")
            return
        config = initial_config()
        results(config, {})
        report = ReportDefinition.objects.create(draft=config, published=config, version=1, published_at=timezone.now())
        ReportRevision.objects.create(report=report, version=1, action="publish", config=config, actor=admin)
        self.stdout.write(self.style.SUCCESS(f"已建立私人報表 {report.pk}；僅 admin 可查看，可自行編輯後開放團隊。"))
