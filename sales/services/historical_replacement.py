"""有限範圍的歷史匯入更正；不解鎖真實已領牌／交付訂單。"""
import hashlib
import json
from decimal import Decimal

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from sales.models import (
    DeliveryRecord, LegacyImportBatch, LegacyImportRow, LegacyImportCorrection, LegacySalesSnapshot,
    OrderChange, OrderEvent, OrderOperationsProfile, PaymentRecord,
    RegistrationDocument, SalesOrder, VehicleInventory, VehicleInventoryHistory,
    normalize_vehicle_identifier,
)
from .financial_refresh import lock_bonus_periods
from .legacy_import import retry_completed_import_row

SALT = "historical-buyer-replacement-v1"


@transaction.atomic
def prepare_replacement_review(*, row, mapping, reason, user, order_id=None):
    """只儲存本列，接到確認頁；絕不在導頁階段取消或建立訂單。"""
    require_admin(user)
    from .legacy_import import _json_clean_value
    from .import_row_review import build_import_row_review
    batch = LegacyImportBatch.objects.select_for_update().get(pk=row.batch_id)
    row = LegacyImportRow.objects.select_for_update().get(pk=row.pk, batch_id=batch.pk)
    row.batch = batch
    before = dict(row.mapped_data)
    row.mapped_data = {**before, **{key: _json_clean_value(value) for key, value in mapping.items()}}
    if "identifier_raw" in mapping:
        row.mapped_data["identifier"] = normalize_vehicle_identifier(mapping["identifier_raw"]) or ""
    candidates = build_import_row_review(row, {})["replacement_candidates"]
    if order_id:
        candidates = [order for order in candidates if str(order.pk) == str(order_id)]
        if not candidates:
            raise ValueError("原訂單與目前填寫的車號／買家不符，請重新核對；尚未執行退訂或補匯。")
    elif not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("同號碼有多筆占用訂單，請從上方清單選擇要核對的原買家，不會自動決定。")
    row.manually_corrected = True
    row.corrected_by = user.get_username()
    row.corrected_at = timezone.now()
    row.save(update_fields=["mapped_data", "manually_corrected", "corrected_by", "corrected_at", "updated_at"])
    LegacyImportCorrection.objects.create(row=row, decision=LegacyImportCorrection.Decision.CORRECT,
        before_data=before, after_data=row.mapped_data, reason=reason, corrected_by=user.get_username())
    return candidates[0]


def require_admin(user):
    if not (user.is_authenticated and user.is_active and user.is_superuser and user.get_username() == "admin"):
        raise PermissionDenied("只有 admin 可以更正歷史退訂換買家。")


