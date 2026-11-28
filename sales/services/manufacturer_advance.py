"""原廠代墊／代轉（T-334 第一版）：訂單頁、追蹤頁、營運總表側邊明細共用這裡的讀寫，三處看到的是同一份資料。

- 只讀寫 ManufacturerAdvance／ManufacturerAdvancePayout：不碰收支欄位、淨利、應收、傭金、原廠獎勵，也不擋交車。
- 每次寫入都在交易裡鎖住那幾筆，並記一筆訂單事件（稽核）；勾選帶「畫面上看到的狀態」，
  跟資料庫不同（別處剛勾過）就不寫，回傳最新狀態讓畫面更新。
- 等待天數：「等原廠撥款」從實際領牌日起算，還沒領牌從建立日起算；「等交給對象」從建立日起算。超過 7 天提醒。
"""
from collections import OrderedDict
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from sales.models import ManufacturerAdvance, ManufacturerAdvancePayout, OrderEvent, SalesOrder, VehicleBrand

ALERT_DAYS = 7
EVENT_TYPE = "manufacturer_advance"
TABS = OrderedDict((("reimburse", "等原廠撥款"), ("handover", "等交給對象")))
FLAGS = {"reimbursed": "原廠已撥", "handed_over": "已交給對象"}
ZERO = Decimal("0")


class Conflict(Exception):
    """畫面上的狀態跟資料庫不同（別處剛改過）；帶最新的項目讓畫面更新。"""

    def __init__(self, message, items=()):
        super().__init__(message)
        self.message = message
        self.items = list(items)


def actor_name(user):
    return user.get_full_name() or user.get_username()


# ── 查詢 ──────────────────────────────────────────────────────────────


def visible_items(user):
    """這個帳號看得到的訂單上、沒刪除的項目（訂單範圍同全部訂單）。"""
    from sales.services.order_intake import scoped_orders

    return ManufacturerAdvance.objects.filter(
        voided_at__isnull=True, order__in=scoped_orders(user, SalesOrder.objects.all()),
    ).select_related("order", "order__vehicle_model", "order__source", "payout")


def order_items(order):
    return list(order.manufacturer_advances.filter(voided_at__isnull=True).select_related("payout"))


def waiting_since(item, tab):
    if tab == "reimburse" and item.order.registration_date:
        return item.order.registration_date
    return timezone.localtime(item.created_at).date()


def waiting_days(item, tab, today=None):
    today = today or timezone.localdate()
    return max((today - waiting_since(item, tab)).days, 0)


def pending(queryset, tab):
    return queryset.filter(reimbursed_at__isnull=True) if tab == "reimburse" else queryset.filter(handed_over_at__isnull=True)


def manufacturers_in(queryset):
    return sorted({name for name in queryset.values_list("manufacturer", flat=True) if name})


def tracking_rows(user, tab, manufacturer="", today=None):
    today = today or timezone.localdate()
    queryset = pending(visible_items(user), tab)
    if manufacturer:
        queryset = queryset.filter(manufacturer=manufacturer)
    rows = []
    for item in queryset:
        item.waiting_days = waiting_days(item, tab, today)
        item.is_overdue = item.waiting_days > ALERT_DAYS
        item.recipient_text = recipient_label(item)
        rows.append(item)
    # 等最久的在最上面，同天數依訂單號。
    rows.sort(key=lambda item: (-item.waiting_days, item.order.number, item.pk))
    return rows


def tab_counts(user, manufacturer=""):
    queryset = visible_items(user)
    if manufacturer:
        queryset = queryset.filter(manufacturer=manufacturer)
    return {tab: pending(queryset, tab).count() for tab in TABS}


