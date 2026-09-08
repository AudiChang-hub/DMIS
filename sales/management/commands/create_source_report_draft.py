"""建立原報表核對草稿，不覆蓋、不發布、不修改任何訂單。"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.reporting.engine import validate_config
from sales.reporting.models import ReportDefinition, ReportRevision
from sales.reporting.source_templates import SOURCE_TEMPLATES


class Command(BaseCommand):
    help = "建立指定原報表核對草稿（僅 admin、不自動發布、已存在則保留）"

    def add_arguments(self, parser):
        parser.add_argument("--page", choices=SOURCE_TEMPLATES, default="total", help="total：總車輛銷售；electric：電動車銷售統計")

    @transaction.atomic
    def handle(self, *args, **options):
        admin = get_user_model().objects.filter(username="admin", is_active=True, is_superuser=True).first()
        if not admin:
            raise CommandError("找不到有效的 admin 管理者。")
        # 同一 admin 的建立請求串行，避免並行執行重複建立。
        admin = get_user_model().objects.select_for_update().get(pk=admin.pk)
        config = validate_config(SOURCE_TEMPLATES[options["page"]]())
        report = ReportDefinition.objects.filter(draft__title=config["title"]).first()
        if report:
            self.stdout.write(f"已存在核對草稿 #{report.pk}，未覆蓋或發布。")
            return
        report = ReportDefinition.objects.create(draft=config, version=1)
        ReportRevision.objects.create(report=report, version=1, action="save", config=config, actor=admin)
        self.stdout.write(f"已建立核對草稿 #{report.pk}；僅 admin 可編輯，尚未發布。")
