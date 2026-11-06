from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from sales.services.agency_fee import (
    compulsory_insurance_cost, default_agency_fee, default_plate_selection_expense,
    plate_fee_waived, registration_fee_cost,
)
from sales.services.customer_receivable import default_customer_balance


BALANCE_LABEL = "尾款"
LEGACY_INSTALLMENT_BALANCE_LABEL = "分期外應收"


def _money(value):
    return value or Decimal("0")


def _sync_financial_field(profile, field_name, value):
    if field_name not in (profile.manual_financial_fields or []):
        setattr(profile, field_name, _money(value))


def _expected_installment_disbursement(order):
    snapshot = order.installment_plan_snapshot or {}
    if "expected_disbursement_method" not in snapshot:
        return _money(order.installment_amount)
    amount = snapshot.get("expected_disbursement_amount")
    return Decimal(str(amount)) if amount is not None else Decimal("0")


def _upsert_system_payment(order, key, defaults, *, update_receivables=False):
    from sales.models import PaymentRecord

    defaults = {**defaults, "receipt_kind": "lender" if key in PaymentRecord.PAYOUT_KEYS else "customer"}
    payment, created = PaymentRecord.objects.get_or_create(
        order=order,
        system_key=key,
        defaults=defaults,
    )
    if created:
        return payment
    before = {name: getattr(payment, name) for name in defaults}
    protected = payment.confirmed or payment.received_amount or payment.proof
    payment.item_name = defaults["item_name"]
    if (not protected or update_receivables) and not payment.expected_amount_overridden:
        payment.expected_amount = defaults["expected_amount"]
    if key == "deposit" and not protected:
        for field in (
            "received_amount",
            "received_on",
            "payment_method",
        ):
            setattr(payment, field, defaults[field])
    changed = [name for name in defaults if getattr(payment, name) != before[name]]
    if changed:
        payment.save(update_fields=[*changed, "updated_at"])
    return payment


def payment_confirmation_changes(order_id, records=None):
    """重算「已收清／分期已撥款」旗標；回傳 (profile, {欄位: (目前, 重算後)})，只列有變的欄位、不存檔。"""
    from sales.models import OrderOperationsProfile, PaymentRecord

    profile = OrderOperationsProfile.objects.filter(order_id=order_id).select_related("order").first()
    if not profile:
        return None, {}
    from .payment_summary import effective_records, payment_summary
    records = list(PaymentRecord.objects.filter(order_id=order_id)) if records is None else list(records)
    confirmed = payment_summary(profile.order, records)["settled"]
    # 匯款已確認不等於所有款項已收清；短款仍由 payment_confirmed／應收差額呈現。
    installment_confirmed = profile.order.payment_type == "installment" and any(
        p.confirmed and p.effective_receipt_kind == "lender" and p.entry_type == "receipt"
        for p in effective_records(records)
    )
    proposed = {"payment_confirmed": confirmed, "installment_transfer_confirmed": installment_confirmed}
    return profile, {name: (getattr(profile, name), value) for name, value in proposed.items() if getattr(profile, name) != value}


def refresh_payment_confirmation(order_id):
    profile, changes = payment_confirmation_changes(order_id)
    if changes:
        for name, (_before, after) in changes.items():
            setattr(profile, name, after)
        profile.save(update_fields=[*changes, "updated_at"])


@transaction.atomic
def sync_payment_financials(order_id, *, adopt_payment_id=None, touch_revision=False):
    """所有收款入口共用；原始收款紀錄與營運財務在同一交易更新。"""
    from sales.models import OrderOperationsProfile, SalesOrder

    order = SalesOrder.objects.select_for_update().filter(pk=order_id).first()
    if not order:
        return
    profile = OrderOperationsProfile.objects.filter(order_id=order_id).first()
    if not profile:
        return
    fields = ("card_fee_income", "card_fee_expense", "actual_disbursement",
              "payment_disbursement_snapshot", "manual_financial_fields")
    before = {name: getattr(profile, name) for name in fields}
    # 被沖銷的收款視同未發生，其刷卡手續費不列入收支。
    totals = order.payment_records.filter(reversal_entries__isnull=True).aggregate(
        income=Sum("card_fee_charged"), expense=Sum("bank_card_fee"),
    )
    profile.card_fee_income = totals["income"] or Decimal("0")
    profile.card_fee_expense = totals["expense"] or Decimal("0")
    from .payment_summary import disbursement_receipts
    payments = disbursement_receipts(order)
    snapshot = dict(profile.payment_disbursement_snapshot or {})
    protected = set(profile.manual_financial_fields or [])
    if payments and (snapshot or any(p.pk == adopt_payment_id for p in payments)):
        if not snapshot:
            snapshot = {"previous": str(profile.actual_disbursement),
                        "was_manual": "actual_disbursement" in protected}
        # 統一撥款對帳入帳只改寫分期那部分（使用者 2026-10-21 T-62）：實際車價收入＝分期公司實收＋客人自付車款。
        customer_part = order.customer_vehicle_split_amount if order.payment_type == SalesOrder.PaymentType.INSTALLMENT else Decimal("0")
        profile.actual_disbursement = sum((p.received_amount for p in payments), Decimal("0")) + customer_part
        protected.add("actual_disbursement")
        snapshot.update(payment_id=payments[0].pk, payment_ids=[p.pk for p in payments], applied=str(profile.actual_disbursement))
    elif not payments and snapshot:
        # 只撤回由收款管理的金額，不覆寫之後另行人工輸入的金額。
        if profile.actual_disbursement == Decimal(snapshot["applied"]):
            if snapshot["was_manual"]:
                profile.actual_disbursement = Decimal(snapshot["previous"])
            else:
                from .incentive_rule import _calculated_disbursement
                profile.actual_disbursement = _calculated_disbursement(order) or Decimal("0")
                protected.discard("actual_disbursement")
        snapshot = {}
    profile.payment_disbursement_snapshot = snapshot
    profile.manual_financial_fields = sorted(protected)
    changed = [name for name in fields if getattr(profile, name) != before[name]]
    # 明細變更即使未改變合計，也須使其他人已開啟的營運表單失效。
    if changed or touch_revision:
        profile.save(update_fields=[*changed, "updated_at"])
    refresh_payment_confirmation(order_id)


