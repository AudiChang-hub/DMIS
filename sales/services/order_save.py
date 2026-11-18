"""訂單頁自動儲存「驗證通過後」的儲存流程（T-232 第 2 版，方案 A）。

`order_edit`（訂車與配件）、`order_operations`（收支、舊車與報廢、車控電池、獨立營運頁）、
`subsidy_data_update`（汰舊補助資料）三個端點原本把存檔、連動與留痕寫在 view 裡；這裡原封不動搬出來，
讓畫面自動儲存和之後的回匯批次修改呼叫同一段程式：同樣的重算（尾款、價格與分期快照、未領牌單的成本／獎勵／傭金、
收支同步）與同樣的 `OrderChange`／`OrderEvent` 留痕。

用法跟 view 一樣分兩段：
1. 表單驗證「之前」先 `*_baseline()` 記下修改前的狀態（ModelForm 驗證會改動 instance，之後就拿不到原值）。
2. 表單、明細都驗證通過後呼叫 `save_*()`；呼叫端負責權限、版本號檢查與交易（view 有 `@transaction.atomic`）。

`views.py` 裡的 `_order_snapshot`、`_record_settlement_gap` 等小工具其他端點也在用，這一版不搬，經下方轉呼叫使用。
"""
from dataclasses import dataclass
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from sales.models import OrderChange, OrderEvent, OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services import id_card_crop
from sales.services.audit_note import balance_summary, note_or_summary
from sales.services.customer_receivable import PLATE_INCOME_FIELDS
from sales.services.installment_plan import apply_order_installment_snapshot
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_ledger import settlement_gap
from sales.services.price_version import apply_order_price_snapshot
from sales.services.secret_fields import encrypt_secret


def _views():
    from sales import views
    return views


def _editing_name(user):
    return _views()._editing_name(user)


def _order_snapshot(order):
    return _views()._order_snapshot(order)


def _snapshot_changes(before, after):
    return _views()._snapshot_changes(before, after)


def _operations_snapshot(profile):
    return _views()._operations_snapshot(profile)


def _payment_deletion_snapshot(payment):
    return _views()._payment_deletion_snapshot(payment)


def _schedule_model_file_cleanup(model, field_name, previous_name):
    return _views()._schedule_model_file_cleanup(model, field_name, previous_name)


def _schedule_replaced_identity_file_cleanup(order, previous_names):
    return _views()._schedule_replaced_identity_file_cleanup(order, previous_names)


def _apply_submitted_subsidy_programs(order, form, post_data):
    return _views()._apply_submitted_subsidy_programs(order, form, post_data)


def _record_duplicate_acknowledgements(order, forms, user):
    return _views()._record_duplicate_acknowledgements(order, forms, user)


def _record_settlement_gap(order, before, user):
    return _views()._record_settlement_gap(order, before, user)


# ---------------------------------------------------------------- 訂車與配件（order_edit）

@dataclass
class ContentBaseline:
    completed_correction: bool
    gap_before: object
    before: dict
    previous_identity_names: dict
    previous_vehicle_model_id: int
    previous_color_id: int
    installment_before: tuple
    balance_was_automatic: bool
    previous_actual_balance: object


def content_baseline(order):
    """表單驗證前記下的原值。"""
    completed_correction = order.is_delivered
    gap_before = settlement_gap(order) if completed_correction else None
    before = _order_snapshot(order)
    previous_identity_names = {
        field_name: getattr(getattr(order, field_name), "name", "")
        for field_name in ("id_front", "id_back")
    }
    previous_vehicle_model_id = order.vehicle_model_id
    previous_color_id = order.color_id
    installment_before = tuple(getattr(order, name) for name in (
        "vehicle_model_id", "order_date", "payment_type", "vehicle_price", "installment_split_amount",
        "installment_company", "installment_periods", "installment_monthly", "installment_opening_fee", "installment_custom",
    ))
    balance_was_automatic = order.actual_balance == order.calculated_balance
    previous_actual_balance = order.actual_balance
    return ContentBaseline(
        completed_correction=completed_correction, gap_before=gap_before, before=before,
        previous_identity_names=previous_identity_names, previous_vehicle_model_id=previous_vehicle_model_id,
        previous_color_id=previous_color_id, installment_before=installment_before,
        balance_was_automatic=balance_was_automatic, previous_actual_balance=previous_actual_balance,
    )


