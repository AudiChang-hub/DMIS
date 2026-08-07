import hashlib
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder, SubsidyItem, VehicleInventory
from sales.services.business_days import add_business_days
from sales.services.settlement_cost import resolve_settlement_cost


@dataclass(frozen=True, slots=True)
class NextAction:
    key: str
    title: str
    description: str
    action_label: str
    url: str
    badge: str = "建議下一步"
    tone: str = "primary"
    target_tab: str = ""
    target_anchor: str = ""


@dataclass(frozen=True, slots=True)
class OrderNextActions:
    primary: NextAction
    secondary: tuple[NextAction, ...]
    state_key: str

    @property
    def all_actions(self):
        return (self.primary, *self.secondary)


def _tab_url(order, tab):
    return f"{reverse('order_detail', args=[order.pk])}?{urlencode({'tab': tab})}"


def _deadline_description(prefix, due_date, today):
    due_label = due_date.strftime("%Y/%m/%d")
    if today > due_date:
        return f"{prefix}期限為 {due_label}，目前已逾期，請優先處理。"
    if today == due_date:
        return f"{prefix}今天（{due_label}）到期，請優先處理。"
    return f"{prefix}請於 {due_label} 前完成。"


def _delivered_on(order):
    if not order.delivered_at:
        return None
    if timezone.is_aware(order.delivered_at):
        return timezone.localtime(order.delivered_at).date()
    return order.delivered_at.date()


def _pending_reconciliation_action(order, today):
    pending_records = []
    for record in order.payment_records.all():
        eligible = record.system_key == "installment_disbursement" or (
            record.system_key == "balance"
            and order.source_type
            in {SalesOrder.SourceType.PLATFORM, SalesOrder.SourceType.DEALER}
        )
        if eligible and not record.confirmed and record.expected_amount > 0:
            pending_records.append(record)
    if not pending_records:
        return None

    description = f"尚有 {len(pending_records)} 筆實際撥款／收款待確認。"
    tone = "primary"
    badge = "結案前確認"
    delivered_on = _delivered_on(order)
    if order.source_type == SalesOrder.SourceType.DEALER and delivered_on:
        due_date = add_business_days(delivered_on, 7)
        description = _deadline_description("合作車行款項", due_date, today)
        tone = "urgent" if today >= due_date else "primary"
        badge = "收款期限"

    query = urlencode({"q": order.number, "status": "pending"})
    return NextAction(
        key="reconciliation",
        title="確認實際撥款與收款",
        description=description,
        action_label="前往統一對帳",
        url=f"{reverse('reconciliation_list')}?{query}",
        badge=badge,
        tone=tone,
    )


def _subsidy_action(order, subsidy_missing):
    if not order.is_trade_in_subsidy:
        return None
    if subsidy_missing:
        return NextAction(
            key="subsidy",
            title=f"補齊補助資料（尚缺 {len(subsidy_missing)} 項）",
            description="補助可與配車、領牌同步處理，不會阻擋主要流程。",
            action_label="前往補助",
            url=_tab_url(order, "subsidy"),
            badge="可同步處理",
            tone="parallel",
            target_tab="subsidy",
        )

    items = list(order.subsidy_items.all())
    if not items:
        title = "建立補助申請項目"
        description = "固定文件已齊，可逐筆記錄補助類別、金額與申請進度。"
    elif any(item.status == SubsidyItem.Status.NOT_SUBMITTED for item in items):
        title = "送出補助申請"
        description = "補助資料已備妥，仍有項目尚未送出申請。"
    elif any(item.status == SubsidyItem.Status.SUBMITTED for item in items):
        title = "更新補助申請進度"
        description = "已有補助送件，完成後請更新為「已申請完成」。"
    else:
        return None
    return NextAction(
        key="subsidy",
        title=title,
        description=description,
        action_label="前往補助",
        url=_tab_url(order, "subsidy"),
        badge="可同步處理",
        tone="parallel",
        target_tab="subsidy",
    )


