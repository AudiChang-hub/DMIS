"""admin 把車輛改回現有庫存（可銷售）：停用、已售出、已預留、已交車、已調出都適用。

使用者 2026-10-19 選方案 B：只有 admin 能用、原因必填、交易內鎖定並留稽核；
還掛在訂單或調車單上的車先擋下，請到原流程處理；已售出、已交車要輸入引擎／車身號碼末 4 碼二次確認。
有領牌痕跡的車（刪單時已領牌）要選「當新車」或「當已領牌車（保留車牌、填再售價）」。
"""
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse

from sales.access.services import is_root
from sales.models import SalesOrder, VehicleInventory, VehicleInventoryHistory, VehicleTransferSignoff
from sales.services.inventory_history import STATUS_LABELS, status_change
from sales.services.order_deletion import DELETION_REVIEW_LABEL, is_order_delivered

Status = VehicleInventory.Status
RESTORABLE_STATUSES = (Status.INACTIVE, Status.SOLD, Status.RESERVED, Status.DELIVERED, Status.TRANSFERRED_OUT)
# 已售出、已交車改回庫存會讓報表與庫存數跟著變，要輸入識別號碼末 4 碼二次確認。
ACKNOWLEDGE_STATUSES = (Status.SOLD, Status.DELIVERED)
CONFIRM_FALLBACK = "確認改回"
MODE_NEW, MODE_REGISTERED = "new", "registered"
REASON_LIMIT = 500


def identifier_tail(vehicle):
    """二次確認要輸入的引擎／車身號碼末 4 碼（只取英數字）；沒有號碼時改輸入「確認改回」。"""
    tail = re.sub(r"[^0-9A-Za-z]", "", vehicle.engine_number or vehicle.frame_number or "")[-4:].upper()
    return tail or CONFIRM_FALLBACK


def identifier_matches(vehicle, value):
    typed = re.sub(r"\s", "", value or "").upper()
    return bool(typed) and typed == identifier_tail(vehicle)


def deletion_review_order(vehicle):
    """刪單時因已領牌而停用、還沒處理的車，回傳那張已刪除訂單。"""
    if vehicle.status != Status.INACTIVE:
        return None
    for order in (SalesOrder.all_objects.filter(deleted_at__isnull=False).exclude(deletion_effects={})
                  .order_by("-deleted_at", "-pk")):
        effect = (order.deletion_effects or {}).get("vehicle") or {}
        if effect.get("id") == vehicle.pk:
            return order if effect.get("after") == Status.INACTIVE else None
    return None


def deletion_review_vehicle_ids():
    """庫存列表標示「刪單待確認」用：停用中且停用來自刪單的車。"""
    latest = {}
    for order in (SalesOrder.all_objects.filter(deleted_at__isnull=False).exclude(deletion_effects={})
                  .order_by("deleted_at", "pk").only("pk", "deletion_effects")):
        effect = (order.deletion_effects or {}).get("vehicle") or {}
        if effect.get("id"):
            latest[effect["id"]] = effect.get("after")
    candidates = {pk for pk, after in latest.items() if after == Status.INACTIVE}
    return set(VehicleInventory.objects.filter(pk__in=candidates, status=Status.INACTIVE).values_list("pk", flat=True))


def registration_trace(vehicle, review_order=None):
    """有領牌痕跡時回傳 {plate, registered_on, source}；沒有則 None。"""
    if vehicle.registered_plate_number:
        return {"plate": vehicle.registered_plate_number, "registered_on": vehicle.registered_on, "source": "車輛已登記為領牌車"}
    order = review_order or deletion_review_order(vehicle)
    if order and (order.final_plate_number or order.registration_completed_at):
        return {"plate": order.final_plate_number, "registered_on": order.registration_date,
                "source": f"刪除的訂單 {order.number} 已領牌"}
    return None


