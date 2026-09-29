"""發票開立、作廢與折讓；紀錄只增不改，淨額供結案與對帳提醒。"""
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

ZERO = Decimal("0")
INVOICE_NUMBER = re.compile(r"^[A-Z]{2}\d{8}$")


def normalize_invoice_number(value):
    number = re.sub(r"[\s\-]", "", (value or "").upper())
    if not INVOICE_NUMBER.match(number):
        raise ValidationError("發票號碼格式應為 2 碼英文加 8 碼數字，例如 AB12345678。")
    return number


def invoice_summary(order, records=None):
    from sales.models import InvoiceRecord

    records = list(order.invoice_records.all()) if records is None else list(records)
    issues = [r for r in records if r.kind == InvoiceRecord.Kind.ISSUE]
    voided = {r.related_invoice_id for r in records if r.kind == InvoiceRecord.Kind.VOID}
    allowances = {}
    for record in records:
        if record.kind == InvoiceRecord.Kind.ALLOWANCE:
            allowances[record.related_invoice_id] = allowances.get(record.related_invoice_id, ZERO) + record.amount
    open_invoices = []
    net = ZERO
    for issue in issues:
        if issue.pk in voided:
            continue
        remaining = issue.amount - allowances.get(issue.pk, ZERO)
        net += remaining
        if remaining > 0:
            open_invoices.append((issue, remaining))
    return {"records": records, "net": net, "open_invoices": open_invoices, "has_issue": bool(issues)}


def _locked_order(order_id):
    from sales.models import SalesOrder

    return SalesOrder.objects.select_for_update().get(pk=order_id)


def _audit(order, actor_name, description):
    from sales.models import OrderEvent

    OrderEvent.objects.create(order=order, event_type="invoice_updated", description=description, actor_name=actor_name)


@transaction.atomic
def issue_invoice(*, order_id, actor_name, invoice_number, invoice_date, amount, buyer_tax_id=""):
    from sales.models import InvoiceRecord, OrderOperationsProfile

    order = _locked_order(order_id)
    if order.is_cancelled_sale:
        raise ValidationError("取消或結案中的訂單不能再開立發票。")
    number = normalize_invoice_number(invoice_number)
    if InvoiceRecord.objects.filter(kind=InvoiceRecord.Kind.ISSUE, invoice_number=number).exists():
        raise ValidationError(f"發票 {number} 已登記過。")
    amount = Decimal(amount or 0)
    if amount <= 0:
        raise ValidationError("發票金額須大於 0。")
    tax_id = (buyer_tax_id or "").strip()
    if tax_id and not re.fullmatch(r"\d{8}", tax_id):
        raise ValidationError("統一編號須為 8 碼數字。")
    record = InvoiceRecord.objects.create(
        order=order, kind=InvoiceRecord.Kind.ISSUE, invoice_number=number, invoice_date=invoice_date,
        amount=amount, buyer_tax_id=tax_id, created_by=actor_name,
    )
    # 既有報表與搜尋讀取營運資料的尾款發票欄位；空白時帶入第一張發票。
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if profile and not profile.balance_invoice_number:
        profile.balance_invoice_number = number
        profile.invoice_date = profile.invoice_date or invoice_date
        profile.save(update_fields=["balance_invoice_number", "invoice_date", "updated_at"])
    _audit(order, actor_name, f"開立發票 {number}，金額 ${amount:,.0f}")
    return record


def _locked_issue(record_id):
    from sales.models import InvoiceRecord

    record = InvoiceRecord.objects.select_related("order").get(pk=record_id)
    order = _locked_order(record.order_id)
    if record.kind != InvoiceRecord.Kind.ISSUE:
        raise ValidationError("只能對開立的發票作廢或折讓。")
    if record.adjustments.filter(kind=InvoiceRecord.Kind.VOID).exists():
        raise ValidationError("此發票已作廢。")
    return order, record


def _require_reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("請填寫原因。")
    return reason[:250]


@transaction.atomic
def void_invoice(*, record_id, actor_name, invoice_date, reason):
    from sales.models import InvoiceRecord

    reason = _require_reason(reason)
    order, record = _locked_issue(record_id)
    if record.adjustments.filter(kind=InvoiceRecord.Kind.ALLOWANCE).exists():
        raise ValidationError("此發票已有折讓，不能再整張作廢；請以折讓處理餘額。")
    void = InvoiceRecord.objects.create(
        order=order, kind=InvoiceRecord.Kind.VOID, invoice_number=record.invoice_number, related_invoice=record,
        invoice_date=invoice_date, amount=record.amount, buyer_tax_id=record.buyer_tax_id, reason=reason,
        created_by=actor_name,
    )
    _audit(order, actor_name, f"作廢發票 {record.invoice_number}；原因：{reason}")
    return void


@transaction.atomic
def allowance_invoice(*, record_id, actor_name, invoice_date, amount, reason):
    from sales.models import InvoiceRecord

    reason = _require_reason(reason)
    order, record = _locked_issue(record_id)
    used = sum((a.amount for a in record.adjustments.filter(kind=InvoiceRecord.Kind.ALLOWANCE)), ZERO)
    remaining = record.amount - used
    amount = Decimal(amount or 0)
    if amount <= 0 or amount > remaining:
        raise ValidationError(f"折讓金額須大於 0 且不超過發票餘額 {remaining:,.0f} 元。")
    allowance = InvoiceRecord.objects.create(
        order=order, kind=InvoiceRecord.Kind.ALLOWANCE, invoice_number=record.invoice_number, related_invoice=record,
        invoice_date=invoice_date, amount=amount, buyer_tax_id=record.buyer_tax_id, reason=reason,
        created_by=actor_name,
    )
    _audit(order, actor_name, f"發票 {record.invoice_number} 折讓 ${amount:,.0f}；原因：{reason}")
    return allowance


def invoice_attention(order, summary=None):
    """需要處理的發票狀況；歷史匯入訂單沒有發票紀錄，不提醒。"""
    summary = summary or invoice_summary(order)
    if order.is_settled_closed and summary["net"] > 0:
        return f"訂單已取消或結案，仍有 ${summary['net']:,.0f} 發票未作廢或折讓。"
    if (order.cash_receivable_v2 and order.is_registration_complete and not order.is_cancelled_sale
            and not summary["has_issue"]):
        return "已完成領牌，尚未登記發票開立紀錄。"
    return ""
