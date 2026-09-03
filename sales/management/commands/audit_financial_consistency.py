import json

from django.core.management.base import BaseCommand

from sales.services.financial_audit import audit_financial_consistency


class Command(BaseCommand):
    help = "唯讀盤點訂單、收款、傭金及結算一致性，不修寫歷史金額。"

    def add_arguments(self, parser):
        parser.add_argument("--sample-limit", type=int, default=30)

    def handle(self, *args, **options):
        result = audit_financial_consistency(max(0, min(options["sample_limit"], 500)))
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
