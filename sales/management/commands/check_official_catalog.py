from django.core.management.base import BaseCommand, CommandError

from sales.services.official_catalog import SOURCES, run_scheduled_checks


class Command(BaseCommand):
    help = "檢查原廠官網車型（排程用）；只記錄比對結果，發現新車型或變動時通知 admin，不修改車型資料"

    def add_arguments(self, parser):
        parser.add_argument("--brand", action="append", choices=sorted(SOURCES), dest="brands",
                            help="指定原廠，可重複使用；預設檢查全部")

    def handle(self, *args, **options):
        failed = []
        for brand, result in run_scheduled_checks(options.get("brands")).items():
            label = SOURCES[brand]["label"]
            if result == "skipped":
                self.stdout.write(f"{label}：已有進行中的檢查，略過。")
                continue
            self.stdout.write(
                f"{label}：{result.get_status_display()}，讀到 {result.entries_found} 款，讀取失敗 {result.error_count} 頁。"
            )
            if result.status == result.Status.FAILED:
                failed.append(label)
        if failed:
            raise CommandError("官網檢查失敗：" + "、".join(failed))
