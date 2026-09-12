"""歷史銷貨同買家改期：更新原單，不重建訂單或改配。"""
from copy import copy
from datetime import datetime, time
import hashlib
import json

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from sales.models import (
    DealerVehicleRewardPlan, DealerVolumeBonusSettlement, DeliveryRecord,
    LegacyImportBatch, LegacyImportCorrection, LegacyImportRow, LegacySalesSnapshot,
    OrderChange, OrderEvent, OrderOperationsProfile, PaymentRecord, RegistrationDocument,
    SalesOrder, VehicleInventory, VehicleInventoryHistory, normalize_vehicle_identifier,
)
from .dealer_commission import matching_bonus_rules, resolve_dealer_brand_policy
from .financial_refresh import lock_bonus_periods
from .historical_replacement import require_admin
from .import_row_review import build_import_row_review, same_import_buyer
from .incentive_rule import resolve_incentive_rule
from .legacy_import import _sales_transaction_key
from .settlement_cost import resolve_settlement_cost

SALT = "historical-registration-date-v1"
EVENT = "historical_date_changed"


def incoming_date(row):
    try:
        return parse_date(str(row.mapped_data.get("registration_date") or ""))
    except ValueError:
        return None


def financial_reference(order, day):
    """僅讀取目前主檔在指定日期的版本參考，不模擬儲存／重算歷史金額。"""
    cost = resolve_settlement_cost(order.vehicle_model_id, day)
    incentive = resolve_incentive_rule(order.vehicle_model_id, day)
    policy = resolve_dealer_brand_policy(order.source_id, order.vehicle_model, day)
    plans = DealerVehicleRewardPlan.objects.filter(vehicle_model_id=order.vehicle_model_id, active=True,
        effective_from__lte=day).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day)) if day else DealerVehicleRewardPlan.objects.none()
    reference = {
        "車輛成本": f"版本 #{cost.pk}：{cost.amount} 元" if cost else "無適用版本（不代表實際成本為零）",
        "原廠獎勵與補助": (f"版本 #{incentive.pk}：實銷 {incentive.sales_bonus}／促銷 {incentive.promotion_subsidy}／分期 {incentive.installment_interest_subsidy}" if incentive else "無適用版本"),
        "車行傭金": (f"車型基礎 {order.vehicle_model.base_dealer_commission} 元；加減版本 #{policy.pk}：{policy.commission_adjustment} 元" if policy else f"車型基礎 {order.vehicle_model.base_dealer_commission} 元；無車行加減版本") if order.source_type == SalesOrder.SourceType.DEALER else "非合作車行來源，不套用車行基礎傭金",
        "實物／紅包／禮券／點數": "；".join(f"版本 #{plan.pk}：{plan.reward_summary}" for plan in plans.prefetch_related("items").order_by("pk")) or "無適用方案",
    }
    candidate = copy(order)
    candidate.registration_date = day
    rules = matching_bonus_rules(candidate, order.commission_recipient_id or order.source_id)
    reference["台數獎金適用規則"] = "、".join(f"#{pk}" for pk in rules.order_by("pk").values_list("pk", flat=True)) or "無適用規則"
    return reference


def settled_period(order, day):
    candidate = copy(order)
    candidate.registration_date = day
    dealer_id = order.commission_recipient_id or order.source_id
    if not dealer_id or not day:
        return False
    return DealerVolumeBonusSettlement.objects.filter(dealer_id=dealer_id,
        rule__in=matching_bonus_rules(candidate, dealer_id),
        period__starts_on__lte=day, period__ends_on__gte=day).exists()


