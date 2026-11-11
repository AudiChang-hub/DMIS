"""領牌資料存檔後的連動（使用者 2026-11-11 T-147，取代 T-130／T-145 的鎖定確認卡）。

- 領牌日與車牌都填好就自動完成領牌，帶入規費、成本、獎勵、傭金，訂單轉待交車；文件選填。
- 完成後任何人、任何訂單狀態都能再改領牌日與車牌，不再有「改不了」的鎖。
- 改領牌日：系統算出的規費、牌照稅、領牌稅金收支，以及成本、獎勵、傭金依新日期重算；人工改過的值保留。
- 只改車牌：不重算任何金額。
- 已結算台數獎金的訂單維持訂單驗證原本的阻擋，不另做跨期處理（台數獎金流程由 T-148 重新設計）。
- 每次改領牌日或車牌都寫 OrderChange（改前、改後）。
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from sales.models import OrderChange, OrderEvent, OrderOperationsProfile
from sales.services.agency_fee import default_agency_fee, plate_fee_waived, registration_fee_cost
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.dealer_reward_campaign import apply_order_dealer_rewards
from sales.services.incentive_rule import apply_order_incentive_rule
from sales.services.operations_sync import sync_order_operations
from sales.services.settlement_cost import apply_order_settlement_cost, resolve_settlement_cost


def _date_text(value):
    return f"{value:%Y/%m/%d}" if value else "未填"


def record_registration_change(order, *, actor_name, before_date, before_plate):
    """改前、改後寫進 OrderChange；沒有變動時不寫。回傳 (日期有改, 車牌有改)。"""
    date_changed = order.registration_date != before_date
    plate_changed = (order.final_plate_number or "") != (before_plate or "")
    changes = {}
    if date_changed:
        changes["實際領牌日期"] = {"before": _date_text(before_date), "after": _date_text(order.registration_date)}
    if plate_changed:
        changes["車牌號碼"] = {"before": before_plate or "未填", "after": order.final_plate_number or "未填"}
    if changes:
        summary = "、".join(f"{label} {value['before']} → {value['after']}" for label, value in changes.items())
        OrderChange.objects.create(order=order, actor_name=actor_name, reason=f"領牌資料：{summary}", changes=changes)
    return date_changed, plate_changed


def finish_registration(order, actor_name):
    """完成領牌並固定成本、獎勵與傭金；回傳 (成功, 訊息)。"""
    if not resolve_settlement_cost(order.vehicle_model_id, order.registration_date):
        return False, "找不到符合機種及領牌日期的車輛結算成本規則，請先至車型資料補建後再完成領牌。"
    try:
        order.complete_registration(actor_name)
    except ValidationError as exc:
        return False, " ".join(exc.messages)
    apply_order_settlement_cost(order, actor_name, lock=True)
    apply_order_incentive_rule(order, actor_name, lock=True)
    apply_order_dealer_rewards(order, force=True)
    apply_order_dealer_commission(order, lock=True)
    OrderEvent.objects.create(
        order=order,
        event_type="registration_completed",
        description=f"領牌完成：{order.registration_date}／{order.final_plate_number}",
        actor_name=actor_name,
    )
    return True, "領牌階段已完成，訂單進入待交付。"


def _resync_registration_tax(order):
    """領牌稅金收支依新領牌日重算，人工改過的欄位保留。
    一般同步（sync_order_operations）不重算已完成與取消的訂單，這裡補上，任何狀態改領牌日都一致。"""
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if profile is None:
        return
    manual = set(profile.manual_financial_fields or [])
    if "registration_tax_expense" not in manual:
        profile.registration_tax_expense = Decimal(registration_fee_cost(order) or 0)
    if "registration_tax_income" not in manual:
        profile.registration_tax_income = Decimal("0") if plate_fee_waived(order) else profile.registration_tax_expense
    if "agency_fee_income" not in manual:
        profile.agency_fee_income = Decimal(default_agency_fee(order, profile) or 0)
    profile.save(update_fields=["registration_tax_expense", "registration_tax_income", "agency_fee_income", "updated_at"])


def _recalculate_after_date_change(order, actor_name):
    """已完成領牌的單改了領牌日：依新日期重套版本後再固定；人工輸入的值由各服務照舊保留。"""
    profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
    unlock = {"incentive_locked_at": None, "dealer_commission_locked_at": None}
    manual = set(profile.manual_financial_fields or [])
    if not (profile.vehicle_cost_manual or "vehicle_cost" in manual):
        unlock["vehicle_cost_locked_at"] = None
    OrderOperationsProfile.objects.filter(pk=profile.pk).update(**unlock)
    if "vehicle_cost_locked_at" in unlock:
        apply_order_settlement_cost(order, actor_name, lock=True)
    apply_order_incentive_rule(order, actor_name, lock=True)
    apply_order_dealer_rewards(order, force=True)
    apply_order_dealer_commission(order, lock=True)


@transaction.atomic
def apply_registration_edit(order, *, actor_name, before_date, before_plate):
    """領牌資料存檔後呼叫（訂單已存入新值）。回傳 {"completed": 本次自動完成領牌, "notes": [(等級, 訊息)]}。"""
    notes = []
    date_changed, _plate_changed = record_registration_change(
        order, actor_name=actor_name, before_date=before_date, before_plate=before_plate,
    )
    if date_changed:
        # 領牌稅金依新日期重算；人工改過的保留（使用者 2026-11-11 T-147，取代 11-07 T-127 p6「覆蓋人工金額」）。
        sync_order_operations(order.pk)
        _resync_registration_tax(order)
    if order.is_registration_complete:
        if date_changed and order.registration_date:
            _recalculate_after_date_change(order, actor_name)
        return {"completed": False, "notes": notes}
    # 尚未完成：依領牌日帶入（預估）成本、獎勵、傭金，資料齊全就自動完成。
    apply_order_settlement_cost(order, actor_name)
    apply_order_incentive_rule(order, actor_name)
    apply_order_dealer_rewards(order)
    apply_order_dealer_commission(order)
    completed = False
    if not order.missing_registration_requirements():
        completed, message = finish_registration(order, actor_name)
        notes.append(("success" if completed else "warning", message))
    return {"completed": completed, "notes": notes}