@transaction.atomic
def sync_order_operations(order_id, *, update_receivables=False):
    from sales.models import OrderOperationsProfile, PaymentRecord, SalesOrder

    order = (
        SalesOrder.objects.select_related(
            "source",
            "allocated_vehicle",
        )
        .filter(pk=order_id)
        .first()
    )
    if not order:
        return None
    profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
    if hasattr(order, "legacy_snapshot") and (
        order.status == order.Status.COMPLETED or profile.legacy_finance_reconciliation
    ):
        # 歷史訂單並無當時完整價格／領牌費快照；一般編輯不得以現行空值覆寫財務。
        # 財務來自 Excel 的歷史匯入單（尚無車牌、待交車者亦同）不論狀態都保護。
        return profile
    profile_before = {field.attname: field.value_from_object(profile) for field in profile._meta.concrete_fields}
    profile.dealer_name = order.source.name if order.source_id else ""
    if (
        order.source_type != order.SourceType.PLATFORM
        and order.payment_type == order.PaymentType.CASH
        and "actual_disbursement" not in (profile.manual_financial_fields or [])
    ):
        profile.actual_disbursement = _money(order.vehicle_price)
    elif (
        order.source_type != order.SourceType.PLATFORM
        and order.payment_type == order.PaymentType.INSTALLMENT
        and "actual_disbursement" not in (profile.manual_financial_fields or [])
        and not profile.payment_disbursement_snapshot
        and not profile.incentive_locked_at
        and not order.is_cancelled_sale
    ):
        # 分期單建立後就帶入預估車價收入＝分期那筆×撥款比例＋客人自付車款（UAT U-02，使用者 2026-11-06 選 A），
        # 不必等到領牌；統一撥款對帳入帳後改為實收（由 sync_payment_financials 接手）。算不出比例時維持原值。
        from .incentive_rule import _calculated_disbursement
        estimate = _calculated_disbursement(order)
        if estimate is not None:
            profile.actual_disbursement = _money(estimate)
    installment_fee = (
        _money(order.installment_opening_fee)
        if order.payment_type == SalesOrder.PaymentType.INSTALLMENT
        else Decimal("0")
    )
    profile.installment_fee_income = installment_fee
    if order.status != SalesOrder.Status.COMPLETED and not order.is_cancelled_sale:
        # 收支領牌相關（使用者 2026-10-15，已完成與取消的訂單不重算）：規費、強制險收入預設等於支出，
        # 牌險溢收（可為負數）記牌險手續費收入；選號收入＝選號費、支出預設 1,000；分期手續費支出預設跟開辦費一樣。
        # 規費、強制險支出一律由本店付、照試算帶入，分期公司不負擔牌險（UAT p4，使用者 2026-11-06 選 A）；
        # 牌險填 0＝客人沒付、本店自己出，規費、強制險收入為 0（使用者 2026-10-19）。
        waived = plate_fee_waived(order)
        _sync_financial_field(profile, "registration_tax_expense", registration_fee_cost(order))
        _sync_financial_field(profile, "compulsory_insurance_expense", compulsory_insurance_cost(order))
        _sync_financial_field(profile, "plate_selection_expense", default_plate_selection_expense(order))
        _sync_financial_field(profile, "registration_tax_income", Decimal("0") if waived else profile.registration_tax_expense)
        _sync_financial_field(profile, "compulsory_insurance_income", Decimal("0") if waived else profile.compulsory_insurance_expense)
        _sync_financial_field(profile, "plate_selection_income", order.plate_selection_fee)
        _sync_financial_field(profile, "agency_fee_income", default_agency_fee(order, profile))
        _sync_financial_field(profile, "installment_fee_expense", installment_fee)
    profile.installment_info = (
        f"{order.installment_company}／{order.installment_periods}期／"
        f"每期 {order.installment_monthly:.0f} 元"
        if order.payment_type == SalesOrder.PaymentType.INSTALLMENT
        else ""
    )
    changed = [name for name, value in profile_before.items() if getattr(profile, name) != value]
    if changed:
        profile.save(update_fields=[*changed, "updated_at"])

    if order.status == SalesOrder.Status.CANCELLED:
        # 已取消的單不再產生或重建系統應收列（使用者 2026-11-06 選 B，services/cancelled_receivables.py）；
        # 已確認的實收與退款紀錄照舊保留，人工刪掉的系統列也不會被補回。
        refresh_payment_confirmation(order.pk)
        return profile

    active_keys = {"deposit"}
    _upsert_system_payment(
        order,
        "deposit",
        {
            "item_name": "訂金",
            "expected_amount": _money(order.deposit_amount),
            "received_amount": Decimal("0") if order.cash_receivable_v2 else _money(order.deposit_amount),
            "received_on": order.deposit_date,
            "payment_method": order.get_deposit_method_display()
            if order.deposit_method
            else "",
        },
        update_receivables=update_receivables,
    )

    if order.payment_type == SalesOrder.PaymentType.INSTALLMENT:
        expected_disbursement = _expected_installment_disbursement(order)
        extra_bonus = Decimal(
            str(
                (order.installment_plan_snapshot or {}).get(
                    "extra_disbursement_bonus"
                )
                or 0
            )
        )
        cash_due = default_customer_balance(order)
        active_keys.update({"installment_disbursement", "balance"})
        _upsert_system_payment(
            order,
            "installment_disbursement",
            {
                "item_name": (
                    f"分期公司撥款（含額外獎金 {extra_bonus:.0f} 元）"
                    if extra_bonus > 0
                    else "分期公司撥款"
                ),
                "expected_amount": expected_disbursement,
                "received_amount": Decimal("0"),
                "received_on": None,
                "payment_method": "分期撥款",
            },
            update_receivables=update_receivables,
        )
    else:
        cash_due = default_customer_balance(order)
        active_keys.add("balance")
    if order.payout_reconciliation_kind == "platform":
        # 平台撥款列（使用者 2026-10-22 T-96）：平台不先給預計金額，應收 0，只在統一撥款對帳登記實收。
        active_keys.add("platform_disbursement")
        _upsert_system_payment(
            order,
            "platform_disbursement",
            {
                "item_name": "平台撥款",
                "expected_amount": Decimal("0"),
                "received_amount": Decimal("0"),
                "received_on": None,
                "payment_method": "平台撥款",
            },
            update_receivables=update_receivables,
        )
    # 這一列是扣訂金後還要收的錢，分期、現金都叫「尾款」；分期外應收是扣訂金前的金額，
    # 只在訂購單與訂單頁另外列（使用者 2026-10-20）。舊名稱由 rename_balance_payment_label 回填。
    balance_label = BALANCE_LABEL
    _upsert_system_payment(
        order,
        "balance",
        {
            "item_name": balance_label,
            "expected_amount": cash_due,
            "received_amount": Decimal("0"),
            "received_on": None,
            "payment_method": order.get_payment_type_display(),
        },
        update_receivables=update_receivables,
    )

    stale = PaymentRecord.objects.filter(order=order).exclude(system_key="")
    stale = stale.exclude(system_key__in=active_keys)
    for payment in stale:
        if not payment.confirmed and not payment.received_amount and not payment.proof:
            payment.delete()
        else:
            # 保留原款項分類，避免撥款列轉為人工列後被改算成客戶款。
            payment.receipt_kind = payment.effective_receipt_kind
            payment.system_key = ""
            payment.note = (
                f"{payment.note}；" if payment.note else ""
            ) + "付款方式已變更，已保留為人工收款紀錄"
            payment.save(update_fields=["receipt_kind", "system_key", "note", "updated_at"])

    refresh_payment_confirmation(order.pk)
    if _commission_follows_master(order, profile):
        from .dealer_commission import apply_order_dealer_commission
        from .settlement_cost import apply_estimated_settlement_cost
        # 建立訂單即帶入已設定的車行／本店人員傭金與預估車輛成本；人工覆寫與領牌後鎖定由服務本身保護。
        apply_estimated_settlement_cost(order)
        profile = apply_order_dealer_commission(order)
    return profile


def _commission_follows_master(order, profile):
    """只有尚未領牌、未取消、未鎖定的系統訂單隨主檔帶入傭金；匯入訂單保留原始值。"""
    if order.registration_completed_at or order.is_cancelled_sale or profile.dealer_commission_locked_at:
        return False
    return not hasattr(order, "legacy_snapshot")
