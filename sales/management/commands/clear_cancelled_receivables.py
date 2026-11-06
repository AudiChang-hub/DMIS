"""既有已取消訂單的系統未收應收列回填清除（使用者 2026-11-06 選 B）。

新取消的訂單在取消完成時自動清除（services/cancelled_receivables.py）；這個指令處理改版前就已取消的單。

- 預設 dry-run：逐張列出訂單與會刪除的收款列（項目、分類、應收、實收），不寫入。
- --apply：在交易內逐張清除，每張寫一筆 OrderChange（含每列完整欄位，供 rollback）與事件，寫完複查並重建搜尋索引。
- --rollback：依 --apply 寫的 OrderChange 以原編號重建收款列，同樣留稽核並重建索引。
- --order：只處理指定訂單編號（可多個）。
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import OrderChange, PaymentRecord, SalesOrder
from sales.services.cancelled_receivables import (
    CLEAR_REASON, clear_cancelled_receivables, clearable_receivables, restore_cleared_receivables,
)
from sales.services.order_search import rebuild_order_search_index

ACTOR = "系統資料整理（依使用者 2026-11-06）"
BACKFILL_REASON = CLEAR_REASON + "（改版前已取消的訂單回填）"


class Command(BaseCommand):
    help = "清除已取消訂單的系統未收應收列；預設 dry-run，--apply 寫入，--rollback 還原。"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="實際清除（預設只列出）")
        mode.add_argument("--rollback", action="store_true", help="依清除時的處理紀錄重建收款列")
        parser.add_argument("--order", nargs="*", default=[], help="只處理這些訂單編號")

    def handle(self, *args, **options):
        if options["rollback"]:
            return self.rollback(options["order"])
        orders = SalesOrder.objects.filter(status=SalesOrder.Status.CANCELLED).order_by("pk")
        if options["order"]:
            orders = orders.filter(number__in=options["order"])
        plan = [(order, clearable_receivables(order)) for order in orders]
        plan = [(order, rows) for order, rows in plan if rows]
        self.stdout.write(f"符合：{len(plan)} 張已取消訂單、{sum(len(rows) for _, rows in plan)} 筆系統未收應收列")
        for order, rows in plan:
            for row in rows:
                self.stdout.write(
                    f"  {order.number}｜收款列 #{row.pk}｜{row.item_name}（{row.system_key}）｜{row.receipt_kind_label}"
                    f"｜應收 {row.expected_amount:,.0f}｜實收 {row.received_amount:,.0f}｜未確認"
                )
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。加上 --apply 才會清除。")
            return
        confirmed_before = self._confirmed_ledger()
        cleared = {}
        with transaction.atomic():
            for order, rows in plan:
                removed = clear_cancelled_receivables(order, actor_name=ACTOR, reason=BACKFILL_REASON)
                if sorted(removed) != sorted(row.pk for row in rows):
                    raise CommandError(f"{order.number} 清除的收款列與預覽不同，已全部復原。")
                cleared[order.pk] = removed
            if self._confirmed_ledger() != confirmed_before:
                raise CommandError("複查失敗：已確認的實收或退款紀錄有變動，已全部復原。")
        for order_id in cleared:
            rebuild_order_search_index(order_id)
        self.stdout.write(self.style.SUCCESS(
            f"完成：清除 {len(cleared)} 張訂單、{sum(map(len, cleared.values()))} 筆，已確認實收不變，已重建搜尋索引。"))

    def rollback(self, numbers):
        changes = OrderChange.objects.filter(actor_name=ACTOR, reason=BACKFILL_REASON).order_by("pk")
        if numbers:
            changes = changes.filter(order__number__in=numbers)
        changes = list(changes.select_related("order"))
        self.stdout.write(f"可還原的處理紀錄：{len(changes)} 筆")
        restored = {}
        with transaction.atomic():
            for change in changes:
                pks = restore_cleared_receivables(change, actor_name=ACTOR)
                if pks:
                    restored[change.order_id] = pks
                    self.stdout.write(f"  {change.order.number}｜重建收款列 {', '.join(f'#{pk}' for pk in pks)}")
        for order_id in restored:
            rebuild_order_search_index(order_id)
        self.stdout.write(self.style.SUCCESS(f"完成：還原 {sum(map(len, restored.values()))} 筆。"))

    @staticmethod
    def _confirmed_ledger():
        return list(PaymentRecord.objects.filter(confirmed=True).order_by("pk").values_list(
            "pk", "order_id", "entry_type", "received_amount", "expected_amount"))
