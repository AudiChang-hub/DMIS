"""清掉沒有訂金的單上空的「訂金」收款列（使用者 2026-11-06 T-125 問題 1 方案 B）。

1.86.73 起沒有訂金就不建訂金列；這個指令處理之前一律建立的空列。只刪「訂單訂金為 0、列上應收與實收都是 0、
沒確認、沒有日期、帳戶、證明、備註、刷卡資料、沖銷關聯、也沒改過項目名稱」的系統訂金列。

- 預設 dry-run：列出筆數（依訂單狀態、來源、付款方式）、略過的原因與抽查範例；每張單在交易內試刪後
  比對收款摘要（應收、實收、交車應收、已收清）前後一致，不一致的單不會刪。
- --apply：逐張在交易內重新檢查後刪除，每張留一筆 OrderChange。
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from sales.models import OrderChange, PaymentRecord, SalesOrder
from sales.services.payment_summary import payment_summary

ACTOR = "系統資料整理（clear_empty_deposit_rows）"
REASON = "刪除沒有訂金的空訂金列（T-125 問題 1 方案 B）"
SUMMARY_KEYS = ("customer_expected", "customer_received", "customer_due", "customer_overpaid", "delivery_due", "lender_expected", "lender_due",
                "lender_received", "settled")


class _Rollback(Exception):
    pass


def candidates():
    return (
        PaymentRecord.objects.filter(system_key="deposit", entry_type=PaymentRecord.EntryType.RECEIPT,
                                     expected_amount=0, received_amount=0, confirmed=False)
        .filter(Q(order__deposit_amount=0) | Q(order__deposit_amount__isnull=True))
        .select_related("order")
        .order_by("order_id", "pk")
    )


def skip_reason(row):
    if row.confirmed_at or row.confirmed_by:
        return "曾確認過"
    if row.received_on:
        return "有收款日期"
    if row.receiving_account or row.proof or row.note:
        return "有帳戶、證明或備註"
    if row.card_principal or row.card_fee_charged or row.bank_card_fee:
        return "有刷卡資料"
    if row.item_name_overridden:
        return "改過項目名稱"
    if row.reverses_id or row.reversal_entries.exists():
        return "有沖銷關聯"
    return ""


def _summary(order):
    order = SalesOrder.objects.get(pk=order.pk)
    summary = payment_summary(order)
    return {key: summary.get(key) for key in SUMMARY_KEYS}


def summary_unchanged(row):
    before = _summary(row.order)
    try:
        with transaction.atomic():
            PaymentRecord.objects.filter(pk=row.pk).delete()
            after = _summary(row.order)
            raise _Rollback
    except _Rollback:
        pass
    return before == after


class Command(BaseCommand):
    help = "刪除沒有訂金的空訂金列；預設 dry-run，--apply 才刪除並留 OrderChange。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="實際刪除（預設只列出）")
        parser.add_argument("--samples", type=int, default=5, help="抽查範例筆數")

    def handle(self, *args, **options):
        plan, skipped = [], Counter()
        for row in candidates().iterator():
            reason = skip_reason(row) or ("" if summary_unchanged(row) else "刪除後收款摘要會變")
            if reason:
                skipped[reason] += 1
            else:
                plan.append(row)
        self.stdout.write(f"符合條件的空訂金列：{len(plan)} 筆；略過 {sum(skipped.values())} 筆")
        for title, key in (("訂單狀態", lambda r: r.order.get_status_display()),
                           ("訂單來源", lambda r: r.order.get_source_type_display()),
                           ("付款方式", lambda r: r.order.get_payment_type_display()),
                           ("匯入單", lambda r: "Excel 匯入" if hasattr(r.order, "legacy_snapshot") else "系統建立")):
            counts = Counter(key(row) for row in plan)
            self.stdout.write(f"  依{title}：" + "、".join(f"{name} {count}" for name, count in counts.most_common()))
        for reason, count in skipped.most_common():
            self.stdout.write(f"  略過（{reason}）：{count}")
        step = max(len(plan) // max(options["samples"], 1), 1)
        for row in plan[::step][:options["samples"]]:
            self.stdout.write(f"  範例 {row.order.number}（{row.order.get_status_display()}，{row.order.get_source_type_display()}）"
                              f"收款列 #{row.pk}：{row.item_name}；應收 {row.expected_amount}；實收 {row.received_amount}")
        if not options["apply"]:
            self.stdout.write("dry-run：未刪除。加上 --apply 才會刪除。")
            return
        deleted = 0
        for row in plan:
            with transaction.atomic():
                current = candidates().select_for_update(of=("self",)).filter(pk=row.pk).first()
                if current is None or skip_reason(current):
                    continue
                OrderChange.objects.create(order=current.order, actor_name=ACTOR, reason=REASON, changes={
                    f"刪除收款列 #{current.pk}：{current.item_name}": {
                        "before": f"應收 {current.expected_amount}／實收 {current.received_amount}／未確認", "after": "已刪除"},
                })
                current.delete()
                deleted += 1
        self.stdout.write(self.style.SUCCESS(f"完成：刪除 {deleted} 筆空訂金列並留下處理紀錄。"))