def save_order_content(order, form, formset, fee_formset, baseline, *, user, posted, reason="修改訂單資料"):
    """`OrderEditForm`＋配件、其他費用明細都驗證通過後存檔；回傳存好的訂單與新學到的配件名稱。"""
    actor = _editing_name(user)
    completed_correction = baseline.completed_correction
    gap_before = baseline.gap_before
    before = baseline.before
    previous_identity_names = baseline.previous_identity_names
    previous_vehicle_model_id = baseline.previous_vehicle_model_id
    installment_before = baseline.installment_before
    balance_was_automatic = baseline.balance_was_automatic
    previous_actual_balance = baseline.previous_actual_balance
    order = form.save(commit=False)
    changed_photos = {
        field_name for field_name, previous_name in previous_identity_names.items()
        if getattr(getattr(order, field_name), "name", "") != previous_name
    }
    cropped_photos = [
        field_name for field_name in id_card_crop.apply_posted_crops(order, posted, changed=changed_photos)
        if field_name not in changed_photos and getattr(order, f"{field_name}_crop")
    ]
    if form.unallocate_requested:
        # 使用者已在警告視窗確認：同一交易內先取消配車（車輛回到可銷售、留紀錄），再存新車型／車色。
        order.unallocate(actor_name=actor, reason="修改車型／車色")
    if (
        order.actual_balance != order.calculate_balance()
        and not order.balance_adjustment_reason
    ):
        order.balance_adjustment_reason = balance_summary("修改訂單資料")
    order.revision += 1
    order.editing_session = ""
    order.editing_by = ""
    order.editing_at = None
    order.save()
    _apply_submitted_subsidy_programs(order, form, posted)
    _schedule_replaced_identity_file_cleanup(
        order,
        previous_identity_names,
    )
    if not completed_correction or previous_vehicle_model_id != order.vehicle_model_id:
        apply_order_price_snapshot(
            order,
            force=(previous_vehicle_model_id != order.vehicle_model_id or not order.price_snapshot),
        )
    installment_after = tuple(getattr(order, name) for name in (
        "vehicle_model_id", "order_date", "payment_type", "vehicle_price", "installment_split_amount",
        "installment_company", "installment_periods", "installment_monthly", "installment_opening_fee", "installment_custom",
    ))
    if installment_after != installment_before or (not completed_correction and not order.installment_plan_snapshot):
        apply_order_installment_snapshot(order)
    from sales.services.accessory_catalog import custom_accessory_categories, learn_custom_accessories, learnable_custom_names
    # 存檔前記下這次新增或改名的自填列；舊列是歷史紀錄，不再加回主檔（T-179）。
    learnable_names = learnable_custom_names(formset)
    formset.save()
    fee_formset.save()
    learned_accessories = learn_custom_accessories(order, actor, categories=custom_accessory_categories(formset),
                                                   names=learnable_names)
    order._prefetched_objects_cache = {}
    order.calculated_balance = order.calculate_balance()
    order.actual_balance = (
        order.calculated_balance
        if balance_was_automatic
        else previous_actual_balance
    )
    order.save(
        update_fields=[
            "calculated_balance",
            "actual_balance",
            "revision",
            "editing_session",
            "editing_by",
            "editing_at",
            "updated_at",
        ]
    )
    after = _order_snapshot(order)
    from sales.services.financial_refresh import refresh_unlocked_financials
    if not completed_correction:
        refresh_unlocked_financials(order.pk)
    changes = _snapshot_changes(before, after)
    OrderChange.objects.create(
        order=order,
        reason=reason,
        changes=changes,
        actor_name=actor,
    )
    OrderEvent.objects.create(
        order=order,
        event_type="updated",
        description=f"{'完成後修正' if completed_correction else '修改訂單'}（{len(changes)} 個項目）",
        actor_name=actor,
    )
    if cropped_photos:
        OrderEvent.objects.create(
            order=order,
            event_type="id_crop_adjusted",
            description="已調整車主證件" + "、".join("正面" if name == "id_front" else "反面" for name in cropped_photos) + "的裁切／旋轉（原始照片保留）。",
            actor_name=actor,
        )
    if completed_correction:
        _record_settlement_gap(order, gap_before, user)
    return SimpleNamespace(order=order, learned_accessories=learned_accessories, changes=changes)


# ---------------------------------------------------------------- 收支、舊車與報廢、車控電池（order_operations）

@dataclass
class OperationsBaseline:
    financial_before: dict
    before: dict
    gap_before: object
    previous_payment_proofs: list