def restore_blockers(vehicle):
    """回傳 [(說明, 連結, 連結文字)]；有任何一項就不能改回。"""
    if vehicle.status not in RESTORABLE_STATUSES:
        return [(f"這台車目前是「{vehicle.get_status_display()}」，已經在現有庫存裡，不需要改回。", "", "")]
    blockers = []
    order = SalesOrder.objects.filter(allocated_vehicle=vehicle).first()
    if order:
        if is_order_delivered(order):
            text = (f"仍屬於已交車的訂單 {order.number}（{order.display_status}）。車已交給客人，"
                    "改回庫存會讓同一台車同時在訂單與庫存；要退車請先洽 admin，目前系統沒有交車後退車的流程。")
        else:
            text = (f"仍配給訂單 {order.number}（{order.display_status}）。請到訂單頁取消、改配或例外結案，"
                    "車輛會自動回到庫存。")
        blockers.append((text, reverse("order_detail", args=[order.pk]), "開啟訂單"))
    pending = vehicle.transfer_signoffs.filter(status=VehicleTransferSignoff.Status.PENDING, voided_at__isnull=True).first()
    if pending:
        blockers.append((f"在預備調車 {pending.number} 中，請先取消預備調車。",
                         reverse("transfer_signoff_detail", args=[pending.pk]), "開啟調車單"))
    if vehicle.status == Status.TRANSFERRED_OUT:
        signed = (vehicle.transfer_signoffs.filter(status=VehicleTransferSignoff.Status.SIGNED, voided_at__isnull=True)
                  .order_by("-signed_at", "-id").first())
        if signed:
            blockers.append((f"由調車簽收 {signed.number} 調出。請在調車單用「作廢調車簽收」改回，簽收紀錄才會一致。",
                             reverse("transfer_signoff_detail", args=[signed.pk]), "開啟調車單"))
    return blockers


def restore_impacts(vehicle):
    impacts = ["改為「可銷售」後列入現有庫存、配車候選與戰情的庫存台數。"]
    if vehicle.status in ACKNOWLEDGE_STATUSES:
        impacts.append(f"這台車原本是「{vehicle.get_status_display()}」：「已售出／調出」分頁少一台、現有庫存多一台；"
                       "以庫存計算的報表與匯出會跟著變。銷售台數、淨利與佣金以訂單計，不受影響。")
    if vehicle.status == Status.TRANSFERRED_OUT:
        impacts.append("「已售出／調出」分頁少一台，現有庫存多一台。")
    if vehicle.disposition or vehicle.disposition_dealer_id or vehicle.disposition_dealer_name:
        impacts.append(f"清除去向紀錄（{vehicle.get_disposition_display() or '未分類'} {vehicle.disposition_target_label}）；原值留在異動紀錄。")
    return impacts


def inventory_restore_summary(vehicle, user):
    """車輛詳細頁的入口資訊；不是 admin 或不適用時回傳 None。"""
    if not is_root(user) or vehicle.status not in RESTORABLE_STATUSES:
        return None
    review = deletion_review_order(vehicle)
    return {"blocked": bool(restore_blockers(vehicle)), "review_order": review, "review_label": DELETION_REVIEW_LABEL if review else "",
            "url": reverse("inventory_restore", args=[vehicle.pk])}


def _parse_price(value):
    try:
        price = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None
    return price if price > 0 and price == price.to_integral_value() else None


