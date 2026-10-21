"""交車後退車：已交車的訂單由 admin 作廢，款項只做紀錄沖回，車輛以已領牌車回到庫存。

使用者 2026-10-19 選方案 A：沿用「例外結案」狀態（不加 migration），訂單頁顯示「已退車」；
有效售出、台數、淨利、車行傭金、車行掛帳與報表都依既有的例外結案排除。
- 客戶應退＝帳本已確認淨實收－沒收（沒收須填原因），寫負向退款帳本列，不實際動帳。
  Excel 匯入單（帳上多半沒有付款紀錄）可改為手填應退（原因必填、不再沒收），
  上限＝Excel 收款價、Excel 現金＋刷卡、帳本淨實收三者取大；同樣寫負向退款列並記下手填。
- 分期公司已撥款也可以退車，但要先登記分期公司沖回金額：寫負向分期帳本列（不超過帳本淨撥款），
  實際撥款歸零並鎖定，原值留在異動紀錄。
- 有汰舊／政府補助要勾「補助已撤回或另行處理」；台數獎金已結算的比照刪單，自動扣掉本單分配。
- 車輛：配車中的車（或匯入單依識別號碼對到、已售出／已交車的庫存車）改可銷售，保留車牌、必填再售價；
  匯入單的車不在庫存時只記錄，不新建庫存車。
- 訂購單等已簽署文件不動，指紋留在紀錄裡；不要求重簽。
"""
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from sales.access.services import is_root
from sales.models import (
    DealerVolumeBonusAllocation, OrderChange, OrderEvent, OrderOperationsProfile, SalesOrder, VehicleInventory,
    VehicleInventoryHistory, normalize_vehicle_identifier,
)
from sales.services.audit_note import SUMMARY_PREFIX, note_or_summary, optional_note, with_note
from sales.services.inventory_history import STATUS_LABELS, status_change
from sales.services.inventory_restore import CONFIRM_FALLBACK as _RESTORE_FALLBACK, identifier_tail as vehicle_tail
from sales.services.order_deletion import _locked_order, _sync_settlements, is_order_delivered

Status = SalesOrder.Status
EVENT_TYPE = "returned_after_delivery"
CONFIRM_FALLBACK = "確認退車"
REASON_LIMIT = 500
RETURNABLE_VEHICLE_STATUSES = (VehicleInventory.Status.DELIVERED, VehicleInventory.Status.SOLD)
ZERO = Decimal("0")


def _money(value):
    return f"{(value or ZERO):,.0f}"


def _parse_amount(value, *, allow_zero=True):
    if value in (None, ""):
        return ZERO if allow_zero else None
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None
    if amount != amount.to_integral_value() or amount < 0 or (not allow_zero and amount == 0):
        return None
    return amount


def legacy_snapshot(order):
    return getattr(order, "legacy_snapshot", None) if order.pk else None


def manual_refund_cap(order, ledger):
    """匯入單手填應退的上限；系統建立的單回傳 None（不能手填）。"""
    snapshot = legacy_snapshot(order)
    if snapshot is None:
        return None
    excel_paid = (snapshot.cash_received or ZERO) + (snapshot.card_received or ZERO)
    return max(snapshot.historical_received_price or ZERO, excel_paid, ledger["customer"]["net"], ZERO)


def legacy_identifier(order):
    snapshot = legacy_snapshot(order)
    return (snapshot.vehicle_identifier if snapshot else "") or ""


def return_vehicle(order):
    """退車要放回庫存的車：配車中的車；匯入單沒連結時，用識別號碼找唯一一台已售出／已交車、沒掛其他訂單的車。"""
    if order.allocated_vehicle_id:
        return order.allocated_vehicle
    key = normalize_vehicle_identifier(legacy_identifier(order))
    if not key:
        return None
    from django.db.models import Q
    candidates = list(VehicleInventory.objects.filter(
        Q(normalized_engine_number=key) | Q(normalized_frame_number=key), status__in=RETURNABLE_VEHICLE_STATUSES,
    ).exclude(pk__in=SalesOrder.objects.exclude(pk=order.pk).filter(allocated_vehicle__isnull=False)
              .values("allocated_vehicle_id"))[:2])
    return candidates[0] if len(candidates) == 1 else None


