"""鎖定前確認卡要列的值（T-130 第 3 層）：一律取資料庫現值，畫面看到的就是確認後會鎖定的值。"""
from django import template
from django.core.exceptions import ObjectDoesNotExist

from sales.services.settlement_cost import resolve_settlement_cost

register = template.Library()


def _money(value):
    return f"{value or 0:,.0f} 元"


@register.simple_tag
def registration_lock_rows(order):
    """確認領牌完成前列出：領牌日、車牌、縣市、領牌規費試算、車輛結算成本、必備文件。"""
    rows = [
        ("領牌日期", f"{order.registration_date:%Y/%m/%d}" if order.registration_date else "", not order.registration_date),
        ("車牌號碼", order.final_plate_number or "", not order.final_plate_number),
    ]
    if order.registration_county:
        rows.append(("領牌縣市", order.get_registration_county_display(), False))
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
    required = list(order.required_registration_document_types())
    uploaded = set(order.registration_documents.values_list("document_type", flat=True))
    rows.append(("必備文件", f"已上傳 {len(uploaded & set(required))}／{len(required)}", False))
    return [{"label": label, "value": value, "missing": missing} for label, value, missing in rows]
