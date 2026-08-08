import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.services.odoo_master_import import import_odoo_master_data


class Command(BaseCommand):
    help = "預覽或套用舊 Odoo DMIS 主檔資料；預設只乾跑，不修改資料庫"

    def add_arguments(self, parser):
        parser.add_argument("source_file")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="實際寫入；省略時只輸出預覽統計",
        )
        parser.add_argument("--report", help="另存 JSON 驗證報告")

    def handle(self, *args, **options):
        source = Path(options["source_file"])
        if not source.is_file():
            raise CommandError(f"找不到匯出檔：{source}")
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"無法讀取匯出檔：{exc}") from exc
        try:
            summary = import_odoo_master_data(payload, apply=options["apply"])
        except (ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        result = {
            "mode": "apply" if options["apply"] else "dry-run",
            "source": str(source),
            "summary": summary,
            "legacy_only_counts": payload.get("legacy_only_counts", {}),
        }
        rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        self.stdout.write(rendered)
        if options.get("report"):
            report = Path(options["report"])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(rendered, encoding="utf-8")