def confirm_tail(order, vehicle=None):
    """二次確認要輸入的末 4 碼：優先用庫存車的引擎／車身號碼，其次是匯入時的車輛識別。"""
    if vehicle is not None:
        tail = vehicle_tail(vehicle)
        if tail != _RESTORE_FALLBACK:
            return tail
    tail = re.sub(r"[^0-9A-Za-z]", "", legacy_identifier(order))[-4:].upper()
    return tail or CONFIRM_FALLBACK


def tail_matches(order, vehicle, value):
    typed = re.sub(r"\s", "", value or "").upper()
    return bool(typed) and typed == confirm_tail(order, vehicle)


def has_subsidy(order):
    return bool(order.is_trade_in_subsidy or order.subsidy_items.exists())


def lender_disbursed(order, ledger, profile):
    """分期公司已撥款：帳本分期淨撥款，或營運收支的實際撥款（統一撥款對帳、匯入單）。"""
    if order.payment_type != SalesOrder.PaymentType.INSTALLMENT:
        return ZERO
    return max(ledger["lender"]["net"], (profile.actual_disbursement if profile else ZERO) or ZERO, ZERO)


def return_blockers(order, ledger=None):
    """回傳 [(說明, 連結, 連結文字)]；有任何一項就不能退車。"""
    from .payment_ledger import ledger_totals

    if order.deleted_at:
        return [("這張訂單已刪除。", "", "")]
    if order.status in {Status.CANCELLED, Status.CANCEL_REFUND_PENDING, Status.EXCEPTION_CLOSED}:
        return [(f"這張訂單目前是「{order.display_status}」，已經不是有效售出。", "", "")]
    if not is_order_delivered(order) or order.status not in {Status.COMPLETED, Status.DELIVERED_DOCS_PENDING}:
        return [("還沒交車的訂單請用一般取消，或已領牌時用「領牌後棄單（例外結案）」。",
                 reverse("order_detail", args=[order.pk]), "開啟訂單")]
    blockers = []
    if order.deletion_requested_at:
        blockers.append(("這張訂單有刪除申請還沒處理，請先在刪除審核駁回或處理。", reverse("order_deletion_queue"), "刪除審核"))
    ledger = ledger or ledger_totals(order)
    if ledger["customer"]["unconfirmed"] or ledger["lender"]["unconfirmed"]:
        blockers.append(("還有已登記但未確認的收款，請先在收款明細確認或刪除。",
                         reverse("order_detail", args=[order.pk]) + "?tab=finance", "開啟收款明細"))
    if ledger["customer"]["net"] < 0:
        blockers.append(("客戶帳本的淨實收是負數，請先更正收款紀錄。", reverse("order_detail", args=[order.pk]) + "?tab=finance", "開啟收款明細"))
    vehicle = return_vehicle(order)
    if vehicle is not None and not order.final_plate_number:
        blockers.append(("訂單沒有車牌號碼，車輛無法以已領牌車回到庫存；請先補登車牌。", reverse("order_detail", args=[order.pk]), "開啟訂單"))
    if vehicle is not None and vehicle.status not in RETURNABLE_VEHICLE_STATUSES:
        blockers.append((f"車輛 {vehicle.identifier} 目前是「{vehicle.get_status_display()}」，不是已交車或已售出；請先到車輛資料頁核對。",
                         reverse("inventory_edit", args=[vehicle.pk]), "開啟車輛資料"))
    return blockers


