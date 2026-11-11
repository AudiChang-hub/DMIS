"""鎖定前確認卡要列的值（T-130 第 3 層）：一律取資料庫現值，畫面看到的就是確認後會鎖定的值。"""
from django import template
from django.core.exceptions import ObjectDoesNotExist

from sales.models import RegistrationDocument
from sales.services.settlement_cost import resolve_settlement_cost

register = template.Library()


def _money(value):
    return f"{value or 0:,.0f} 元"


@register.simple_tag
def registration_lock_rows(order):
    """確認領牌完成前列出：領牌日、車牌、領牌規費試算、車輛結算成本、已上傳的領牌文件（領牌縣市已不使用，T-130）。
    文件全部選填（2026-11-11 T-145），只列份數供核對，不是完成條件。"""
    rows = [
        ("領牌日期", f"{order.registration_date:%Y/%m/%d}" if order.registration_date else "", not order.registration_date),
        ("車牌號碼", order.final_plate_number or "", not order.final_plate_number),
    ]
    rows.append(("領牌規費（試算）", _money(order.registration_calculated_total), False))
    try:
        profile = order.operations
    except ObjectDoesNotExist:
        profile = None
    rule = resolve_settlement_cost(order.vehicle_model_id, order.registration_date)
    if profile is not None and profile.vehicle_cost_manual:
        cost = f"{_money(profile.vehicle_cost)}（人工輸入）"
    elif profile is not None and profile.vehicle_cost_rule_id:
        cost = _money(profile.vehicle_cost)
    else:
        cost = _money(rule.amount) if rule else "找不到成本規則，無法完成"
    rows.append(("車輛結算成本", cost, False))
    uploaded = order.registration_documents.exclude(
        document_type__in=RegistrationDocument.retired_document_types()
    ).count()
    rows.append(("領牌文件", f"已上傳 {uploaded} 份（選填）", False))
    return [{"label": label, "value": value, "missing": missing} for label, value, missing in rows]
