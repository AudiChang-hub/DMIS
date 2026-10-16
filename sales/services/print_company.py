"""文件身分的唯一來源；列印不依觀看者、來源或最新公司資料改寫歷史。"""
from django.core.exceptions import ValidationError
from django.utils import timezone

from sales.models import PrintCompany, SalesOrder

FIELDS = ("legal_name", "tax_id", "address", "phone")


def company_data(company):
    return {**{key: getattr(company, key) for key in FIELDS}, "company_id": company.pk,
            "company_revision": company.revision, "saved_at": timezone.now().isoformat()}


def validate_header(data):
    if not isinstance(data, dict) or any(not str(data.get(key, "")).strip() for key in FIELDS):
        raise ValidationError("開單公司資料尚未確認或不完整，請聯絡 admin 設定後再列印。")
    return data


def initialize_company(order, user):
    """僅由正式下單入口呼叫：新訂單一律保留本店公司資料（使用者 2026-10-16）。"""
    company = PrintCompany.objects.filter(key="home").first()
    order.print_company = company
    order.print_company_snapshot = company_data(company) if company else {}


def ensure_order_company(order):
    """沒有開單公司的訂單（多為 Excel 匯入）一律用馭盛（本店公司），不再等 admin 逐筆確認（使用者 2026-10-13）。

    第一次列印或簽署時保存當下的馭盛資料，之後不隨公司資料變動；早期已保留其他公司的訂單不受影響。
    """
    if order.print_company_snapshot:
        return order
    company = PrintCompany.objects.filter(key="home").first()
    if company is None:
        return order
    data = company_data(company)
    try:
        validate_header(data)
    except ValidationError:
        return order
    if SalesOrder.objects.filter(pk=order.pk, print_company_snapshot={}).update(print_company=company, print_company_snapshot=data):
        order.print_company, order.print_company_snapshot = company, data
    else:
        order.refresh_from_db(fields=["print_company", "print_company_snapshot"])
    return order
