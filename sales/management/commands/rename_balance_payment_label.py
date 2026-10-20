"""系統尾款收款列改名：「分期外應收」→「尾款」（使用者 2026-10-20，1.86.27）。

這一列的金額一直是扣訂金後還要收的錢（尾款），分期單卻叫「分期外應收」，與訂購單的分期外應收（扣訂金前）
對不起來。只改名稱，金額、實收、確認與憑證一律不動。

- 預設 dry-run：逐筆列出訂單編號、收款列與舊值→新值，不寫入。
- --apply：在交易內改名，每筆寫一筆 OrderChange（舊值、新值與收款列編號，供 rollback），寫完複查並重建搜尋索引。
- --rollback：依 --apply 寫的 OrderChange 把名稱改回舊值，同樣留稽核並重建索引。
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import OrderChange, PaymentRecord
from sales.services.operations_sync import BALANCE_LABEL, LEGACY_INSTALLMENT_BALANCE_LABEL
from sales.services.order_search import rebuild_order_search_index

ACTOR = "系統資料整理（依使用者 2026-10-20）"
APPLY_REASON = "系統收款列改名：扣訂金後的金額稱「尾款」（收款列 #{pk}；金額與收款狀態不變）"
ROLLBACK_REASON = "系統收款列改名還原（收款列 #{pk}）"
REASON_PATTERN = re.compile(r"^系統收款列改名：.*收款列 #(\d+)")
FIELD_LABEL = "收款項目"
FROZEN_FIELDS = (
    "expected_amount", "received_amount", "received_on", "confirmed", "payment_method", "system_key",
    "receipt_kind", "expected_amount_overridden", "order_id",
)


def _frozen(records):
    return {record["pk"]: tuple(record[name] for name in FROZEN_FIELDS)
            for record in records.values("pk", *FROZEN_FIELDS)}


class Command(BaseCommand):
    help = "系統尾款收款列「分期外應收」改名為「尾款」；預設 dry-run，--apply 寫入，--rollback 還原。"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="實際改名（預設只列出變動）")
        mode.add_argument("--rollback", action="store_true", help="依改名時的稽核紀錄改回舊名稱")

    def handle(self, *args, **options):
        if options["rollback"]:
            return self.rollback()
        targets = PaymentRecord.objects.filter(system_key="balance", item_name=LEGACY_INSTALLMENT_BALANCE_LABEL)
        rows = list(targets.select_related("order").order_by("order_id", "pk"))
        received = sum(1 for row in rows if row.received_amount or row.confirmed)
        self.stdout.write(f"符合：{len(rows)} 筆（其中已收款或已確認 {received} 筆，只改名稱）")
        for row in rows:
            self.stdout.write(
                f"  {row.order.number}｜收款列 #{row.pk}｜{row.item_name} → {BALANCE_LABEL}"
                f"｜應收 {row.expected_amount:,.0f}｜實收 {row.received_amount:,.0f}"
            )
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。加上 --apply 才會改名。")
            return
        order_ids = self._rename(
            targets, LEGACY_INSTALLMENT_BALANCE_LABEL, BALANCE_LABEL, APPLY_REASON, expected=len(rows))
        self._reindex(order_ids)
        self.stdout.write(self.style.SUCCESS(f"完成：改名 {len(order_ids)} 張訂單的尾款列，並重建搜尋索引。"))

    def rollback(self):
        payment_ids = []
        for change in OrderChange.objects.filter(actor_name=ACTOR, reason__startswith="系統收款列改名："):
            match = REASON_PATTERN.match(change.reason)
            if match:
                payment_ids.append(int(match.group(1)))
        targets = PaymentRecord.objects.filter(pk__in=payment_ids, system_key="balance", item_name=BALANCE_LABEL)
        self.stdout.write(f"可還原：{targets.count()} 筆（改名紀錄 {len(payment_ids)} 筆）")
        order_ids = self._rename(
            targets, BALANCE_LABEL, LEGACY_INSTALLMENT_BALANCE_LABEL, ROLLBACK_REASON, expected=targets.count())
        self._reindex(order_ids)
        self.stdout.write(self.style.SUCCESS(f"完成：還原 {len(order_ids)} 筆。"))

    def _rename(self, targets, old, new, reason, *, expected):
        with transaction.atomic():
            locked = list(targets.select_for_update().order_by("pk"))
            if len(locked) != expected:
                raise CommandError(f"筆數在執行期間變動（預期 {expected}、實際 {len(locked)}），未寫入。")
            ids = [row.pk for row in locked]
            before = _frozen(PaymentRecord.objects.filter(pk__in=ids))
            # 只更新名稱欄位：不經 save()，不觸發金額或收款同步。
            PaymentRecord.objects.filter(pk__in=ids, item_name=old).update(item_name=new)
            OrderChange.objects.bulk_create([
                OrderChange(order_id=row.order_id, actor_name=ACTOR, reason=reason.format(pk=row.pk),
                            changes={FIELD_LABEL: {"before": old, "after": new}})
                for row in locked
            ])
            after = _frozen(PaymentRecord.objects.filter(pk__in=ids))
            renamed = PaymentRecord.objects.filter(pk__in=ids, item_name=new).count()
            if after != before or renamed != len(ids):
                raise CommandError("複查失敗：金額、收款狀態或名稱與預期不符，已全部復原。")
        return sorted({row.order_id for row in locked})

    def _reindex(self, order_ids):
        for order_id in order_ids:
            rebuild_order_search_index(order_id)