def _document_archive_action(order):
    missing = []
    if not order.has_signed_contract:
        missing.append("訂購合約")
    if not order.has_privacy_consent:
        missing.append("個資同意書")
    if not missing:
        return None
    return NextAction(
        key="documents",
        title="補上簽署文件",
        description=f"尚未上傳：{'、'.join(missing)}；取得紙本照片後可隨時補上。",
        action_label="查看簽署文件",
        url=f"{_tab_url(order, 'order')}#signed-documents",
        badge="可稍後處理",
        tone="optional",
        target_tab="order",
        target_anchor="signed-documents",
    )


def _registration_action(order, registration_missing):
    if registration_missing:
        preview = "、".join(registration_missing[:3])
        if len(registration_missing) > 3:
            preview += f"等 {len(registration_missing)} 項"
        return NextAction(
            key="registration",
            title=f"補齊領牌資料（尚缺 {len(registration_missing)} 項）",
            description=f"目前待補：{preview}。",
            action_label="前往領牌",
            url=_tab_url(order, "registration"),
            target_tab="registration",
        )

    rule = resolve_settlement_cost(
        order.vehicle_model_id,
        order.registration_county,
        order.registration_date,
    )
    if not rule:
        query = urlencode(
            {
                "q": f"{order.vehicle_model.brand} {order.vehicle_model.name}",
                "registration_county": order.registration_county,
            }
        )
        return NextAction(
            key="settlement-cost",
            title="補建代銷結算成本",
            description="領牌資料已齊，但找不到適用的車型、縣市與生效日成本版本。",
            action_label="查看成本規則",
            url=f"{reverse('settlement_cost_rule_list')}?{query}",
            badge="完成領牌前必須處理",
            tone="urgent",
        )
    return NextAction(
        key="registration",
        title="確認領牌完成",
        description="領牌資料與必備文件已齊，請核對後完成此階段。",
        action_label="前往領牌確認",
        url=_tab_url(order, "registration"),
        target_tab="registration",
    )


def _state_key(primary, secondary):
    values = []
    for action in (primary, *secondary):
        values.extend(
            [
                action.key,
                action.title,
                action.description,
                action.url,
                action.tone,
                action.target_tab,
            ]
        )
        if action.target_anchor:
            values.append(action.target_anchor)
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()[:16]


