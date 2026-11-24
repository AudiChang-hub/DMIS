"""調出（調車）：把本店庫存的車調給別家店，離開本店庫存（T-310，使用者 2026-11-24）。

庫存列表勾車 → 填「調給哪一家」→ 確認，一步完成：不簽名、不勾聲明、不產生 PDF、沒有預備調車。
調出後車輛改為「已調出」（不算庫存也不算售出，保留進車紀錄），並留一筆調車紀錄（單號 TS 不變）。
放到本店其他門市不是調出，請改列表上的「實際位置」（T-308），車仍是庫存；所以不能調給本店。
作廢保留紀錄，仍為已調出的車改回調出前狀態。

2026-11-24 以前的紀錄有領車人簽名與簽收單 PDF（已存檔），明細照常顯示與下載。
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from sales.models import (
    PrintCompany,
    SalesSource,
    VehicleInventory,
    VehicleTransferSignoff,
    record_vehicle_history,
)
from sales.services.audit_note import note_or_summary, with_note
from sales.services.home_stores import home_store_labels
from sales.services.inventory_location_note import FACTORY_LABEL, FACTORY_WORDS

ELIGIBLE_STATUSES = (
    VehicleInventory.Status.AVAILABLE,
    VehicleInventory.Status.CONDITION_ISSUE,
)
# 舊紀錄（有簽名）的點交聲明；新流程不勾聲明，只在舊紀錄明細顯示。
STATEMENT = "上列車輛已由領車人於本店當面點交，車況、車身與引擎號碼確認無誤後領走。"
FACTORY_OPTION = f"{FACTORY_LABEL}（調回）"
NAME_MAX = 120
NOTE_MAX = 200
HOME_STORE_HINT = "放到本店其他門市請直接改列表上的「實際位置」，車仍是本店庫存。"


def eligible_vehicles():
    """可調出的車：可銷售或車況異常；已預留（已配給訂單）的車不能調走。"""
    return (
        VehicleInventory.objects.filter(status__in=ELIGIBLE_STATUSES)
        .select_related("vehicle_model", "color", "current_dealer")
        .order_by("vehicle_model__name", "color__name", "received_on", "id")
    )


def selected_vehicles(vehicle_ids, *, lock=False):
    ids = sorted({int(value) for value in vehicle_ids if str(value).isdigit()})
    if not ids:
        raise ValidationError("請至少選擇一台要調出的車。")
    queryset = VehicleInventory.objects.select_related("vehicle_model", "color", "current_dealer")
    if lock:
        # 車行、門市可為空（LEFT JOIN），PostgreSQL 不允許鎖外部連接的一側，只鎖車輛本身。
        queryset = queryset.select_for_update(of=("self",))
    vehicles = list(queryset.filter(pk__in=ids).order_by("id"))
    if len(vehicles) != len(ids):
        raise ValidationError("部分車輛已不存在，請重新整理後再選。")
    blocked = [v.identifier for v in vehicles if v.status not in ELIGIBLE_STATUSES]
    if blocked:
        raise ValidationError(
            f"{'、'.join(blocked)} 目前不是可銷售或車況異常（可能剛被配車、售出或調出），不能調出；"
            "這次都沒有調出，請重新整理後再選。"
        )
    return vehicles


def vehicle_snapshot(vehicles):
    return [
        {
            "id": vehicle.pk,
            "model": vehicle.vehicle_model.name,
            "model_number": vehicle.vehicle_model.model_number or "",
            "color": vehicle.color.label,
            "engine_number": vehicle.engine_number or "",
            "frame_number": vehicle.frame_number or "",
            "location": vehicle.actual_location_label,
            "status": vehicle.status,
        }
        for vehicle in vehicles
    ]


def home_company():
    company = PrintCompany.objects.filter(key="home").first()
    if not company:
        return {}
    return {key: getattr(company, key) for key in ("legal_name", "tax_id", "address", "phone")}


def _active_dealers():
    return SalesSource.objects.filter(active=True, source_type=SalesSource.SourceType.DEALER)


def _compact(name):
    return "".join((name or "").split())


def is_home_store(name):
    """本店（馭盛、永湛）：打「馭盛」「本店」「本店：永湛」都算。"""
    compact = _compact(name)
    if compact.startswith("本店"):
        compact = compact[2:].lstrip("：:")
        if not compact:
            return True
    return compact in home_store_labels()


def resolve_destination(raw_name):
    """自由輸入的店名 → (存檔名稱, 車行主檔或 None)。

    和啟用中車行名稱完全相同（去頭尾空白）才連主檔，否則只存原文，和「主檔沒有的車行」一樣。
    原廠、總公司等統一記為「原廠／總公司」。本店不能調出（要改實際位置）。
    """
    name = " ".join((raw_name or "").split())[:NAME_MAX]
    if not name:
        raise ValidationError("請填寫要調給哪一家。")
    if is_home_store(name):
        raise ValidationError(f"「{name}」是本店，不能調出。{HOME_STORE_HINT}")
    if name in FACTORY_WORDS or name == FACTORY_OPTION:
        return FACTORY_LABEL, None
    dealer = _active_dealers().filter(name=name).order_by("id").first()
    return name, dealer


def _short_date(value, today):
    if not value:
        return ""
    return f"{value:%m/%d}" if value.year == today.year else f"{value:%Y/%m/%d}"


def name_suggestions():
    """調出小視窗的店名建議：打過的店名（調車紀錄＋車輛去向原文，最近用過的在前）與啟用中車行。

    不含本店；「原廠／總公司」由畫面固定放在最上面。正式站約兩百個短字串，整頁只輸出一份。
    """
    today = timezone.localdate()
    used = {}

    def remember(name, when, count):
        name = " ".join((name or "").split())
        if not name or name == FACTORY_LABEL or is_home_store(name):
            return
        entry = used.setdefault(name, {"name": name, "last": None, "count": 0})
        if when and (entry["last"] is None or when > entry["last"]):
            entry["last"] = when
        entry["count"] += count

    rows = (
        VehicleInventory.objects.exclude(disposition_dealer_name="").order_by()
        .values("disposition_dealer_name").annotate(last=Max("disposition_on"), total=Count("id"))
    )
    for row in rows:
        remember(row["disposition_dealer_name"], row["last"], row["total"])
    signed = (
        VehicleTransferSignoff.objects.filter(status=VehicleTransferSignoff.Status.SIGNED).order_by()
        .values("dealer_name").annotate(last=Max("signed_at"))
    )
    for row in signed:
        remember(row["dealer_name"], timezone.localdate(row["last"]) if row["last"] else None, 0)

    ordered = sorted(
        used.values(),
        key=lambda item: (item["last"] is None, -(item["last"].toordinal() if item["last"] else 0), item["name"]),
    )
    used_names = {item["name"] for item in ordered}
    dealers = [
        name for name in _active_dealers().order_by("name").values_list("name", flat=True).distinct()
        if name not in used_names and not is_home_store(name)
    ]
    return {
        "factory": FACTORY_OPTION,
        "used": [
            {
                "name": item["name"],
                "meta": "・".join(part for part in (
                    _short_date(item["last"], today), f"{item['count']} 台" if item["count"] else "",
                ) if part),
            }
            for item in ordered
        ],
        "dealers": dealers,
        "home": home_store_labels(),
    }


@transaction.atomic
def transfer_out(*, vehicle_ids, name, note, user):
    """調出：一個交易內鎖車、重新檢查狀態（期間被配走就整批不調），車改已調出並留一筆調車紀錄。"""
    dealer_name, dealer = resolve_destination(name)
    note = " ".join((note or "").split())[:NOTE_MAX]
    vehicles = selected_vehicles(vehicle_ids, lock=True)
    staff_name = (user.get_full_name() or user.get_username())[:60]
    signoff = VehicleTransferSignoff.objects.create(
        status=VehicleTransferSignoff.Status.SIGNED, dealer=dealer, dealer_name=dealer_name,
        vehicles_snapshot=vehicle_snapshot(vehicles), company_snapshot=home_company(), note=note,
        signed_at=timezone.now(), staff=user, staff_name=staff_name,
    )
    signoff.vehicles.set(vehicles)

    today = timezone.localdate()
    reason = with_note(f"調出 {signoff.number}：調給 {dealer_name}", note, "，")
    for vehicle in vehicles:
        before_status = vehicle.status
        vehicle.status = VehicleInventory.Status.TRANSFERRED_OUT
        vehicle.disposition = VehicleInventory.Disposition.TRANSFER_OUT
        vehicle.disposition_dealer = dealer
        vehicle.disposition_dealer_name = dealer_name
        vehicle.disposition_on = today
        vehicle.save(update_fields=[
            "status", "disposition", "disposition_dealer", "disposition_dealer_name",
            "disposition_on", "updated_at",
        ])
        record_vehicle_history(vehicle, actor_name=staff_name, reason=reason, before_status=before_status)
    return signoff


@transaction.atomic
def void_signoff(signoff, *, actor_name, reason):
    """作廢保留簽收紀錄；只把仍為已調出、且最後一次調出就是這張簽收單的車改回簽署前狀態。"""
    # 作廢備註選填（使用者 2026-10-21 T-39）。
    note = (reason or "").strip()[:300]
    signoff = VehicleTransferSignoff.objects.select_for_update().get(pk=signoff.pk)
    if signoff.is_voided:
        raise ValidationError("這張簽收單已經作廢。")
    if signoff.is_pending:
        raise ValidationError("預備調車尚未簽收，請改用取消預備。")
    previous = {item["id"]: item.get("status") for item in signoff.vehicles_snapshot}
    restored, kept = [], []
    vehicles = VehicleInventory.objects.select_for_update(of=("self",)).filter(
        pk__in=signoff.vehicles.values("pk")
    ).order_by("id")
    for vehicle in vehicles:
        latest = vehicle.transfer_signoffs.filter(
            voided_at__isnull=True, status=VehicleTransferSignoff.Status.SIGNED,
        ).order_by("-signed_at", "-id").first()
        if vehicle.status != VehicleInventory.Status.TRANSFERRED_OUT or latest != signoff:
            kept.append(vehicle.identifier)
            continue
        before_status = vehicle.status
        vehicle.status = previous.get(vehicle.pk) or VehicleInventory.Status.AVAILABLE
        if vehicle.status not in ELIGIBLE_STATUSES:
            vehicle.status = VehicleInventory.Status.AVAILABLE
        vehicle.disposition = ""
        vehicle.disposition_dealer = None
        vehicle.disposition_dealer_name = ""
        vehicle.disposition_on = None
        vehicle.save(update_fields=[
            "status", "disposition", "disposition_dealer", "disposition_dealer_name",
            "disposition_on", "updated_at",
        ])
        record_vehicle_history(
            vehicle, actor_name=actor_name,
            reason=with_note(f"作廢調車簽收 {signoff.number}", note, "："), before_status=before_status,
        )
        restored.append(vehicle.identifier)
    signoff.voided_at = timezone.now()
    signoff.voided_by = actor_name[:150]
    signoff.void_reason = note_or_summary(note, f"作廢調車簽收 {signoff.number}", 300)
    signoff.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    return restored, kept