def return_impacts(order, *, ledger, profile, vehicle):
    received = ledger["customer"]["net"]
    impacts = [
        "訂單改為「已退車」（例外結案），不再列入有效售出、銷售台數、淨利、報表與戰情；列表移到「已取消」頁籤。",
        f"客戶已確認淨實收 {_money(received)} 元：應退＝淨實收－沒收，寫一筆負向退款紀錄（只做紀錄，不實際動帳）。",
    ]
    cap = manual_refund_cap(order, ledger)
    if cap is not None:
        impacts.append(f"這是 Excel 匯入的單，也可以手填應退金額（最多 {_money(cap)} 元，原因必填），一樣寫一筆負向退款紀錄。")
    disbursed = lender_disbursed(order, ledger, profile)
    if disbursed:
        impacts.append(f"分期公司已撥款 {_money(disbursed)} 元：要登記分期公司沖回金額；實際撥款歸零，原值留在異動紀錄。")
    if profile and profile.dealer_commission_expense:
        month = order.registration_date.strftime("%Y-%m") if order.registration_date else "領牌月份"
        impacts.append(f"車行傭金 {_money(profile.dealer_commission_expense)} 元原本列在 {month} 的車行結算，退車後該月結算少這張；"
                       "如果已付給車行，請向車行追回（系統不另開追回單）。")
    if order.source_type == SalesOrder.SourceType.DEALER and order.cash_receivable_v2:
        impacts.append("車行單的客戶應收尾款不再列入車行掛帳。")
    allocations = order.dealer_volume_bonus_allocations.count()
    if allocations:
        impacts.append(f"已結算的台數獎金會自動扣掉本單 {allocations} 筆分配，並寫入結算調整紀錄。")
    if vehicle is not None:
        impacts.append(f"車輛 {vehicle.identifier}（{vehicle.get_status_display()}）改為可銷售，保留車牌 {order.final_plate_number}，"
                       "以已領牌車重新定價，之後只能配給「領牌車」交易。")
    else:
        impacts.append("這張單的車不在庫存裡（或對不到唯一一台），只記錄退車，不新建庫存車。")
    if order.signed_contract or order.has_privacy_consent:
        impacts.append("已簽署的訂購單與個資同意書保留原檔，內容指紋記在退車紀錄，不要求重簽。")
    if order.closed_at:
        impacts.append("撤回原本的「確認結案」，原結案人員與時間留在紀錄。")
    return impacts


def return_summary(order, user):
    """訂單頁的入口；不是 admin 或不適用時回傳 None。"""
    if not is_root(user) or order.status not in {Status.COMPLETED, Status.DELIVERED_DOCS_PENDING}:
        return None
    return {"url": reverse("order_return", args=[order.pk])}


def _record_vehicle(vehicle, order, *, actor_name, reason, price):
    before = {"status": vehicle.status, "plate": vehicle.registered_plate_number, "resale_price": vehicle.resale_price}
    vehicle.status = VehicleInventory.Status.AVAILABLE
    vehicle.registered_plate_number = order.final_plate_number
    vehicle.registered_on = order.registration_date
    vehicle.resale_price = price
    vehicle.disposition, vehicle.disposition_dealer, vehicle.disposition_dealer_name, vehicle.disposition_on = "", None, "", None
    vehicle.save(update_fields=["status", "registered_plate_number", "registered_on", "resale_price", "disposition",
                                "disposition_dealer", "disposition_dealer_name", "disposition_on", "updated_at"])
    VehicleInventoryHistory.objects.create(
        vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED, actor_name=actor_name,
        reason=f"訂單 {order.number} 交車後退車，以已領牌車回到庫存（原為{STATUS_LABELS.get(before['status'], before['status'])}）" + (f"：{reason}" if reason else ""),
        changes={
            "status": status_change(before["status"], vehicle.status),
            "order": {"label": "訂單", "value": order.number},
            "registered_plate_number": {"label": "已領牌車牌", "before": before["plate"] or "未設定", "after": vehicle.registered_plate_number},
            "resale_price": {"label": "領牌車再售價",
                             "before": _money(before["resale_price"]) if before["resale_price"] is not None else "未設定",
                             "after": _money(vehicle.resale_price)},
        },
        status_snapshot=vehicle.status, location_store_snapshot=vehicle.location_store,
        location_label_snapshot=vehicle.actual_location_label, condition_note_snapshot=vehicle.condition_note,
        condition_resolution_snapshot=vehicle.condition_resolution,
    )


