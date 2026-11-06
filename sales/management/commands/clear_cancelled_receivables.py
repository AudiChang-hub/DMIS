"""既有已取消訂單的系統未收應收列回填清除，並重算已收清狀態（使用者 2026-11-06 選 B，T-113）。

新取消的訂單在取消完成時自動清除（services/cancelled_receivables.py）；這個指令處理改版前就已取消的單。

- 預設 dry-run：逐張列出會刪除的收款列（項目、分類、應收、實收），以及已取消類訂單（取消、取消待退款、例外結案）
  重算後會改變的「已收清／分期已撥款」旗標前後值，不寫入。
- --apply：在交易內清除收款列（每張一筆 OrderChange 含每列完整欄位）、再重算旗標（每張一筆 OrderChange 記前後值），
  複查已確認實收與退款紀錄不變，重建搜尋索引。
- --rollback：依 --apply 的 OrderChange 以原編號重建收款列、旗標改回清除前的值，同樣留稽核並重建索引。
- --order：只處理指定訂單編號（可多個）。
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import OrderChange, OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services.cancelled_receivables import (
    CLEAR_REASON, clear_cancelled_receivables, clearable_receivables, restore_cleared_receivables,
)
from sales.services.operations_sync import payment_confirmation_changes, refresh_payment_confirmation
from sales.services.order_search import rebuild_order_search_index
from sales.services.payment_summary import CLOSED_SALE_STATUSES

ACTOR = "系統資料整理（依使用者 2026-11-06）"
BACKFILL_REASON = CLEAR_REASON + "（改版前已取消的訂單回填）"
REFRESH_REASON = "重算已取消訂單的已收清狀態（取消單不再推算系統應收）"
FLAG_LABELS = {"payment_confirmed": "已收清", "installment_transfer_confirmed": "分期已撥款"}


def _yes_no(value):
    return "是" if value else "否"


class Command(BaseCommand):
    help = "清除已取消訂單的系統未收應收列並重算已收清；預設 dry-run，--apply 寫入，--rollback 還原。"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="實際清除與重算（預設只列出）")
        mode.add_argument("--rollback", action="store_true", help="依處理紀錄重建收款列、旗標改回原值")
        parser.add_argument("--order", nargs="*", default=[], help="只處理這些訂單編號")

    def handle(self, *args, **options):
        if options["rollback"]:
            return self.rollback(options["order"])
        cancelled = SalesOrder.objects.filter(status=SalesOrder.Status.CANCELLED).order_by("pk")
        closed = SalesOrder.objects.filter(status__in=CLOSED_SALE_STATUSES).order_by("pk")
        if options["order"]:
            cancelled = cancelled.filter(number__in=options["order"])
            closed = closed.filter(number__in=options["order"])
        plan = [(order, clearable_receivables(order)) for order in cancelled]
        plan = [(order, rows) for order, rows in plan if rows]
        clearing = {order.pk: {row.pk for row in rows} for order, rows in plan}
        self.stdout.write(f"符合：{len(plan)} 張已取消訂單、{sum(len(rows) for _, rows in plan)} 筆系統未收應收列")
        for order, rows in plan:
            for row in rows:
                self.stdout.write(
                    f"  {order.number}｜收款列 #{row.pk}｜{row.item_name}（{row.system_key}）｜{row.receipt_kind_label}"
                    f"｜應收 {row.expected_amount:,.0f}｜實收 {row.received_amount:,.0f}｜未確認"
                )
        refresh_plan = []
        for order in closed:
            # 以清除後的收款列試算，dry-run 與 --apply 看到的結果一致。
            records = PaymentRecord.objects.filter(order=order).exclude(pk__in=clearing.get(order.pk, ()))
            _profile, changes = payment_confirmation_changes(order.pk, records)
            if changes:
                refresh_plan.append((order, changes))
        self.stdout.write(f"重算已收清：{len(refresh_plan)} 張已取消類訂單會改變")
        for order, changes in refresh_plan:
            text = "；".join(f"{FLAG_LABELS[name]} {_yes_no(before)}→{_yes_no(after)}" for name, (before, after) in changes.items())
            self.stdout.write(f"  {order.number}（{order.get_status_display()}）｜{text}")
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。加上 --apply 才會清除與重算。")
            return
        confirmed_before = self._confirmed_ledger()
        touched = set()
        with transaction.atomic():
            for order, rows in plan:
                removed = clear_cancelled_receivables(order, actor_name=ACTOR, reason=BACKFILL_REASON)
                if sorted(removed) != sorted(row.pk for row in rows):
                    raise CommandError(f"{order.number} 清除的收款列與預覽不同，已全部復原。")
                touched.add(order.pk)
            for order, planned in refresh_plan:
                # 清除收款列時已順手重算過；這裡補算其餘訂單，並核對結果與預覽相同。
                refresh_payment_confirmation(order.pk)
                profile = OrderOperationsProfile.objects.get(order=order)
                if any(getattr(profile, name) != after for name, (_before, after) in planned.items()):
                    raise CommandError(f"{order.number} 重算結果與預覽不同，已全部復原。")
                OrderChange.objects.create(order=order, actor_name=ACTOR, reason=REFRESH_REASON, changes={
                    FLAG_LABELS[name]: {"before": _yes_no(before), "after": _yes_no(after), "field": name, "value": before}
                    for name, (before, after) in planned.items()
                })
                touched.add(order.pk)
            if self._confirmed_ledger() != confirmed_before:
                raise CommandError("複查失敗：已確認的實收或退款紀錄有變動，已全部復原。")
        for order_id in touched:
            rebuild_order_search_index(order_id)
        self.stdout.write(self.style.SUCCESS(
            f"完成：清除 {len(plan)} 張訂單的 {sum(len(rows) for _, rows in plan)} 筆應收、重算 {len(refresh_plan)} 張的已收清，"
            "已確認實收不變，已重建搜尋索引。"))

    def rollback(self, numbers):
        changes = OrderChange.objects.filter(actor_name=ACTOR, reason__in=[BACKFILL_REASON, REFRESH_REASON]).order_by("-pk")
        if numbers:
            changes = changes.filter(order__number__in=numbers)
        changes = list(changes.select_related("order"))
        self.stdout.write(f"可還原的處理紀錄：{len(changes)} 筆")
        restored = {}
        with transaction.atomic():
            for change in changes:
                if change.reason == REFRESH_REASON:
                    values = {entry["field"]: entry["value"] for entry in change.changes.values() if "field" in entry}
                    OrderOperationsProfile.objects.filter(order_id=change.order_id).update(**values)
                    OrderChange.objects.create(order_id=change.order_id, actor_name=ACTOR, reason=f"還原：{REFRESH_REASON}",
                                               changes={label: {"before": entry["after"], "after": entry["before"]}
                                                        for label, entry in change.changes.items()})
                    restored.setdefault(change.order_id, [])
                    self.stdout.write(f"  {change.order.number}｜已收清旗標改回原值")
                    continue
                pks = restore_cleared_receivables(change, actor_name=ACTOR)
                if pks:
                    restored.setdefault(change.order_id, []).extend(pks)
                    self.stdout.write(f"  {change.order.number}｜重建收款列 {', '.join(f'#{pk}' for pk in pks)}")
        for order_id in restored:
            rebuild_order_search_index(order_id)
        self.stdout.write(self.style.SUCCESS(f"完成：還原 {sum(map(len, restored.values()))} 筆收款列。"))

    @staticmethod
    def _confirmed_ledger():
        return list(PaymentRecord.objects.filter(confirmed=True).order_by("pk").values_list(
            "pk", "order_id", "entry_type", "received_amount", "expected_amount"))
