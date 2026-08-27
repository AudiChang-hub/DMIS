from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from sales.services.dgpa_calendar import (
    CalendarSyncError,
    sync_official_business_calendar,
)


class Command(BaseCommand):
    help = "從人事行政總處同步政府行政機關辦公日曆；預設同步當年與次年"

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            action="append",
            type=int,
            dest="years",
            help="指定西元年度，可重複使用；指定後每個年度都必須已有官方資料",
        )

    def handle(self, *args, **options):
        requested_years = options.get("years")
        if requested_years:
            years = requested_years
            required_years = requested_years
        else:
            current_year = timezone.localdate().year
            years = [current_year, current_year + 1]
            required_years = [current_year]
        try:
            summary = sync_official_business_calendar(
                years=years,
                required_years=required_years,
            )
        except CalendarSyncError as exc:
            raise CommandError(str(exc)) from exc

        synced = "、".join(str(year) for year in summary["years"])
        skipped = "、".join(str(year) for year in summary["skipped_years"])
        message = (
            f"官方工作日行事曆同步完成：{synced}；"
            f"新增 {summary['created']} 筆、更新 {summary['updated']} 筆、"
            f"停用 {summary['deactivated']} 筆。"
        )
        if skipped:
            message += f" 尚未公布：{skipped}。"
        self.stdout.write(self.style.SUCCESS(message))