@transaction.atomic
def return_after_delivery(*, user, order_id, reason, expected_updated_at, refunded_on, actor_name="",
                          forfeited_amount=None, forfeit_reason="", method="", reference="",
                          lender_clawback=None, lender_reference="", resale_price=None,
                          subsidy_handled=False, confirm_identifier="", manual_refund=None, manual_refund_reason=""):
    from .notifications import notify
    from .payment_ledger import create_refund_entry, ledger_totals

    if not is_root(user):
        raise PermissionDenied("只有 admin 可以辦理交車後退車。")
    try:
        order, settlements = _locked_order(order_id)
    except SalesOrder.DoesNotExist as exc:
        raise ValidationError("找不到這張訂單，請重新整理。") from exc
    if expected_updated_at != order.updated_at.isoformat():
        raise ValidationError("訂單已被更新，請重新載入後再確認。")
    # 退車、沒收、手填應退的備註都選填（使用者 2026-10-21 T-39），空白時由系統描述代替。
    reason = optional_note(reason, REASON_LIMIT)
    list(order.payment_records.select_for_update().order_by("pk"))
    ledger = ledger_totals(order)
    blockers = return_blockers(order, ledger)
    if blockers:
        raise ValidationError([text for text, _url, _label in blockers])
    vehicle = return_vehicle(order)
    if vehicle is not None:
        vehicle = VehicleInventory.objects.select_for_update(of=("self",)).get(pk=vehicle.pk)
    if not tail_matches(order, vehicle, confirm_identifier):
        raise ValidationError("請輸入引擎／車身號碼末 4 碼確認；輸入的號碼不符。")
    if has_subsidy(order) and not subsidy_handled:
        raise ValidationError("這張單有汰舊／政府補助，請確認補助已撤回或另行處理後勾選。")

    received = ledger["customer"]["net"]
    forfeited = _parse_amount(forfeited_amount)
    if forfeited is None or forfeited > received:
        raise ValidationError(f"沒收金額須介於 0 至客戶已確認淨實收 {_money(received)} 元之間。")
    forfeit_reason = (forfeit_reason or "").strip()
    if forfeited and not forfeit_reason:
        forfeit_reason = f"{SUMMARY_PREFIX}交車後退車沒收 {_money(forfeited)} 元"
    refund = received - forfeited
    manual_note = ""
    if manual_refund not in (None, ""):
        cap = manual_refund_cap(order, ledger)
        if cap is None:
            raise ValidationError("只有 Excel 匯入的訂單可以手填應退金額；系統建立的訂單依帳本計算。")
        manual = _parse_amount(manual_refund, allow_zero=False)
        if manual is None or manual > cap:
            raise ValidationError(f"手填應退金額須為 1～{_money(cap)} 元的整數（不超過 Excel 歷史收款與帳本淨實收的較大者）。")
        manual_refund_reason = (manual_refund_reason or "").strip()[:200]
        if forfeited:
            raise ValidationError("手填應退金額時不另計沒收，請把沒收金額留空。")
        refund = manual
        manual_note = with_note(f"手填應退 {_money(manual)} 元（帳本計算 {_money(received)} 元）",
                                manual_refund_reason and f"備註：{manual_refund_reason}", "，")
    if refund > 0 and not method:
        raise ValidationError("有應退金額時，請選擇退款方式。")
    if not refunded_on:
        raise ValidationError("請填寫退款／沖回日期。")

    profile = OrderOperationsProfile.objects.select_for_update().filter(order=order).first()
    disbursed = lender_disbursed(order, ledger, profile)
    clawback = ZERO
    if disbursed:
        clawback = _parse_amount(lender_clawback, allow_zero=False)
        if clawback is None or clawback > disbursed:
            raise ValidationError(f"分期公司已撥款 {_money(disbursed)} 元，請登記分期公司沖回金額（1～{_money(disbursed)} 元）。")
    price = None
    if vehicle is not None:
        price = _parse_amount(resale_price, allow_zero=False)
        if price is None:
            raise ValidationError("請填寫領牌車再售價（大於 0 的整數）。")

    actor_name = actor_name or user.get_username()
    method_label = dict(SalesOrder.PaymentMethod.choices).get(method, method or "")
    if refund > 0:
        create_refund_entry(
            order, kind="customer", amount=refund, actor_name=actor_name,
            reason=(f"交車後退車退款（{manual_note}）" if manual_note else
                    f"交車後退車退款（已收 {_money(received)}、沒收 {_money(forfeited)}）")[:250],
            method_label=method_label, refunded_on=refunded_on, reference=reference, item_name="退車退款",
        )
    lender_entry = min(clawback, max(ledger["lender"]["net"], ZERO))
    if lender_entry > 0:
        create_refund_entry(
            order, kind="lender", amount=lender_entry, actor_name=actor_name,
            reason=f"交車後退車，分期公司沖回撥款 {_money(clawback)} 元",
            method_label="", refunded_on=refunded_on, reference=lender_reference, item_name="分期撥款沖回",
        )
    finance_changes = {}
    if profile is not None and disbursed:
        previous = profile.actual_disbursement or ZERO
        profile.actual_disbursement = ZERO
        profile.payment_disbursement_snapshot = {}
        profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) | {"actual_disbursement"})
        profile.save(update_fields=["actual_disbursement", "payment_disbursement_snapshot", "manual_financial_fields", "updated_at"])
        finance_changes["實際撥款"] = {"before": _money(previous), "after": "0"}
        finance_changes["分期公司沖回"] = {"before": "", "after": f"{_money(clawback)}（帳本沖回 {_money(lender_entry)}）"}

    snapshot = {
        "net_profit": _money(profile.net_profit) if profile else "",
        "dealer_commission_expense": _money(profile.dealer_commission_expense) if profile else "0",
        "closed_at": order.closed_at.isoformat() if order.closed_at else "",
        "closed_by": order.closed_by,
        "status": order.status,
        "signed_contract": f"{order.get_signed_contract_method_display() or '未簽署'} {order.signed_contract_fingerprint}".strip()
        if order.signed_contract else "未上傳",
    }
    allocation_ids = list(order.dealer_volume_bonus_allocations.values_list("pk", flat=True))
    now = timezone.now()
    if allocation_ids:
        DealerVolumeBonusAllocation.all_objects.filter(pk__in=allocation_ids).update(voided_at=now)
        _sync_settlements(settlements, user, with_note(f"訂單 {order.number} 交車後退車", reason, "："))
    if vehicle is not None:
        _record_vehicle(vehicle, order, actor_name=actor_name, reason=reason, price=price)

    before_label = order.display_status
    order.ensure_transition(Status.EXCEPTION_CLOSED)
    order.allocated_vehicle = None
    order.exception_vehicle = vehicle
    order.exception_reason = with_note("交車後退車", reason, "：")[:250]
    order.exception_closed_at = now
    order.exception_closed_by = actor_name
    order.refund_amount = refund
    order.forfeited_amount = forfeited
    order.forfeit_reason = forfeit_reason[:250]
    order.refund_completed_on = refunded_on
    order.refund_method = method if refund > 0 else ""
    order.refund_reference = (reference or "")[:250] if refund > 0 else ""
    order.closed_at, order.closed_by = None, ""
    order.status = Status.EXCEPTION_CLOSED
    order.save(update_fields=[
        "allocated_vehicle", "exception_vehicle", "exception_reason", "exception_closed_at", "exception_closed_by",
        "refund_amount", "forfeited_amount", "forfeit_reason", "refund_completed_on", "refund_method",
        "refund_reference", "closed_at", "closed_by", "status", "updated_at",
    ])
    summary = (f"手填應退 {_money(refund)}（帳本淨實收 {_money(received)}）" if manual_note else
               f"已收 {_money(received)}、沒收 {_money(forfeited)}、退款 {_money(refund)}")
    if disbursed:
        summary += f"、分期公司沖回 {_money(clawback)}"
    vehicle_text = (f"車輛 {vehicle.identifier}（{order.final_plate_number}）以已領牌車回到庫存，再售價 {_money(price)} 元"
                    if vehicle is not None else "車輛不在庫存，只記錄")
    OrderChange.objects.create(order=order, reason=note_or_summary(reason, f"交車後退車；{summary}"), actor_name=actor_name, changes={
        "訂單狀態": {"before": before_label, "after": "已退車（例外結案）"},
        "結算": {"before": "", "after": summary},
        **({"應退金額（手填）": {"before": f"帳本計算 {_money(received)}", "after": with_note(_money(refund), manual_refund_reason)}}
           if manual_note else {}),
        **finance_changes,
        **({"確認結案": {"before": f"{snapshot['closed_by']} {snapshot['closed_at']}".strip(), "after": "撤回"}}
           if snapshot["closed_at"] else {}),
        **({"台數獎金": {"before": f"{len(allocation_ids)} 筆分配", "after": "已扣除"}} if allocation_ids else {}),
    })
    OrderEvent.objects.create(order=order, event_type=EVENT_TYPE, actor_name=actor_name, description=(
        f"{with_note('交車後退車', reason, '：')}；{summary}；{vehicle_text}。"
        f"\n退車前：淨利 {snapshot['net_profit'] or '未計算'}、車行傭金 {snapshot['dealer_commission_expense']}、"
        f"訂購單 {snapshot['signed_contract']}"
        + ("；補助已確認撤回或另行處理" if has_subsidy(order) else "")
        + (f"\n{manual_note}" if manual_note else "")
    ))
    notify("exception_closed", order, f"訂單 {order.number} 已辦理交車後退車", f"{reason or '交車後退車'}；{summary}。")
    return order