def date_change_preview(row, order):
    blockers = []
    day = incoming_date(row)
    vehicle = order.allocated_vehicle
    snapshot = LegacySalesSnapshot.objects.filter(order=order).first()
    identifier = normalize_vehicle_identifier(row.mapped_data.get("identifier_raw") or row.mapped_data.get("identifier"))
    if row.batch.status != LegacyImportBatch.Status.COMPLETED or row.action != LegacyImportRow.Action.ERROR or row.committed_model or row.committed_pk or row.excluded or row.sheet_name != "銷貨":
        blockers.append("本列不是已完成批次中尚待處理的銷貨錯誤列，可能已經更新。")
    if row.mapped_data.get("vehicle_category") != SalesOrder.VehicleCategory.NEW or order.vehicle_category != SalesOrder.VehicleCategory.NEW:
        blockers.append("此流程只處理同一筆新車交易；中古轉售不能當成改期。")
    if not identifier or not vehicle or identifier not in {vehicle.normalized_engine_number, vehicle.normalized_frame_number} or row.mapped_data.get("identifier") != identifier:
        blockers.append("本列與原訂單配車不相符，不能更新其他車輛。")
    if not same_import_buyer(row.mapped_data, order):
        blockers.append("車主姓名或證號不同，不能當成同買家改期。")
    historical_complete = order.status == SalesOrder.Status.COMPLETED and order.delivered_by == "歷史資料匯入"
    corrected_pending = order.status == SalesOrder.Status.ALLOCATED and not order.delivered_at and not order.registration_completed_at and OrderEvent.objects.filter(order=order, event_type=EVENT).exists()
    if not snapshot or not (historical_complete or corrected_pending) or (order.registration_completed_at and order.registration_completed_by != "歷史資料匯入"):
        blockers.append("只可更正歷史匯入完成標記或本流程的待辦訂單，正式訂單須走原領牌流程。")
    if vehicle and vehicle.status != (VehicleInventory.Status.SOLD if historical_complete else VehicleInventory.Status.RESERVED):
        blockers.append("庫存車況與原單進度不符，請先核對，不會覆蓋庫存狀態。")
    if order.final_plate_number or RegistrationDocument.objects.filter(order=order).exists() or DeliveryRecord.objects.filter(order=order).exists():
        blockers.append("已有車牌、領牌文件或正式交付紀錄，不能直接更正歷史完成狀態。")
    if not day:
        blockers.append("本次領牌日期無效或空白，請返回來源列修正。")
    elif day == order.registration_date:
        blockers.append("本次日期與原單相同，沒有改期差異；請核對是否重複匯入。")
    if order.dealer_volume_bonus_allocations.exists() or settled_period(order, order.registration_date) or settled_period(order, day):
        blockers.append("原單或目標領牌期間已有結算台數獎金，不能變更已結算清單。")
    old_reference, new_reference = financial_reference(order, order.registration_date), financial_reference(order, day)
    impacts = [{"label": key, "before": value, "after": new_reference[key], "changed": value != new_reference[key]} for key, value in old_reference.items()]
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    financials = [{"label": field.verbose_name, "value": getattr(profile, field.name)} for field in profile._meta.fields if field.get_internal_type() == "DecimalField"] if profile else []
    comparison = next((item for item in build_import_row_review(row, {})["comparisons"] if item["order"].pk == order.pk), None)
    state = {
        "row": list(LegacyImportRow.objects.filter(pk=row.pk).values()), "batch_status": row.batch.status,
        "order": list(SalesOrder.objects.filter(pk=order.pk).values()),
        "vehicle": list(VehicleInventory.objects.filter(pk=order.allocated_vehicle_id).values()),
        "payments": list(order.payment_records.order_by("pk").values()),
        "profile": list(OrderOperationsProfile.objects.filter(order=order).values()),
        "snapshot": list(LegacySalesSnapshot.objects.filter(order=order).values()),
        "blockers": blockers, "impacts": impacts,
    }
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    return {"row": row, "order": order, "day": day, "blockers": blockers, "impacts": impacts,
        "financials": financials, "comparison": comparison, "digest": digest}


def date_preview_token(preview, user):
    return signing.dumps({"digest": preview["digest"], "user": user.pk}, salt=SALT)


