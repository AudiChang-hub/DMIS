"""原廠代墊／代轉活動（T-337 第二版）：依活動自動掛單、預計適用、單張訂單「不適用」。

- 條件：活動啟用、原廠＝訂單車型的品牌（不分大小寫）、適用車型留白＝該原廠全部車型、期間涵蓋日期、
  對象是車行時只限有車行的車行單。取消、刪除與 Excel 匯入的歷史單不掛（匯入單一律算已結清）。
- 已確認實際領牌：依實際領牌日自動掛上一筆項目（origin=campaign、origin_key=campaign:<活動 id>，一單一活動一筆）。
  還沒確認領牌：依訂單日期在訂單頁顯示「預計適用」，不建項目、不進追蹤頁與營運總表。
- 已經勾過「原廠已撥」或「已交給對象」的項目固定不動；還沒勾的跟著活動更新內容，條件不再符合時由系統移除（作廢）。
- 「不適用」：從該單移除，之後也不再自動掛回去；可以復原（復原後依條件重新掛上）。
- 只讀寫代墊／代轉自己的表與訂單事件：不碰收支、淨利、應收、傭金、交車。
"""
import logging

from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from sales.models import (ManufacturerAdvance, ManufacturerAdvanceCampaign, ManufacturerAdvanceExclusion, OrderEvent,
                          SalesOrder, VehicleModel)
from sales.services.manufacturer_advance import Conflict, EVENT_TYPE, ZERO, actor_name, dealer_available

logger = logging.getLogger(__name__)

SYSTEM_NAME = "系統"
SYSTEM_VOID = "系統（活動條件不符）"
CLOSED_STATUSES = {SalesOrder.Status.CANCELLED, SalesOrder.Status.CANCEL_REFUND_PENDING}
CONTENT_FIELDS = ("manufacturer", "campaign_name", "recipient", "kind", "amount", "gift_name", "gift_quantity")
# 訂單存檔時只有這些欄位變了才需要重新比對（沒帶 update_fields 的一般存檔也比對）。
ORDER_FIELDS = {"registration_date", "registration_completed_at", "vehicle_model", "source_type", "source", "status",
                "deleted_at"}


# ── 比對 ──────────────────────────────────────────────────────────────


def applies_on(order):
    """(比對日期, 是否只是預計)：確認實際領牌後用實際領牌日，之前用訂單日期。"""
    if order.registration_completed_at and order.registration_date:
        return order.registration_date, False
    return order.order_date, True


def order_eligible(order):
    if order.deleted_at or order.status in CLOSED_STATUSES or not order.vehicle_model_id:
        return False
    return not hasattr(order, "legacy_snapshot")


def active_campaigns():
    return list(ManufacturerAdvanceCampaign.objects.filter(active=True).prefetch_related("vehicle_models"))


def _model_ids(campaign):
    return {model.pk for model in campaign.vehicle_models.all()}


def matches(campaign, order, day):
    if not campaign.active or day is None or not order.vehicle_model_id:
        return False
    if (order.vehicle_model.brand or "").casefold() != (campaign.manufacturer or "").casefold():
        return False
    model_ids = _model_ids(campaign)
    if model_ids and order.vehicle_model_id not in model_ids:
        return False
    if day < campaign.effective_from or (campaign.effective_to and day > campaign.effective_to):
        return False
    if campaign.recipient == ManufacturerAdvance.Recipient.DEALER and not dealer_available(order):
        return False
    return True


def excluded_ids(order):
    return set(order.manufacturer_advance_exclusions.values_list("campaign_id", flat=True))


def matching_campaigns(order, day, campaigns=None):
    campaigns = active_campaigns() if campaigns is None else campaigns
    excluded = excluded_ids(order)
    return [campaign for campaign in campaigns if campaign.pk not in excluded and matches(campaign, order, day)]


def projected_campaigns(order):
    """還沒確認領牌的單：依訂單日期「預計適用」的活動（只顯示，不建項目）。"""
    day, projected = applies_on(order)
    if not projected or not order_eligible(order):
        return []
    return matching_campaigns(order, day)


def exclusions(order):
    return list(order.manufacturer_advance_exclusions.select_related("campaign"))


# ── 自動掛單 ──────────────────────────────────────────────────────────


def _content(campaign):
    return {
        "manufacturer": campaign.manufacturer, "campaign_name": campaign.name, "recipient": campaign.recipient,
        "kind": campaign.kind, "amount": campaign.amount if campaign.is_cash else ZERO,
        "gift_name": "" if campaign.is_cash else campaign.gift_name,
        "gift_quantity": 0 if campaign.is_cash else campaign.gift_quantity,
    }


def untouched(item):
    return not item.reimbursed and not item.handed_over


def _event(order, description, name=SYSTEM_NAME):
    OrderEvent.objects.create(order=order, event_type=EVENT_TYPE, description=description, actor_name=name)


