"""文件身分的唯一來源；列印不依觀看者、來源或最新公司資料改寫歷史。"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from sales.models import PrintCompany, PrintCompanyChange, SalesOrder

FIELDS = ("legal_name", "tax_id", "address", "phone")


def company_data(company):
    return {**{key: getattr(company, key) for key in FIELDS}, "company_id": company.pk,
            "company_revision": company.revision, "saved_at": timezone.now().isoformat()}


def validate_header(data):
    if not isinstance(data, dict) or any(not str(data.get(key, "")).strip() for key in FIELDS):
        raise ValidationError("開單公司資料尚未確認或不完整，請聯絡 admin 設定後再列印。")
    return data


def initialize_company(order, user, *, assisted_company=None):
    """僅由正式下單入口呼叫，不能用目前帳號回推舊單。"""
    from sales.services.order_intake import account_profile
    profile = account_profile(user)
    if profile and profile.kind == "dealer":
        company = PrintCompany.objects.filter(source_id=profile.source_id).first() if profile.source_id else None
    elif assisted_company is not None:
        company = PrintCompany.objects.select_for_update().get(pk=assisted_company.pk)
        if order.source_type != "dealer" or company.source_id != order.source_id or company.revision != assisted_company.revision:
            raise ValidationError("代開公司資料已變更，請重新確認後再送出。")
        validate_header(company_data(company))
    else:
        company = PrintCompany.objects.filter(key="home").first()
    order.print_company = company
    order.print_company_snapshot = company_data(company) if company else {}


@transaction.atomic
def correct_order_company(*, user, pk, company_id, revision, reason, acknowledged):
    from sales.access.services import is_root
    if not is_root(user):
        raise PermissionDenied
    order = SalesOrder.objects.select_for_update().get(pk=pk)
    if order.revision != revision:
        raise ValidationError("訂單已被其他人更新，請重新整理後再確認。")
    if not reason.strip() or not acknowledged:
        raise ValidationError("請填寫原因並確認本次更正；已簽文件不會被覆寫。")
    company = PrintCompany.objects.select_for_update().get(pk=company_id)
    data = validate_header(company_data(company))
    if company.source_id and not company.source.active:
        raise ValidationError("此車行已停用，不能指定為新的開單公司。")
    PrintCompanyChange.objects.create(company=company, order=order, order_number=order.number, actor=user, reason=reason.strip(),
                                      before=order.print_company_snapshot, after=data)
    # 僅更新文件身分與版本，不觸發金額／收款同步，也不改簽名附件。
    SalesOrder.objects.filter(pk=order.pk).update(print_company=company, print_company_snapshot=data,
                                                revision=order.revision + 1, updated_at=timezone.now())
    return order
