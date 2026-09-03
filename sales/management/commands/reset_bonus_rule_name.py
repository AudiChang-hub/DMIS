from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import DealerVolumeBonusRule


class Command(BaseCommand):
    help = "將指定未結算規則的已確認舊名稱改回自動命名；預設僅預覽，不變更適用範圍。"

    def add_arguments(self, parser):
        parser.add_argument("--rule-id", type=int, required=True)
        parser.add_argument("--expected-name", required=True)
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            rule = DealerVolumeBonusRule.objects.select_for_update().get(pk=options["rule_id"])
        except DealerVolumeBonusRule.DoesNotExist as exc:
            raise CommandError("找不到指定規則。") from exc
        if not rule.name:
            self.stdout.write("已是自動命名，沒有變更。")
            return
        if rule.name != options["expected_name"]:
            raise CommandError("名稱已變更，停止修正，請先重新確認。")
        if rule.settlements.exists():
            raise CommandError("已有結算，不能修改歷史規則名稱。")
        previous = rule.name
        rule.name = ""
        self.stdout.write(f"規則 #{rule.pk}：{previous} → {rule.display_name}；僅清除舊名稱，不變更車行、條件、期間或金額。")
        if options["apply"]:
            rule.save(update_fields=["name", "updated_at"])
            self.stdout.write("已套用自動命名。")
        else:
            self.stdout.write("僅預覽；確認後加 --apply 才會寫入。")