def operations_baseline(order, profile):
    """表單驗證前記下的原值。"""
    financial_before = {
        field_name: getattr(profile, field_name)
        for field_name in profile.MANUAL_PROTECTABLE_FINANCIAL_FIELDS
    }
    before = _operations_snapshot(profile)
    gap_before = settlement_gap(order)
    previous_payment_proofs = list(
        order.payment_records.exclude(proof="").values_list("proof", flat=True)
    )
    return OperationsBaseline(financial_before=financial_before, before=before, gap_before=gap_before,
                              previous_payment_proofs=previous_payment_proofs)


def save_operations(order, profile, form, payment_formset, baseline, *, user):
    """`OrderOperationsForm`（與收款明細，若有）驗證通過後存檔；回傳存好的收支資料。"""
    actor = _editing_name(user)
    financial_before = baseline.financial_before
    before = baseline.before
    gap_before = baseline.gap_before
    previous_payment_proofs = baseline.previous_payment_proofs
    with transaction.atomic():
        profile = form.save(commit=False)
        protected_fields = set(profile.manual_financial_fields or [])
        protected_fields.update(
            field_name
            for field_name, original_value in financial_before.items()
            if field_name in form.fields and form.cleaned_data.get(field_name) != original_value
        )
        profile.manual_financial_fields = sorted(protected_fields)
        if "vehicle_cost" in form.fields and form.cleaned_data.get("vehicle_cost") != financial_before.get("vehicle_cost"):
            profile.vehicle_cost_manual = True
        vehicle_secret = form.cleaned_data.get("vehicle_control_password")
        battery_secret = form.cleaned_data.get("battery_password")
        if vehicle_secret:
            profile.vehicle_control_password_encrypted = encrypt_secret(
                vehicle_secret
            )
        if battery_secret:
            profile.battery_password_encrypted = encrypt_secret(battery_secret)
        for flag, prefix in (("vehicle_control_confirmed", "vehicle_control"), ("fulfillment_confirmed", "fulfillment")):
            if flag not in form.fields or form.fields[flag].disabled:
                continue
            checked = bool(form.cleaned_data.get(flag))
            if checked and not getattr(profile, f"{prefix}_confirmed_at"):
                setattr(profile, f"{prefix}_confirmed_at", timezone.now())
                setattr(profile, f"{prefix}_confirmed_by", actor)
            elif not checked:
                setattr(profile, f"{prefix}_confirmed_at", None)
                setattr(profile, f"{prefix}_confirmed_by", "")
        profile.updated_by = actor
        profile.save()
        # 收款明細直接刪除（使用者 2026-10-21 T-47）：刪前留下內容快照寫入處理紀錄，刪除後無法復原。
        deleted_payments = [_payment_deletion_snapshot(row.instance) for row in (payment_formset.deleted_forms if payment_formset is not None else [])
                            if row.instance.pk]
        payments = payment_formset.save() if payment_formset is not None else []
        for snapshot in deleted_payments:
            OrderChange.objects.create(order=order, reason="刪除收款", actor_name=actor,
                                       changes={f"刪除收款：{snapshot['item_name']}": {"before": snapshot["text"], "after": "已刪除"}})
            OrderEvent.objects.create(order=order, event_type="payment_deleted", actor_name=actor,
                                      description=f"刪除收款：{snapshot['text']}")
        deposit = next((payment for payment in payments if payment.system_key == "deposit"), None)
        # 取消流程中退款依帳本結算，訂金應收不再回寫訂單約定訂金。
        if deposit and deposit.expected_amount != order.deposit_amount and not order.is_cancelled_sale:
            order.actual_balance += order.deposit_amount - deposit.expected_amount
            order.deposit_amount = deposit.expected_amount
            if deposit.received_on:
                order.deposit_date = deposit.received_on
            order.calculated_balance = order.calculate_balance()
            order.save(update_fields=["deposit_amount", "deposit_date", "actual_balance", "calculated_balance", "updated_at"])
            sync_order_operations(order.pk, update_receivables=True)
        for previous_proof in (previous_payment_proofs if payment_formset is not None else []):
            _schedule_model_file_cleanup(
                PaymentRecord,
                "proof",
                previous_proof,
            )
        now = timezone.now()
        for payment in payments:
            if payment.confirmed and not payment.confirmed_at:
                payment.confirmed_at = now
                payment.confirmed_by = actor
                payment.save(
                    update_fields=[
                        "confirmed_at", "confirmed_by", "updated_at"
                    ]
                )
            elif not payment.confirmed and (payment.confirmed_at or payment.confirmed_by):
                payment.confirmed_at = None
                payment.confirmed_by = ""
                payment.save(update_fields=["confirmed_at", "confirmed_by", "updated_at"])
        plate_income_changed = any(
            name in form.fields and form.cleaned_data.get(name) != financial_before.get(name)
            for name in PLATE_INCOME_FIELDS
        )
        # 改了支出（例如請代辦人員領牌的選號支出）時，跟著支出的收入與代辦費收入要重算。
        # 分期客戶應收依牌險收入計算，收入這次有改才連已收款的應收一起改（人工調整過的應收不動）。
        sync_order_operations(
            order.pk,
            update_receivables=plate_income_changed and order.payment_type == SalesOrder.PaymentType.INSTALLMENT,
        )
        from sales.services.operations_sync import sync_payment_financials
        from sales.services.payment_summary import disbursement_receipts
        adoptable = {payment.pk for payment in disbursement_receipts(order, PaymentRecord.objects.filter(order=order))}
        adopted = next((payment for payment in payments if payment.pk in adoptable), None)
        sync_payment_financials(order.pk, adopt_payment_id=adopted.pk if adopted else None)
        profile.refresh_from_db()
        if form.cleaned_data.get("confirm_legacy_finance"):
            profile.legacy_finance_reconciliation = {
                **profile.legacy_finance_reconciliation, "status": "reviewed",
                "reviewed_by": actor, "reviewed_at": timezone.now().isoformat(),
                "review_reason": note_or_summary(form.cleaned_data.get("change_reason"), "人工確認歷史收支", 250),
                "reviewed_profit": str(profile.net_profit),
            }
            profile.save(update_fields=["legacy_finance_reconciliation", "updated_at"])
        after = _operations_snapshot(profile)
        changes = {
            key: {"before": before.get(key, ""), "after": value}
            for key, value in after.items()
            if before.get(key, "") != value
        }
        OrderChange.objects.create(
            order=order,
            reason=(note_or_summary(form.cleaned_data.get("change_reason"), "人工確認歷史收支")
                    if form.cleaned_data.get("confirm_legacy_finance") else "更新營運與對帳資料"),
            changes=changes,
            actor_name=actor,
        )
        OrderEvent.objects.create(
            order=order,
            event_type="operations_updated",
            description=f"更新營運與對帳資料（{len(changes)} 個欄位）",
            actor_name=actor,
        )
        if payment_formset is not None:
            _record_duplicate_acknowledgements(order, payment_formset.forms, user)
        _record_settlement_gap(order, gap_before, user)
    return profile


