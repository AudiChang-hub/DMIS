from django.core.management.base import BaseCommand

from sales.services.notifications import resend_pending


class Command(BaseCommand):
    help = "補發待發送或失敗的 Email 通知；未設定 Email 通道時只標記為略過。"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        count = resend_pending(limit=options["limit"])
        self.stdout.write(f"已處理 {count} 筆通知。")