def summary(user, today=None):
    """營運總表卡片：一律是「目前未結」，不跟期間篩選走。"""
    today = today or timezone.localdate()
    items = list(visible_items(user).filter(Q(reimbursed_at__isnull=True) | Q(handed_over_at__isnull=True)))
    reimburse = OrderedDict()
    reimburse_oldest = None
    handover = {"cash_count": 0, "cash_amount": ZERO, "gift_count": 0, "gift_quantity": 0}
    handover_oldest = None
    for item in items:
        if not item.reimbursed:
            row = reimburse.setdefault(item.manufacturer, {"manufacturer": item.manufacturer, "count": 0, "amount": ZERO, "gift_quantity": 0})
            row["count"] += 1
            if item.is_cash:
                row["amount"] += item.amount
            else:
                row["gift_quantity"] += item.gift_quantity
            days = waiting_days(item, "reimburse", today)
            reimburse_oldest = days if reimburse_oldest is None else max(reimburse_oldest, days)
        if not item.handed_over:
            if item.is_cash:
                handover["cash_count"] += 1
                handover["cash_amount"] += item.amount
            else:
                handover["gift_count"] += 1
                handover["gift_quantity"] += item.gift_quantity
            days = waiting_days(item, "handover", today)
            handover_oldest = days if handover_oldest is None else max(handover_oldest, days)
    reimburse_rows = sorted(reimburse.values(), key=lambda row: row["manufacturer"])
    return {
        "reimburse": {
            "rows": reimburse_rows,
            "count": sum(row["count"] for row in reimburse_rows),
            "amount": sum((row["amount"] for row in reimburse_rows), ZERO),
            "oldest": reimburse_oldest,
            "alert": reimburse_oldest is not None and reimburse_oldest > ALERT_DAYS,
        },
        "handover": {
            **handover,
            "count": handover["cash_count"] + handover["gift_count"],
            "oldest": handover_oldest,
            "alert": handover_oldest is not None and handover_oldest > ALERT_DAYS,
        },
        "alert_days": ALERT_DAYS,
        "empty": not items,
    }


def campaign_suggestions(limit=30):
    """打過的活動名稱，最近用過的在前，給輸入框直接點選。"""
    rows = (ManufacturerAdvance.objects.exclude(campaign_name="").values("campaign_name")
            .annotate(latest=Max("created_at")).order_by("-latest")[:limit])
    return [row["campaign_name"] for row in rows]


def default_manufacturer(order):
    """訂單車型的品牌；品牌清單有同名（不分大小寫）就用清單的寫法，下拉才會選到。"""
    brand = ((order.vehicle_model.brand if order.vehicle_model_id else "") or "").strip()
    if not brand:
        return ""
    return VehicleBrand.objects.filter(active=True, name__iexact=brand).values_list("name", flat=True).first() or brand


def manufacturer_choices(order):
    """原廠下拉（T-347）：和車型主檔、活動設定同一份品牌清單；訂單車型的品牌不在清單裡也列出來。"""
    from sales.forms import _brand_choices

    return _brand_choices(default_manufacturer(order))[1:]


def dealer_available(order):
    return order.source_type == SalesOrder.SourceType.DEALER and bool(order.source_id)


def recipient_label(item):
    order = item.order
    if item.recipient == ManufacturerAdvance.Recipient.DEALER:
        return f"車行 {order.source.name}" if order.source_id else "車行"
    return f"客人 {order.owner_name}" if order.owner_name else "客人"


def flag_label(item, flag):
    return getattr(item, f"{flag}_label")


def item_state(item):
    """畫面用的狀態（JSON）：三處都依這份更新。"""
    return {
        "id": item.pk,
        "reimbursed": item.reimbursed,
        "reimbursed_label": flag_label(item, "reimbursed"),
        "payout": item.payout_id,
        "handed_over": item.handed_over,
        "handed_over_label": flag_label(item, "handed_over"),
        "settled": item.settled,
        "voided": item.voided_at is not None,
    }


# ── 寫入 ──────────────────────────────────────────────────────────────


