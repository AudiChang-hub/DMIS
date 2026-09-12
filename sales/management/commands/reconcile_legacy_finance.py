import hashlib
import json
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from sales.models import LegacySalesSnapshot, OrderChange, OrderEvent, OrderOperationsProfile, SalesOrder
from sales.services.legacy_finance import repair_plan


class Command(BaseCommand):
    help = "逐筆核對歷史財務；預設唯讀，--apply 須搭配 --expected-digest。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-digest")
        parser.add_argument("--details", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["apply"] and not options["expected_digest"]:
            raise CommandError("套用前請先預覽並提供 --expected-digest。")
        order_ids = list(LegacySalesSnapshot.objects.order_by("order_id").values_list("order_id", flat=True))
        if options["apply"]:
            list(SalesOrder.objects.select_for_update().filter(pk__in=order_ids).order_by("pk"))
            list(OrderOperationsProfile.objects.select_for_update().filter(order_id__in=order_ids).order_by("order_id"))
        snapshots = list(LegacySalesSnapshot.objects.select_related("order__operations", "import_row").order_by("order_id"))
        plans = [repair_plan(snapshot) for snapshot in snapshots]
        digest = hashlib.sha256(json.dumps(plans, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        if options["apply"]:
            if digest != options["expected_digest"]:
                raise CommandError("資料已變更，請重新預覽；本次未寫入。")
            for snapshot, plan in zip(snapshots, plans):
                if plan["status"] != "ready":
                    if plan["status"] not in ("already_reconciled", "missing_profile"):
                        profile = snapshot.order.operations
                        note = {**plan["reconciliation"], "status": plan["status"]}
                        if plan["status"] == "preserved_changes":
                            note["reason"] = "已有財務或訂單修改，已保留現值，請人工核對。"
                        if profile.legacy_finance_reconciliation != note:
                            profile.legacy_finance_reconciliation = note
                            profile.save(update_fields=["legacy_finance_reconciliation", "updated_at"])
                    continue
                profile = snapshot.order.operations
                for field, value in plan["after"].items():
                    setattr(profile, field, Decimal(value))
                profile.legacy_finance_reconciliation = plan["reconciliation"]
                profile.updated_by = "歷史財務核對修復"
                profile.save(update_fields=[*plan["after"], "legacy_finance_reconciliation", "updated_by", "updated_at"])
                SalesOrder.objects.filter(pk=snapshot.order_id).update(revision=plan["revision"] + 1, updated_at=timezone.now())
                changes = {field: {"before": plan["before"][field], "after": value} for field, value in plan["after"].items() if Decimal(plan["before"][field]) != Decimal(value)}
                changes["Excel 財務核對"] = {"before": plan["source"], "after": plan["reconciliation"]}
                OrderChange.objects.create(order_id=snapshot.order_id, reason="補齊 Excel 財務映射並核對原淨利", changes=changes, actor_name="歷史財務核對修復")
                OrderEvent.objects.create(order_id=snapshot.order_id, event_type="legacy_finance_repaired", description="已逐筆核對原 Excel 淨利；保留原付款紀錄與價格快照。", actor_name="歷史財務核對修復")
        self.stdout.write(json.dumps({"applied": options["apply"], "digest": digest,
                                      "counts": dict(Counter(p["status"] for p in plans)),
                                      **({"rows": plans} if options["details"] else {})}, ensure_ascii=False, default=str))