@transaction.atomic
def change_historical_date(*, row_id, order_id, user, data):
    require_admin(user)
    batch_id = LegacyImportRow.objects.values_list("batch_id", flat=True).get(pk=row_id)
    batch = LegacyImportBatch.objects.select_for_update().get(pk=batch_id)
    row = LegacyImportRow.objects.select_for_update().get(pk=row_id)
    row.batch = batch
    order = SalesOrder.objects.select_for_update().get(pk=order_id)
    lock_bonus_periods(order)
    target = copy(order)
    target.registration_date = incoming_date(row)
    target.registration_completed_at = timezone.now()
    lock_bonus_periods(target)
    if order.allocated_vehicle_id:
        order.allocated_vehicle = VehicleInventory.objects.select_for_update().get(pk=order.allocated_vehicle_id)
    list(PaymentRecord.objects.select_for_update().filter(order=order).order_by("pk"))
    list(OrderOperationsProfile.objects.select_for_update().filter(order=order))
    preview = date_change_preview(row, order)
    if preview["blockers"]:
        raise ValidationError(preview["blockers"])
    try:
        token = signing.loads(data.get("preview_token", ""), salt=SALT, max_age=900)
    except signing.BadSignature as exc:
        raise ValidationError("核對頁面已過期或無效，請重新開啟。") from exc
    if token != {"digest": preview["digest"], "user": user.pk}:
        raise ValidationError("預覽後資料已變更，請重新核對。")
    from sales.historical_date_change import HistoricalDateChangeForm
    form = HistoricalDateChangeForm(data, preview=preview)
    if not form.is_valid():
        raise ValidationError([error for errors in form.errors.values() for error in errors])
    facts = form.cleaned_data
    now, actor = timezone.now(), user.get_username()
    changes = {"registration_date": preview["day"], "revision": order.revision + 1, "updated_at": now}
    if order.established_on is None:
        changes["established_on"] = preview["day"]
    if facts["date_kind"] == "planned":
        changes.update(status=SalesOrder.Status.ALLOCATED, registration_completed_at=None,
            registration_completed_by="", delivered_at=None, delivered_by="")
    else:
        changes["registration_completed_at"] = timezone.make_aware(datetime.combine(preview["day"], time(hour=12)))
    audit = {key: {"before": str(getattr(order, key)), "after": str(value)} for key, value in changes.items()}
    # 不呼叫整單 save：避免歷史收支因今日主檔、試算或 signals 被重套。
    SalesOrder.objects.filter(pk=order.pk).update(**changes)
    vehicle = order.allocated_vehicle
    if facts["date_kind"] == "planned" and vehicle.status != VehicleInventory.Status.RESERVED:
        VehicleInventory.objects.filter(pk=vehicle.pk).update(status=VehicleInventory.Status.RESERVED, updated_at=now)
        VehicleInventoryHistory.objects.create(vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED,
            actor_name=actor, reason=f"歷史改期 {order.number}：尚待領牌交車，保留原配車",
            changes={"status": {"before": vehicle.status, "after": VehicleInventory.Status.RESERVED}},
            status_snapshot=VehicleInventory.Status.RESERVED, location_store_snapshot=vehicle.location_store,
            location_label_snapshot=vehicle.actual_location_label, condition_note_snapshot=vehicle.condition_note,
            condition_resolution_snapshot=vehicle.condition_resolution)
    before = dict(row.mapped_data)
    row.action = LegacyImportRow.Action.UPDATE
    row.committed_model, row.committed_pk = "SalesOrder", str(order.pk)
    row.natural_key = _sales_transaction_key(row.mapped_data)
    row.messages = [f"已更新原訂單 {order.number} 的領牌日期；未新增訂單，其他來源欄位與原收支未覆寫。"]
    row.manually_corrected, row.corrected_by, row.corrected_at = True, actor, now
    row.save(update_fields=["action", "committed_model", "committed_pk", "natural_key", "messages", "manually_corrected", "corrected_by", "corrected_at", "updated_at"])
    LegacyImportCorrection.objects.create(row=row, decision=LegacyImportCorrection.Decision.CORRECT,
        before_data=before, after_data=row.mapped_data, reason=f"領牌改期更新原單 {order.number}；{facts['reason']}", corrected_by=actor)
    result = dict(batch.result_summary or {})
    result["errors"] = max(int(result.get("errors", 0)) - 1, 0)
    result["updated"] = int(result.get("updated", 0)) + 1
    batch.result_summary = result
    batch.save(update_fields=["result_summary", "updated_at"])
    audit["日期性質"] = {"before": "歷史匯入／上次更正", "after": dict(form.fields["date_kind"].choices)[facts["date_kind"]]}
    audit["主檔參考差異（未自動套用）"] = {"before": {i["label"]: i["before"] for i in preview["impacts"]}, "after": {i["label"]: i["after"] for i in preview["impacts"]}}
    OrderChange.objects.create(order=order, reason=f"歷史領牌改期；{facts['reason']}", changes=audit, actor_name=actor)
    OrderEvent.objects.create(order=order, event_type=EVENT,
        description=f"來源列 {row.pk}：領牌日期 {order.registration_date} → {preview['day']}。{audit['日期性質']['after']}；保留原配車、收支與原始快照，其他 Excel 欄位未更新；{facts['reason']}", actor_name=actor)
    order.refresh_from_db()
    return order