class ManufacturerAdvanceForm(forms.ModelForm):
    class Meta:
        model = ManufacturerAdvance
        fields = ("manufacturer", "campaign_name", "recipient", "kind", "amount", "gift_name", "gift_quantity")

    def __init__(self, *args, order, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        self.fields["amount"].required = False
        self.fields["gift_quantity"].required = False
        if not dealer_available(order):
            self.fields["recipient"].choices = [(ManufacturerAdvance.Recipient.CUSTOMER, "客人")]
        self.fields["manufacturer"] = forms.ChoiceField(
            label="原廠", choices=manufacturer_choices(order),
            error_messages={"required": "請選原廠。", "invalid_choice": "請從清單選原廠。"})

    def clean_campaign_name(self):
        value = " ".join((self.cleaned_data.get("campaign_name") or "").split())
        if not value:
            raise ValidationError("請填活動名稱。")
        return value

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        if kind == ManufacturerAdvance.Kind.CASH:
            amount = cleaned.get("amount")
            if amount is None or amount <= 0:
                self.add_error("amount", "請填金額（大於 0）。")
            cleaned["gift_name"], cleaned["gift_quantity"] = "", 0
        elif kind == ManufacturerAdvance.Kind.GIFT:
            cleaned["gift_name"] = (cleaned.get("gift_name") or "").strip()
            if not cleaned["gift_name"]:
                self.add_error("gift_name", "請填贈品名稱。")
            if not cleaned.get("gift_quantity"):
                self.add_error("gift_quantity", "請填數量（至少 1）。")
            cleaned["amount"] = ZERO
        return cleaned


class PayoutForm(forms.Form):
    paid_on = forms.DateField(label="撥款日", error_messages={"required": "請填撥款日。", "invalid": "撥款日格式不對。"})
    amount = forms.DecimalField(label="實撥金額", min_value=0, max_digits=12, decimal_places=0,
                                error_messages={"required": "請填實撥金額。", "min_value": "實撥金額不能是負的。",
                                                "invalid": "實撥金額要是整數。", "max_decimal_places": "實撥金額要是整數。"})


def _event(order, description, user):
    OrderEvent.objects.create(order=order, event_type=EVENT_TYPE, description=description, actor_name=actor_name(user))


@transaction.atomic
def create_item(order, form, user):
    item = form.save(commit=False)
    item.order = order
    item.origin = ManufacturerAdvance.Origin.MANUAL
    item.created_by = user
    item.created_by_name = actor_name(user)
    item.save()
    _event(order, f"新增原廠代墊／代轉：{item.manufacturer}「{item.campaign_name}」給{item.get_recipient_display()} {item.content_label}", user)
    return item


def _locked(pk):
    # 撥款紀錄可為空（LEFT JOIN），PostgreSQL 不允許鎖外部連接的一側，只鎖項目本身。
    return (ManufacturerAdvance.objects.select_for_update(of=("self",))
            .select_related("order", "payout").get(pk=pk))


def _void_payout_if_empty(payout, user, now):
    if payout and payout.voided_at is None and not payout.items.filter(voided_at__isnull=True).exists():
        payout.voided_at, payout.voided_by = now, actor_name(user)
        payout.save(update_fields=["voided_at", "voided_by", "updated_at"])


@transaction.atomic
def set_flag(pk, flag, value, user, *, expected=None, undo=False):
    """勾或取消「原廠已撥」「已交給對象」。expected 是畫面上看到的狀態（"1"／"0"），跟資料庫不同就不寫。"""
    if flag not in FLAGS:
        raise ValidationError("不認得的勾選項目。")
    item = _locked(pk)
    if item.voided_at:
        raise Conflict("這筆已經刪除，請重新整理。", [item])
    current = getattr(item, flag)
    if expected is not None and expected != ("1" if current else "0"):
        raise Conflict(f"這筆的「{FLAGS[flag]}」剛被別人改過，已更新成最新狀態。", [item])
    if current == value:
        return item, False
    now = timezone.now()
    name = actor_name(user)
    fields = [f"{flag}_on", f"{flag}_by", f"{flag}_at", "updated_at"]
    if value:
        setattr(item, f"{flag}_on", timezone.localdate())
        setattr(item, f"{flag}_by", name)
        setattr(item, f"{flag}_at", now)
    else:
        setattr(item, f"{flag}_on", None)
        setattr(item, f"{flag}_by", "")
        setattr(item, f"{flag}_at", None)
    previous_payout = None
    if flag == "reimbursed" and not value and item.payout_id:
        previous_payout = item.payout
        item.payout = None
        fields.append("payout")
    item.save(update_fields=fields)
    _void_payout_if_empty(previous_payout, user, now)
    verb = "勾" if value else ("復原" if undo else "取消")
    _event(item.order, f"原廠代墊／代轉「{item.campaign_name}」{verb}「{FLAGS[flag]}」", user)
    return item, True


@transaction.atomic
def void_item(pk, user, *, restore=False):
    item = _locked(pk)
    if restore:
        if item.voided_at is None:
            return item
        item.voided_at, item.voided_by = None, ""
        item.save(update_fields=["voided_at", "voided_by", "updated_at"])
        _event(item.order, f"復原原廠代墊／代轉「{item.campaign_name}」", user)
        return item
    if item.voided_at:
        return item
    if item.reimbursed or item.handed_over:
        raise Conflict("已經勾過「原廠已撥」或「已交給對象」的項目不能刪除，請先取消勾選。", [item])
    item.voided_at, item.voided_by = timezone.now(), actor_name(user)
    item.save(update_fields=["voided_at", "voided_by", "updated_at"])
    _event(item.order, f"刪除原廠代墊／代轉「{item.campaign_name}」", user)
    return item


def payout_totals(items, amount):
    """登記撥款的「勾選合計／實撥／差額」：差額＝實撥－勾選項目的金額合計（贈品不算金額）。只顯示，不進收支。"""
    selected = sum((item.amount for item in items if item.is_cash), ZERO)
    actual = Decimal(amount or 0)
    return {"selected": selected, "actual": actual, "difference": actual - selected}


@transaction.atomic
def register_payout(user, item_ids, paid_on, amount, *, visible=None):
    """多選幾列一次標成原廠已撥，並建一筆撥款紀錄。全部同一家原廠、全部還沒標已撥，才寫入。"""
    ids = sorted({int(pk) for pk in item_ids})
    if not ids:
        raise ValidationError("請先勾選要登記的項目。")
    queryset = visible if visible is not None else ManufacturerAdvance.objects.all()
    if queryset.filter(pk__in=ids).count() != len(ids):
        raise ValidationError("有項目找不到或沒有權限，請重新整理後再選。")
    items = list(ManufacturerAdvance.objects.select_for_update(of=("self",)).select_related("order").filter(pk__in=ids).order_by("pk"))
    stale = [item for item in items if item.voided_at or item.reimbursed]
    if stale:
        numbers = "、".join(item.order.number for item in stale)
        raise Conflict(f"有 {len(stale)} 筆剛被標成已撥或刪除（{numbers}），已更新成最新狀態，請重新勾選。", stale)
    manufacturers = {item.manufacturer for item in items}
    if len(manufacturers) > 1:
        raise ValidationError(f"一次只能登記同一家原廠的撥款，目前勾了：{'、'.join(sorted(manufacturers))}。")
    name = actor_name(user)
    now = timezone.now()
    payout = ManufacturerAdvancePayout.objects.create(
        manufacturer=items[0].manufacturer, paid_on=paid_on, amount=amount, handled_by=name, created_by=user,
    )
    for item in items:
        item.reimbursed_on, item.reimbursed_by, item.reimbursed_at, item.payout = paid_on, name, now, payout
        item.save(update_fields=["reimbursed_on", "reimbursed_by", "reimbursed_at", "payout", "updated_at"])
        _event(item.order, f"原廠代墊／代轉「{item.campaign_name}」登記原廠撥款（{paid_on:%Y/%m/%d}，同批 {len(items)} 筆實撥 ${amount:,.0f}）", user)
    return payout, items


@transaction.atomic
def void_payout(pk, user):
    """復原整批撥款：清掉這批還掛著的項目的已撥，撥款紀錄標為已復原。"""
    payout = ManufacturerAdvancePayout.objects.select_for_update().get(pk=pk)
    items = list(ManufacturerAdvance.objects.select_for_update(of=("self",)).select_related("order").filter(payout=payout))
    if payout.voided_at:
        return payout, items
    for item in items:
        item.reimbursed_on, item.reimbursed_by, item.reimbursed_at, item.payout = None, "", None, None
        item.save(update_fields=["reimbursed_on", "reimbursed_by", "reimbursed_at", "payout", "updated_at"])
        _event(item.order, f"原廠代墊／代轉「{item.campaign_name}」復原原廠撥款登記", user)
    payout.voided_at, payout.voided_by = timezone.now(), actor_name(user)
    payout.save(update_fields=["voided_at", "voided_by", "updated_at"])
    return payout, items
