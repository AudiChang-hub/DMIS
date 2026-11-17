from django.core.management.base import BaseCommand, CommandError

from sales.help.manual import manual_path, manual_text, render_manual


class Command(BaseCommand):
    help = "由 sales/help/articles.py 產生 docs/USER_MANUAL.md；--check 只檢查是否同步。"

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="不寫檔，內容不同步時回傳錯誤")

    def handle(self, *args, **options):
        content = render_manual()
        if options["check"]:
            if manual_text() != content:
                raise CommandError("docs/USER_MANUAL.md 與文章資料不同步，請執行 python manage.py build_user_manual")
            self.stdout.write("USER_MANUAL.md 已同步")
            return
        path = manual_path()
        path.write_bytes(content.encode("utf-8"))
        self.stdout.write(f"已寫入 {path}（{len(content.splitlines())} 行）")
