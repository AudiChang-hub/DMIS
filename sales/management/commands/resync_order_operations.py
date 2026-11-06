"""重新同步訂單收支與系統收款列（使用者 2026-11-06 T-114 方案 B）。

打開訂單頁、收支頁不再順手同步寫入；主檔與收款異動照舊由存檔與 signal 連動。這個指令用來找出、補上
漏網的落差（例如缺系統收款列、主檔改了但連動沒跑到）。

- 預設 dry-run：每張單在各自的交易內試跑 `sync_order_operations` 後立即回滾，列出會改的營運欄位前後值、
  會新增／刪除／修改的收款列，不寫入。
- --apply：只對有落差的單正式同步，每張寫一筆 OrderChange（欄位前後值），並重建搜尋索引。
- --order：只處理指定訂單編號（可多個）。
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from sales.models import OrderChange, OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services.operations_sync import sync_order_operations
from sales.services.order_search import rebuild_order_search_index

ACTOR = "系統資料整理（resync_order_operations）"
REASON = "重新同步訂單收支（打開頁面不再自動同步，T-114）"
SKIPPED = {"updated_at"}


class _Rollback(Exception):
    pass


def _state(order_id):
    profile = OrderOperationsProfile.objects.filter(order_id=order_id).values().first() or {}
    rows = {row["id"]: row for row in PaymentRecord.objects.filter(order_id=order_id).values()}
    for row in (profile, *rows.values()):
        for name in SKIPPED:
            row.pop(name, None)
    return profile, rows


def _text(value):
    return "" if value is None else str(value)


def planned_changes(order_id):
    """交易內試跑同步後回滾，回傳 {顯示名稱: (前, 後)}；沒有落差回傳空 dict。"""
    before = _state(order_id)
    try:
        with transaction.atomic():
            sync_order_operations(order_id)
            after = _state(order_id)
            raise _Rollback
    except _Rollback:
        pass
    changes = {}
    for name in sorted(set(before[0]) | set(after[0])):
        if before[0].get(name) != after[0].get(name):
            changes[f"收支：{name}"] = (_text(before[0].get(name)), _text(after[0].get(name)))
    for pk in sorted(set(before[1]) | set(after[1])):
        old, new = before[1].get(pk), after[1].get(pk)
        if old is None:
            changes[f"新增收款列：{new['item_name']}（{new['system_key'] or '人工'}）"] = ("", f"應收 {new['expected_amount']}")
        elif new is None:
            changes[f"刪除收款列 #{pk}：{old['item_name']}"] = (f"應收 {old['expected_amount']}／實收 {old['received_amount']}", "")
        else:
            for name in sorted(old):
                if old[name] != new.get(name):
                    changes[f"收款列 #{pk}.{name}"] = (_text(old[name]), _text(new.get(name)))
    return changes


class Command(BaseCommand):
    help = "找出並補上訂單收支同步的落差；預設 dry-run，--apply 才寫入並留 OrderChange。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="實際同步有落差的訂單（預設只列出）")
        parser.add_argument("--order", nargs="*", default=[], help="只處理這些訂單編號")

    def handle(self, *args, **options):
        orders = SalesOrder.objects.exclude(status=SalesOrder.Status.DRAFT).order_by("pk")
        if options["order"]:
            orders = orders.filter(number__in=options["order"])
        plan = []
        for order in orders.only("pk", "number", "status").iterator():
            changes = planned_changes(order.pk)
            if changes:
                plan.append((order, changes))
        self.stdout.write(f"檢查 {orders.count()} 張訂單；有落差：{len(plan)} 張")
        for order, changes in plan:
            self.stdout.write(f"  {order.number}（{order.get_status_display()}）")
            for label, (before, after) in changes.items():
                self.stdout.write(f"    {label}：{before or '—'} → {after or '—'}")
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。加上 --apply 才會同步。")
            return
        for order, changes in plan:
            with transaction.atomic():
                sync_order_operations(order.pk)
                OrderChange.objects.create(order=order, actor_name=ACTOR, reason=REASON, changes={
                    label: {"before": before, "after": after} for label, (before, after) in changes.items()
                })
            rebuild_order_search_index(order.pk)
        self.stdout.write(self.style.SUCCESS(f"完成：同步 {len(plan)} 張訂單並留下處理紀錄。"))