def replacement_preview(row, order):
    blockers = []
    snapshot = LegacySalesSnapshot.objects.filter(order=order).select_related("import_row").first()
    vehicle = order.allocated_vehicle
    identifier = normalize_vehicle_identifier(row.mapped_data.get("identifier_raw") or row.mapped_data.get("identifier"))
    if row.batch.status != LegacyImportBatch.Status.COMPLETED or row.action != LegacyImportRow.Action.ERROR or row.committed_model or row.committed_pk or row.sheet_name != "銷貨":
        blockers.append("本列不是已完成批次中尚待補匯的銷貨資料，可能已經處理。")
    if row.mapped_data.get("vehicle_category") != SalesOrder.VehicleCategory.NEW or order.vehicle_category != SalesOrder.VehicleCategory.NEW:
        blockers.append("此流程僅供新車退訂換買家；中古交易需另行核對。")
    if not vehicle or not identifier or identifier not in {vehicle.normalized_engine_number, vehicle.normalized_frame_number}:
        blockers.append("來源列與原訂單配車不相符，不能解除其他車輛。")
    if row.mapped_data.get("identifier") != identifier:
        blockers.append("暫存識別號碼與原始輸入不同，請先重新核對並儲存本列。")
    if vehicle and vehicle.status != VehicleInventory.Status.SOLD:
        blockers.append("車輛不是歷史已售狀態，請先核對庫存，不可覆蓋其他車況。")
    if not snapshot or order.status != SalesOrder.Status.COMPLETED or order.delivered_by != "歷史資料匯入" or (order.registration_completed_at and order.registration_completed_by != "歷史資料匯入"):
        blockers.append("只可更正由歷史匯入標記完成的訂單，不可解鎖正式交付訂單。")
    if DeliveryRecord.objects.filter(order=order).exists() or RegistrationDocument.objects.filter(order=order).exists() or order.final_plate_number:
        blockers.append("原訂單已有交付紀錄、領牌文件或車牌，請先由管理者釐清真實交付／領牌證據；此處不能直接取消。")
    if order.dealer_volume_bonus_allocations.exists():
        blockers.append("原訂單已有結算台數獎金，禁止直接取消或更動已結算資料。")
    if row.mapped_data.get("owner_name", "").strip() == order.owner_name.strip():
        blockers.append("本次買家姓名與原單相同，請使用原訂單更正，不可當作換買家。")
    payments = list(order.payment_records.order_by("pk"))
    recorded = max(sum((p.received_amount for p in payments), Decimal("0")), order.deposit_amount)
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    financials = []
    if profile:
        for field in profile._meta.fields:
            if field.get_internal_type() == "DecimalField" and getattr(profile, field.name):
                financials.append({"label": field.verbose_name, "value": getattr(profile, field.name)})
    state = {
        "row": list(LegacyImportRow.objects.filter(pk=row.pk).values()),
        "batch_status": row.batch.status,
        "order": list(SalesOrder.objects.filter(pk=order.pk).values()),
        "vehicle": list(VehicleInventory.objects.filter(pk=order.allocated_vehicle_id).values()),
        "payments": list(order.payment_records.order_by("pk").values()),
        "profile": list(OrderOperationsProfile.objects.filter(order=order).values()),
        "snapshot": list(LegacySalesSnapshot.objects.filter(order=order).values()),
        "allocations": list(order.dealer_volume_bonus_allocations.order_by("pk").values()),
        "blockers": blockers,
    }
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    return {"row": row, "order": order, "vehicle": vehicle, "blockers": blockers,
            "recorded_received": recorded, "payments": payments, "financials": financials, "digest": digest}


def preview_token(preview, user):
    return signing.dumps({"digest": preview["digest"], "user": user.pk}, salt=SALT)


