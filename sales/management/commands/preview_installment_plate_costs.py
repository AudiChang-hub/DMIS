"""分期單牌險費 0 改由本店支付規費、強制險後，列出受影響的訂單與金額變化（UAT p4，使用者 2026-11-06 選 A）。

只列出、不寫入（沒有 --apply）：
- 未完成的訂單：下次儲存或同步時自動改成新規則（`operations_sync.sync_order_operations`）。
- 已完成的訂單：照規則不回填，只列出供查閱。
取消、待退款、例外結案與 Excel 匯入單不適用；人工改過的支出欄位保留原值，不列入變化。
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from sales.models import OrderOperationsProfile, SalesOrder
from sales.services.agency_fee import compulsory_insurance_cost, plate_fee_waived, registration_fee_cost
from sales.services.payment_summary import CLOSED_SALE_STATUSES

FIELDS = (
    ("registration_tax_expense", "規費支出", registration_fee_cost),
    ("compulsory_insurance_expense", "強制險支出", compulsory_insurance_cost),
)


def plate_cost_changes(order):
    """回傳 {欄位: (目前, 新規則)}；人工改過的欄位與沒有差異的欄位不列。"""
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    manual = set(profile.manual_financial_fields or []) if profile else set()
    changes = {}
    for name, _label, calculate in FIELDS:
        if name in manual:
            continue
        before = Decimal(str(getattr(profile, name, 0) or 0))
        after = Decimal(str(calculate(order) or 0))
        if before != after:
            changes[name] = (before, after)
    return changes


def affected_orders(numbers=()):
    orders = (
        SalesOrder.objects.filter(
            payment_type=SalesOrder.PaymentType.INSTALLMENT, plate_insurance_auto=False, plate_insurance_fee=0,
            legacy_snapshot__isnull=True,
        )
        .exclude(status__in=CLOSED_SALE_STATUSES)
        .select_related("vehicle_model")
        .order_by("pk")
    )
    if numbers:
        orders = orders.filter(number__in=numbers)
    for order in orders:
        if not plate_fee_waived(order):
            continue
        changes = plate_cost_changes(order)
        if changes:
            yield order, changes


class Command(BaseCommand):
    help = "列出分期單牌險費 0 改由本店支付規費、強制險後的金額變化；只列出，不寫入。"

    def add_arguments(self, parser):
        parser.add_argument("--order", nargs="*", default=[], help="只列這些訂單編號")

    def handle(self, *args, **options):
        plan = list(affected_orders(options["order"]))
        groups = (
            ("未完成（下次儲存或同步時自動套用）", [item for item in plan if item[0].status != SalesOrder.Status.COMPLETED]),
            ("已完成（不回填，只列出）", [item for item in plan if item[0].status == SalesOrder.Status.COMPLETED]),
        )
        self.stdout.write(f"符合：{len(plan)} 張分期單（牌險費 0、規費或強制險支出會改變）")
        for title, items in groups:
            total = sum(after - before for _order, changes in items for before, after in changes.values())
            self.stdout.write(f"{title}：{len(items)} 張，淨利合計變化 {-total:,.0f}")
            for order, changes in items:
                text = "；".join(
                    f"{label} {changes[name][0]:,.0f}→{changes[name][1]:,.0f}"
                    for name, label, _calculate in FIELDS if name in changes
                )
                delta = sum(after - before for before, after in changes.values())
                self.stdout.write(f"  {order.number}（{order.get_status_display()}）｜{text}｜淨利 {-delta:+,.0f}")
        self.stdout.write("dry-run：只列出，未寫入。")