@transaction.atomic
def reconcile_order(order, campaigns=None):
    """讓這張單的自動掛單跟活動條件一致；回傳 (掛上, 移除) 筆數。勾過的項目不動。"""
    day, projected = applies_on(order)
    desired = {}
    if not projected and order_eligible(order):
        desired = {campaign.pk: campaign for campaign in matching_campaigns(order, day, campaigns)}
    existing = {item.campaign_id: item for item in ManufacturerAdvance.objects.select_for_update(of=("self",))
                .filter(order=order, campaign__isnull=False)}
    if not desired and not existing:
        return 0, 0
    excluded = excluded_ids(order) if existing else set()
    attached = removed = 0
    for pk, campaign in desired.items():
        content = _content(campaign)
        item = existing.get(pk)
        if item is None:
            try:
                with transaction.atomic():
                    item = ManufacturerAdvance.objects.create(
                        order=order, campaign=campaign, origin=ManufacturerAdvance.Origin.CAMPAIGN,
                        origin_key=campaign.origin_key, created_by_name=SYSTEM_NAME, **content,
                    )
            except IntegrityError:  # 同時有別處剛掛上（一單一活動一筆）
                continue
            attached += 1
            _event(order, f"依活動自動掛上原廠代墊／代轉：{item.manufacturer}「{item.campaign_name}」給{item.get_recipient_display()} {item.content_label}")
            continue
        if not untouched(item):
            continue
        fields = [name for name, value in content.items() if getattr(item, name) != value]
        for name in fields:
            setattr(item, name, content[name])
        if item.voided_at:
            item.voided_at, item.voided_by = None, ""
            fields += ["voided_at", "voided_by"]
            attached += 1
            _event(order, f"依活動重新掛上原廠代墊／代轉「{item.campaign_name}」")
        if fields:
            item.save(update_fields=[*fields, "updated_at"])
    for pk, item in existing.items():
        if pk in desired or pk in excluded or item.voided_at or not untouched(item):
            continue
        item.voided_at, item.voided_by = timezone.now(), SYSTEM_VOID
        item.save(update_fields=["voided_at", "voided_by", "updated_at"])
        removed += 1
        _event(order, f"活動條件已不符合，自動移除原廠代墊／代轉「{item.campaign_name}」")
    return attached, removed


def reconcile_order_pk(pk):
    """訂單存檔後（交易提交後）呼叫；失敗只記 log，不影響訂單存檔。"""
    try:
        order = SalesOrder.all_objects.select_related("vehicle_model", "source").filter(pk=pk).first()
        if order is None:
            return
        if not order.registration_completed_at and not ManufacturerAdvance.objects.filter(
                order=order, campaign__isnull=False, voided_at__isnull=True).exists():
            return
        if not ManufacturerAdvanceCampaign.objects.exists():
            return
        reconcile_order(order)
    except Exception:  # noqa: BLE001 — 自動掛單失敗不能擋訂單存檔
        logger.exception("原廠代墊／代轉自動掛單失敗：訂單 %s", pk)


def order_saved(sender, instance, created=False, update_fields=None, raw=False, **kwargs):
    if raw or instance.pk is None:
        return
    if update_fields is not None and not ORDER_FIELDS & set(update_fields):
        return
    pk = instance.pk
    transaction.on_commit(lambda: reconcile_order_pk(pk))


def campaign_orders(campaign):
    """活動存檔後要重新比對的訂單：已確認領牌、品牌相同、領牌日在期間內，加上已經掛著這個活動的。"""
    scope = Q(registration_completed_at__isnull=False, registration_date__gte=campaign.effective_from,
              vehicle_model__brand__iexact=campaign.manufacturer)
    if campaign.effective_to:
        scope &= Q(registration_date__lte=campaign.effective_to)
    ids = set(SalesOrder.all_objects.filter(scope).values_list("pk", flat=True))
    ids |= set(campaign.advance_items.values_list("order_id", flat=True))
    return SalesOrder.all_objects.select_related("vehicle_model", "source").filter(pk__in=ids).order_by("pk")


@transaction.atomic
def reconcile_campaign(campaign):
    """活動新增、修改、停用後：依條件掛上或移除（勾過的不動）。回傳 (掛上, 移除) 筆數。"""
    campaigns = active_campaigns()
    attached = removed = 0
    for order in campaign_orders(campaign):
        added, dropped = reconcile_order(order, campaigns)
        attached, removed = attached + added, removed + dropped
    return attached, removed


# ── 不適用 ────────────────────────────────────────────────────────────