def build_order_next_actions(
    order,
    *,
    registration_missing=None,
    subsidy_missing=None,
    today: date | None = None,
):
    """依訂單事實產生一項主要建議與最多兩項平行建議。"""
    today = today or timezone.localdate()
    registration_missing = (
        list(registration_missing)
        if registration_missing is not None
        else order.missing_registration_requirements()
    )
    subsidy_missing = (
        list(subsidy_missing)
        if subsidy_missing is not None
        else order.missing_subsidy_requirements()
    )

    if order.status == SalesOrder.Status.CANCELLED:
        return None
    if order.status == SalesOrder.Status.CANCEL_REFUND_PENDING:
        primary = NextAction(
            key="refund",
            title="完成訂金全額退款",
            description="退款完成後，這張訂單才會正式取消。",
            action_label="前往處理退款",
            url=_tab_url(order, "order"),
            badge="優先處理",
            tone="urgent",
            target_tab="order",
        )
        return OrderNextActions(primary, (), _state_key(primary, ()))

    secondary = []
    primary = None
    vehicle = order.allocated_vehicle

    if order.status == SalesOrder.Status.DRAFT:
        primary = NextAction(
            key="complete-order",
            title="完成訂單資料",
            description="這張訂單仍是草稿，請確認資料後完成建立。",
            action_label="繼續編輯訂單",
            url=reverse("order_edit", args=[order.pk]),
        )
    elif order.status == SalesOrder.Status.COMPLETED:
        # 歷史匯入資料可能沒有實體配車；結案後不應再倒退提示進車或配車。
        primary = None
    elif not order.allocated_vehicle_id:
        has_available_vehicle = VehicleInventory.objects.filter(
            vehicle_model_id=order.vehicle_model_id,
            color_id=order.color_id,
            status=VehicleInventory.Status.AVAILABLE,
        ).exists()
        if has_available_vehicle:
            primary = NextAction(
                key="allocation",
                title="選擇實體車輛",
                description="已有符合車型與車色的可售庫存，可由人員確認後配車。",
                action_label="前往配車",
                url=_tab_url(order, "allocation"),
                target_tab="allocation",
            )
        else:
            primary = NextAction(
                key="inventory-entry",
                title="先建立符合的進車資料",
                description=(
                    f"目前沒有符合「{order.vehicle_model}／{order.color.name}」"
                    "的可售庫存。"
                ),
                action_label="前往快速進車",
                url=reverse("inventory_quick_create"),
                badge="目前無可配車輛",
                tone="urgent",
            )
    elif vehicle.status == VehicleInventory.Status.CONDITION_ISSUE:
        primary = NextAction(
            key="vehicle-condition",
            title="先處理實體車輛的車況",
            description="配車車輛標記為車況異常，請確認處理結果後再往下作業。",
            action_label="查看庫存車輛",
            url=reverse("inventory_edit", args=[vehicle.pk]),
            badge="需先確認",
            tone="urgent",
        )
    elif vehicle.status in {
        VehicleInventory.Status.TRANSFER_PENDING,
        VehicleInventory.Status.IN_TRANSFER,
    }:
        primary = NextAction(
            key="vehicle-transfer",
            title="追蹤調車並確認實際到店",
            description="車輛仍在調度中；實際送達並核對車況後再繼續作業。",
            action_label="查看調車資料",
            url=reverse("inventory_edit", args=[vehicle.pk]),
            badge="調車進行中",
        )
    elif order.is_delivered and not order.is_registration_complete:
        delivered_on = _delivered_on(order)
        due_date = add_business_days(delivered_on, 3) if delivered_on else today
        primary = NextAction(
            key="registration",
            title="補齊領牌資料與文件",
            description=_deadline_description("合作車行交付後的領牌資料", due_date, today),
            action_label="前往領牌",
            url=_tab_url(order, "registration"),
            badge="交付後期限",
            tone="urgent" if today >= due_date else "primary",
            target_tab="registration",
        )
    elif not order.is_registration_complete:
        primary = _registration_action(order, registration_missing)
        if order.source_type == SalesOrder.SourceType.DEALER and not order.is_delivered:
            secondary.append(
                NextAction(
                    key="dealer-early-delivery",
                    title="合作車行可先領車",
                    description="如需先交付，可完成交付核對，領牌資料於交付後三個工作日內補齊。",
                    action_label="前往交付",
                    url=_tab_url(order, "delivery"),
                    badge="可同步處理",
                    tone="parallel",
                    target_tab="delivery",
                )
            )
    elif not order.is_delivered:
        primary = NextAction(
            key="delivery",
            title="完成車輛交付",
            description="領牌已完成，請核對車況、文件、鑰匙、配件與收款。",
            action_label="前往交付",
            url=_tab_url(order, "delivery"),
            target_tab="delivery",
        )

    reconciliation = _pending_reconciliation_action(order, today) if order.is_delivered else None
    subsidy = _subsidy_action(order, subsidy_missing)

    if primary is None:
        primary = reconciliation or subsidy
    else:
        for action in (reconciliation, subsidy):
            if action and action.key != primary.key:
                secondary.append(action)

    if primary is None:
        return None

    if not order.is_delivered:
        archive = _document_archive_action(order)
        if archive and archive.key != primary.key:
            secondary.append(archive)

    deduplicated = []
    seen = {primary.key}
    for action in secondary:
        if action.key in seen:
            continue
        seen.add(action.key)
        deduplicated.append(action)
        if len(deduplicated) == 2:
            break
    secondary_tuple = tuple(deduplicated)
    return OrderNextActions(
        primary=primary,
        secondary=secondary_tuple,
        state_key=_state_key(primary, secondary_tuple),
    )