@transaction.atomic
def restore_to_stock(*, user, vehicle_id, reason, expected_updated_at, actor_name="", mode="",
                     resale_price=None, confirm_identifier=""):
    if not is_root(user):
        raise PermissionDenied("只有 admin 可以把車輛改回現有庫存。")
    try:
        vehicle = VehicleInventory.objects.select_for_update(of=("self",)).get(pk=vehicle_id)
    except VehicleInventory.DoesNotExist as exc:
        raise ValidationError("找不到這台車，請重新整理。") from exc
    if expected_updated_at != vehicle.updated_at.isoformat():
        raise ValidationError("車輛資料已被更新，請重新載入後再確認。")
    reason = (reason or "").strip()
    if not reason or len(reason) > REASON_LIMIT:
        raise ValidationError(f"請填寫改回庫存的原因，最多 {REASON_LIMIT} 字。")
    blockers = restore_blockers(vehicle)
    if blockers:
        raise ValidationError([text for text, _url, _label in blockers])
    if vehicle.status in ACKNOWLEDGE_STATUSES and not identifier_matches(vehicle, confirm_identifier):
        raise ValidationError(f"這台車是「{vehicle.get_status_display()}」，請輸入引擎／車身號碼末 4 碼確認；輸入的號碼不符。")
    review = deletion_review_order(vehicle)
    trace = registration_trace(vehicle, review)
    if trace and mode not in {MODE_NEW, MODE_REGISTERED}:
        raise ValidationError("這台車有領牌紀錄，請選擇要當新車還是已領牌車改回。")
    price = None
    if trace and mode == MODE_REGISTERED:
        if not trace["plate"]:
            raise ValidationError("原訂單沒有車牌號碼，無法當已領牌車改回；請改選當新車，或先補登車牌。")
        price = _parse_price(resale_price)
        if price is None:
            raise ValidationError("請填寫領牌車再售價（大於 0 的整數）。")

    before = {
        "status": vehicle.status,
        "disposition": " ".join(p for p in (vehicle.get_disposition_display() if vehicle.disposition else "",
                                            vehicle.disposition_target_label, str(vehicle.disposition_on or "")) if p),
        "plate": vehicle.registered_plate_number,
        "resale_price": vehicle.resale_price,
    }
    vehicle.status = Status.AVAILABLE
    vehicle.disposition, vehicle.disposition_dealer, vehicle.disposition_dealer_name, vehicle.disposition_on = "", None, "", None
    if trace and mode == MODE_REGISTERED:
        vehicle.registered_plate_number = trace["plate"]
        vehicle.registered_on = trace["registered_on"]
        vehicle.resale_price = price
    elif trace:
        vehicle.registered_plate_number, vehicle.registered_on, vehicle.resale_price = "", None, None
    vehicle.save(update_fields=["status", "disposition", "disposition_dealer", "disposition_dealer_name", "disposition_on",
                                "registered_plate_number", "registered_on", "resale_price", "updated_at"])

    changes = {"status": status_change(before["status"], vehicle.status)}
    if before["disposition"]:
        changes["disposition"] = {"label": "去向", "before": before["disposition"], "after": "未記錄"}
    if before["plate"] != vehicle.registered_plate_number:
        changes["registered_plate_number"] = {"label": "已領牌車牌", "before": before["plate"] or "未設定",
                                              "after": vehicle.registered_plate_number or "未設定"}
    if before["resale_price"] != vehicle.resale_price:
        changes["resale_price"] = {"label": "領牌車再售價",
                                   "before": f"{before['resale_price']:,.0f}" if before["resale_price"] is not None else "未設定",
                                   "after": f"{vehicle.resale_price:,.0f}" if vehicle.resale_price is not None else "未設定"}
    if trace:
        changes["mode"] = {"label": "改回方式", "value": "已領牌車（保留車牌）" if mode == MODE_REGISTERED else "新車（不採用領牌紀錄）"}
    if review:
        changes["review"] = {"label": "後續處理", "value": f"{DELETION_REVIEW_LABEL}已處理（刪除的訂單 {review.number}）"}
    VehicleInventoryHistory.objects.create(
        vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED, actor_name=actor_name or user.get_username(),
        reason=f"改回現有庫存（原為{STATUS_LABELS.get(before['status'], before['status'])}）：{reason}", changes=changes,
        status_snapshot=vehicle.status, location_store_snapshot=vehicle.location_store,
        location_label_snapshot=vehicle.actual_location_label, condition_note_snapshot=vehicle.condition_note,
        condition_resolution_snapshot=vehicle.condition_resolution,
    )
    return vehicle