@transaction.atomic
def mark_not_applicable(order, campaign, user):
    """這張單不適用這個活動：移除已掛上的項目，之後不再自動掛回去。勾過的項目要先取消勾選。"""
    item = (ManufacturerAdvance.objects.select_for_update(of=("self",)).select_related("order")
            .filter(order=order, campaign=campaign).first())
    if item and not untouched(item):
        raise Conflict("已經勾過「原廠已撥」或「已交給對象」的項目不能標不適用，請先取消勾選。", [item])
    _exclusion, created = ManufacturerAdvanceExclusion.objects.get_or_create(
        order=order, campaign=campaign, defaults={"created_by": user, "created_by_name": actor_name(user)},
    )
    if item and item.voided_at is None:
        item.voided_at, item.voided_by = timezone.now(), actor_name(user)
        item.save(update_fields=["voided_at", "voided_by", "updated_at"])
    if created:
        _event(order, f"原廠代墊／代轉活動「{campaign.name}」標為不適用，之後不再自動掛上", actor_name(user))
    return item


@transaction.atomic
def clear_not_applicable(order, campaign, user):
    """復原「不適用」：依條件重新掛上（已確認領牌）或回到預計適用。"""
    deleted, _ = ManufacturerAdvanceExclusion.objects.filter(order=order, campaign=campaign).delete()
    if deleted:
        _event(order, f"原廠代墊／代轉活動「{campaign.name}」取消不適用", actor_name(user))
    reconcile_order(order)
    return order.manufacturer_advances.filter(campaign=campaign).first()


# ── 活動設定 ──────────────────────────────────────────────────────────


def campaign_rows(queryset):
    return queryset.prefetch_related("vehicle_models").annotate(
        attached_count=Count("advance_items", filter=Q(advance_items__voided_at__isnull=True), distinct=True),
    )


def models_label(campaign):
    models = list(campaign.vehicle_models.all())
    if not models:
        return f"{campaign.manufacturer} 全部車型"
    names = [f"{model.name}{f' {model.model_year}' if model.model_year else ''}" for model in models]
    return "、".join(names[:3]) + (f" 等 {len(names)} 款" if len(names) > 3 else "")


class CampaignForm(forms.ModelForm):
    class Meta:
        model = ManufacturerAdvanceCampaign
        fields = ("name", "manufacturer", "effective_from", "effective_to", "vehicle_models", "recipient", "kind",
                  "amount", "gift_name", "gift_quantity", "active")
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "effective_to": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "recipient": forms.RadioSelect, "kind": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        from sales.forms import CampaignVehicleModelSelectMultiple, _brand_choices

        super().__init__(*args, **kwargs)
        current = self.instance.manufacturer if self.instance.pk else ""
        self.fields["manufacturer"] = forms.ChoiceField(label="原廠", choices=_brand_choices(current))
        self.fields["manufacturer"].initial = current
        selected = list(self.instance.vehicle_models.values_list("pk", flat=True)) if self.instance.pk else []
        field = self.fields["vehicle_models"]
        field.widget = CampaignVehicleModelSelectMultiple()
        field.queryset = VehicleModel.objects.filter(Q(active=True) | Q(pk__in=selected)).order_by(
            "brand", "name", "-model_year", "model_code")
        field.widget.choices = field.choices
        field.required = False
        field.label = "適用車型"
        field.help_text = "留白代表這個原廠的全部車型。"
        field.widget.attrs.update({"data-searchable-select": "1", "data-search-placeholder": "不限車型；搜尋並複選",
                                   "data-search-empty-message": "沒有符合的車型", "data-advance-campaign-models": ""})
        self.fields["effective_to"].help_text = "可留白，代表持續有效。"
        self.fields["name"].widget.attrs.update({"placeholder": "例如：年終加碼現金回饋", "autocomplete": "off"})
        self.fields["amount"].required = False
        self.fields["gift_quantity"].required = False
        self.fields["amount"].widget.attrs.update({"inputmode": "numeric", "min": "1", "step": "1"})
        self.fields["gift_quantity"].widget.attrs.update({"inputmode": "numeric", "min": "1", "step": "1"})
        self.fields["recipient"].help_text = "車行：只掛在有車行的車行單。"
        for name, item in self.fields.items():
            if not isinstance(item.widget, (forms.CheckboxInput, forms.RadioSelect)):
                item.widget.attrs.setdefault("class", "form-control")

    def clean_name(self):
        value = " ".join((self.cleaned_data.get("name") or "").split())
        if not value:
            raise ValidationError("請填活動名稱。")
        return value

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("effective_from"), cleaned.get("effective_to")
        if start and end and end < start:
            self.add_error("effective_to", "結束日不能早於開始日。")
        manufacturer = (cleaned.get("manufacturer") or "").casefold()
        others = [model for model in cleaned.get("vehicle_models") or [] if (model.brand or "").casefold() != manufacturer]
        if manufacturer and others:
            self.add_error("vehicle_models", f"適用車型要是同一個原廠的車：{'、'.join(model.name for model in others[:3])} 不是。")
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