@transaction.atomic
def replace_historical_buyer(*, row_id, order_id, user, data):
    require_admin(user)
    batch_id = LegacyImportRow.objects.values_list("batch_id", flat=True).get(pk=row_id)
    batch = LegacyImportBatch.objects.select_for_update().get(pk=batch_id)
    row = LegacyImportRow.objects.select_for_update().get(pk=row_id)
    row.batch = batch
    order = SalesOrder.objects.select_for_update().get(pk=order_id)
    lock_bonus_periods(order)
    if order.allocated_vehicle_id:
        order.allocated_vehicle = VehicleInventory.objects.select_for_update().get(pk=order.allocated_vehicle_id)
    list(PaymentRecord.objects.select_for_update().filter(order=order).order_by("pk"))
    list(OrderOperationsProfile.objects.select_for_update().filter(order=order))
    preview = replacement_preview(row, order)
    if preview["blockers"]:
        raise ValidationError(preview["blockers"])
    try:
        token = signing.loads(data.get("preview_token", ""), salt=SALT, max_age=900)
    except signing.BadSignature as exc:
        raise ValidationError("核對頁面已過期或無效，請重新開啟並確認。") from exc
    if token != {"digest": preview["digest"], "user": user.pk}:
        raise ValidationError("預覽後資料已變更，請重新開啟核對頁，不能套用舊資料。")
    # Service 本身也驗證聲明，防止繞過 view 直接呼叫。
    from sales.historical_replacement import HistoricalReplacementForm
    form = HistoricalReplacementForm(data, preview=preview)
    if not form.is_valid():
        raise ValidationError([message for errors in form.errors.values() for message in errors])
    facts = form.cleaned_data
    actor = user.get_username()
    now = timezone.now()
    vehicle = order.allocated_vehicle
    changes = {
        "status": SalesOrder.Status.CANCELLED, "allocated_vehicle_id": None,
        "registration_date": None, "registration_completed_at": None, "registration_completed_by": "",
        "delivered_at": None, "delivered_by": "", "cancellation_requested_at": now,
        "cancellation_requested_by": actor, "cancellation_reason": facts["reason"],
        "cancellation_note": f"歷史匯入退訂更正；本次來源列 {row.pk}。已確認未實際領牌／交車及財務、實物核對完成。",
        "cancellation_completed_at": now, "cancellation_completed_by": actor,
        "refund_amount": facts["actual_received"], "refund_completed_on": facts.get("refund_on"),
        "refund_method": facts.get("refund_method", ""), "refund_reference": facts.get("refund_reference", ""),
        "revision": order.revision + 1, "updated_at": now,
    }
    audit = {key: {"before": str(getattr(order, key)), "after": str(value)} for key, value in changes.items()}
    # 歷史費率不可因清除誤標領牌時間而重套今日費率。此專用交易保留原付款／營運快照，
    # 明確更新狀態與稽核；OrderChange/OrderEvent 共用 signal 更新搜尋索引。
    SalesOrder.objects.filter(pk=order.pk).update(**changes)
    VehicleInventory.objects.filter(pk=vehicle.pk).update(status=VehicleInventory.Status.AVAILABLE, updated_at=now)
    VehicleInventoryHistory.objects.create(vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED,
        actor_name=actor, reason=f"歷史退訂更正 {order.number}，解除原配車供本列補匯",
        changes={"status": {"before": vehicle.status, "after": VehicleInventory.Status.AVAILABLE}},
        status_snapshot=VehicleInventory.Status.AVAILABLE, location_store_snapshot=vehicle.location_store,
        location_label_snapshot=vehicle.actual_location_label, condition_note_snapshot=vehicle.condition_note,
        condition_resolution_snapshot=vehicle.condition_resolution)
    pending_order = None
    if facts["incoming_status"] == "pending":
        pending_order = {"vehicle_price": facts["pending_vehicle_price"], "balance": facts["pending_balance"], "reason": facts["reason"]}
    result = retry_completed_import_row(row, {}, "correct", f"原單 {order.number} 歷史退訂更正：{facts['reason']}", actor, pending_order=pending_order)
    if not result["ok"]:
        raise ValidationError(f"新買家補匯失敗，原單、配車及所有異動均已回復：{result['error']}")
    row.refresh_from_db()
    new_order = SalesOrder.objects.get(pk=row.committed_pk)
    if new_order.allocated_vehicle_id != vehicle.pk:
        raise ValidationError("同號碼對應到不同庫存車輛，已回復所有異動。請核對完整重複清單，不可自動改配其他車輛。")
    OrderChange.objects.create(order=order, reason=f"歷史退訂換買家；補匯新單 {new_order.number}；{facts['reason']}", changes=audit, actor_name=actor)
    OrderEvent.objects.create(order=order, event_type="historical_buyer_replaced", description=f"已更正歷史匯入退訂狀態，保留原收支；實際已退清 {facts['actual_received']} 元。新單 {new_order.number}。", actor_name=actor)
    OrderEvent.objects.create(order=new_order, event_type="historical_buyer_replacement", description=f"由歷史退訂更正補匯，原單 {order.number}。新單進度：{new_order.get_status_display()}。未轉移原單收款；{facts['reason']}", actor_name=actor)
    return new_order