# ---------------------------------------------------------------- 汰舊補助資料（subsidy_data_update）

@dataclass
class SubsidyBaseline:
    before: dict
    balance_was_automatic: bool
    previous_actual_balance: object


def subsidy_baseline(order):
    """表單驗證前記下的原值。"""
    before = _order_snapshot(order)
    balance_was_automatic = order.actual_balance == order.calculated_balance
    previous_actual_balance = order.actual_balance
    return SubsidyBaseline(before=before, balance_was_automatic=balance_was_automatic,
                           previous_actual_balance=previous_actual_balance)


def save_subsidy_data(order, form, item_formset, baseline, *, items_submitted, user, reason="修改補助資料"):
    """`SubsidyDataForm`（與補助項目明細，若有送出）驗證通過後存檔；回傳存好的訂單。"""
    actor = _editing_name(user)
    before = baseline.before
    balance_was_automatic = baseline.balance_was_automatic
    previous_actual_balance = baseline.previous_actual_balance
    order = form.save(commit=False)
    order.revision += 1
    order.calculated_balance = order.calculate_balance()
    if balance_was_automatic:
        order.actual_balance = order.calculated_balance
    else:
        order.actual_balance = previous_actual_balance
        if order.actual_balance != order.calculated_balance:
            order.balance_adjustment_reason = balance_summary("修改補助資料")
    order.save()
    if items_submitted:
        item_formset.instance = order
        item_formset.save()
        # 有沒有汰舊由補助項目推導（使用者 2026-10-22 T-81 方案 A）。
        from sales.services.subsidy_programs import sync_trade_in_from_subsidies
        sync_trade_in_from_subsidies(order)
    profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
    profile.subsidy_amount = order.subsidy_total
    profile.subsidy_applied_on = order.subsidy_last_applied_on
    profile.updated_by = actor
    profile.save(
        update_fields=["subsidy_amount", "subsidy_applied_on", "updated_by", "updated_at"]
    )

    after = _order_snapshot(order)
    changes = _snapshot_changes(before, after)
    OrderChange.objects.create(
        order=order,
        reason=reason,
        changes=changes,
        actor_name=actor,
    )
    OrderEvent.objects.create(
        order=order,
        event_type="subsidy_data_updated",
        description=f"修改補助資料（{len(changes)} 個項目）",
        actor_name=actor,
    )
    return order
