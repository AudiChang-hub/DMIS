from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.services.dealer_workbook_sync import sync_dealer_workbook


class Command(BaseCommand):
    help = "同步車行聯絡簿 Excel；預設只預演，加上 --apply 才會寫入資料庫。"

    def add_arguments(self, parser):
        parser.add_argument("workbook", help="車行、網路平台.xlsx 的路徑")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="確認寫入；未指定時會在交易結束前回滾。",
        )

    def handle(self, *args, **options):
        workbook = Path(options["workbook"])
        if not workbook.is_file():
            raise CommandError(f"找不到檔案：{workbook}")
        try:
            result = sync_dealer_workbook(workbook, apply=options["apply"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        mode = "已正式同步" if options["apply"] else "預演完成（未寫入）"
        self.stdout.write(self.style.SUCCESS(mode))
        self.stdout.write(
            "、".join(
                [
                    f"Excel {result.source_rows} 家",
                    f"新增 {result.created} 家",
                    f"更新 {result.updated} 家",
                    f"無異動 {result.unchanged} 家",
                    f"別名對應 {result.aliases_used} 家",
                    f"系統既有但 Excel 未列 {result.database_only} 家（保留）",
                ]
            )
        )
