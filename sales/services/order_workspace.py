"""訂單工作區共用呈現；不新增第二份帳務，也不改既有計算。"""
from django.http import JsonResponse
from django.template.loader import render_to_string

from sales.access.services import policy_for
from sales.forms import OrderOperationsForm, PaymentRecordFormSet, DiscountRequestForm, DiscountDecisionForm, OrderEditForm, SubsidyDataForm
from sales.models import OrderOperationsProfile
from sales.services.order_intake import can_edit_finance
from sales.services.payment_summary import payment_summary


def is_workspace_save(request):
    return request.headers.get('X-Order-Workspace') == '1'


def finance_allowed(request):
    policy = policy_for(request)
    return policy.screen('order_finance') and policy.route('order_operations') and not policy.dealer


def mask_account(account):
    """帳號只露出末四碼；前面固定四個圓點，不洩漏帳號長度。"""
    digits = str(account or "").strip()
    if not digits:
        return ""
    return "●●●●" + digits[-4:] if len(digits) > 4 else "●●●●"


def payout_summary_context(request, order):
    """沒有財務授權、但可操作訂單作業的人員，在補助步驟唯讀查看撥款銀行與匯款帳戶（1.62.4 起完整顯示，使用者 2026-10-10）。"""
    policy = policy_for(request)
    if finance_allowed(request) or policy.dealer or not policy.screen('work', 'operate'):
        return {}
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    account = profile.remittance_account if profile else ''
    return {'payout_summary': {
        'bank_name': profile.bank_name if profile else '',
        'account': account,
        'account_masked': mask_account(account),
        'has_account': bool(account),
    }}


def payment_ledger_context(order, summary=None):
    """帳本調整紀錄與沖銷／退還溢收入口；已取消訂單只保留唯讀紀錄。"""
    from sales.forms import OverpaymentRefundForm, PaymentReversalForm
    from sales.models import PaymentRecord
    from sales.services.payment_ledger import settlement_gap

    summary = summary or payment_summary(order)
    active = not order.is_cancelled_sale
    reversal_form = PaymentReversalForm(order) if not order.is_settled_closed else None
    refund_form = OverpaymentRefundForm(order, summary) if active else None
    return {
        'ledger_adjustments': list(order.payment_records.exclude(entry_type=PaymentRecord.EntryType.RECEIPT).select_related('reverses').order_by('pk')),
        'payment_reversal_form': reversal_form if reversal_form and reversal_form.has_choices else None,
        'overpayment_refund_form': refund_form if refund_form and refund_form.has_overpayment else None,
        'settlement_gap': settlement_gap(order, summary),
        'payments_read_only': order.is_settled_closed,
    }


def payment_formset_for(order, data=None, files=None):
    return PaymentRecordFormSet(
        data, files, instance=order, prefix='payments',
        form_kwargs={'read_only': order.is_settled_closed},
    )


def finance_context(request, order):
    if not finance_allowed(request):
        return {}
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if profile is None:
        return {}
    operations_form = OrderOperationsForm(instance=profile, prefix='operations')
    for name in ('subsidy_amount', 'subsidy_applied_on'):
        operations_form.fields[name].disabled = True
    # 補助追蹤與車控贈品在各自步驟以獨立表單送出；auto_id 區隔避免同頁欄位 id 重複。
    subsidy_form = OrderOperationsForm(instance=profile, prefix='operations', section='subsidy', auto_id='ops_subsidy_%s')
    for name in ('subsidy_amount', 'subsidy_applied_on'):
        subsidy_form.fields[name].disabled = True
    fulfillment_form = OrderOperationsForm(instance=profile, prefix='operations', section='fulfillment', auto_id='ops_fulfillment_%s')
    summary = payment_summary(order)
    return {
        **payment_ledger_context(order, summary),
        **finance_overview_context(operations_form, profile, order),
        'workspace_finance': True,
        'workspace_finance_editable': can_edit_finance(request.user) and policy_for(request).route('order_operations', 'POST'),
        'workspace_discount_editable': can_edit_finance(request.user) and policy_for(request).route('order_discount_decide', 'POST'),
        'profile': profile,
        'operations_form': operations_form,
        'operations_subsidy_form': subsidy_form,
        'operations_fulfillment_form': fulfillment_form,
        'payment_formset': payment_formset_for(order),
        'receipt_summary': summary,
        'manual_financial_fields': profile.manual_financial_fields or [],
        'is_electric': order.vehicle_model.energy_type != 'gas',
        'discount_request_form': DiscountRequestForm(initial={'amount': order.discount_requested_amount or None, 'reason': order.discount_reason}),
        'discount_decision_form': DiscountDecisionForm(initial={'decision': 'approve'}),
    }


def finance_overview_context(form, profile, order):
    """收入／支出兩欄的分組、合計與車行結算；只呈現，不寫入。"""
    from sales.services.dealer_settlement import dealer_settlement
    from sales.services.finance_ledger import finance_ledger, finance_totals

    plate_variance = None
    calculated = order.registration_calculated_total
    if calculated and order.plate_insurance_fee != calculated:
        plate_variance = {
            'calculated': calculated,
            'actual': order.plate_insurance_fee,
            'difference': order.plate_insurance_fee - calculated,
            'difference_abs': abs(order.plate_insurance_fee - calculated),
            'confirmed': bool(
                order.registration_fee_variance_confirmed_at
                and order.registration_fee_variance_confirmed_calculated_total == calculated
                and order.registration_fee_variance_confirmed_actual_total == order.plate_insurance_fee
            ),
        }
    return {
        'finance_ledger': finance_ledger(form, profile),
        'finance_totals': finance_totals(profile),
        'dealer_settlement': dealer_settlement(order, profile),
        'plate_variance': plate_variance,
    }


def apply_inline_discount(request, order, form):
    """已授權人員在同頁直接核定，保留樂觀鎖與前後稽核。"""
    from django.core.exceptions import PermissionDenied
    from sales.models import OrderChange, OrderEvent
    from sales.services.operations_sync import sync_order_operations
    if not can_edit_finance(request.user) or not policy_for(request).route('order_discount_decide', 'POST'):
        raise PermissionDenied
    if str(order.revision) != request.POST.get('_order_revision'):
        return save_error('訂單已更新，請重新載入再調整折扣。', status=409)
    if not order.is_editable:
        return save_error('此訂單狀態不可調整折扣（已交付、完成或進入取消流程）。')
    if not form.is_valid():
        return save_error('折扣未儲存，請修正欄位。', forms=(form,))
    from sales.services.order_discount import approve_discount_now
    before = order.approved_discount_amount
    approve_discount_now(order, amount=form.cleaned_data['amount'], reason=form.cleaned_data['reason'],
                         actor_name=request.user.get_username(), note='金額收支頁直接核定')
    order.save()
    sync_order_operations(order.pk, update_receivables=True)
    OrderChange.objects.create(order=order, actor_name=request.user.get_username(), reason=order.discount_reason,
        changes={'approved_discount_amount': {'before': str(before), 'after': str(order.approved_discount_amount)}})
    OrderEvent.objects.create(order=order, actor_name=request.user.get_username(), event_type='discount_decided', description='在金額收支頁核定折扣，未變更分期撥款、成本與佣金。')
    return saved(request, order)


def save_error(message, *, status=400, forms=()):
    errors = {}
    for form in forms:
        for name, values in form.errors.items():
            errors[form.add_prefix(name)] = [str(value) for value in values]
    return JsonResponse({'ok': False, 'error': message, 'errors': errors}, status=status)


def saved(request, order, *, form=None, formsets=()):
    """只回傳已保存資料；維持欄位 index，讓新增的明細可再次編輯。"""
    order.refresh_from_db()
    values = {}
    for formset in formsets:
        for row in formset.forms:
            if row.instance.pk and not row.cleaned_data.get('DELETE'):
                values[row.add_prefix('id')] = str(row.instance.pk)
    context = finance_context(request, order)
    profile = context.get('profile')
    def field_values(current):
        return {field.html_name: field.value() for field in current
                if getattr(field.field.widget, 'input_type', '') not in ('file', 'password')}
    sync = {'subsidy': field_values(SubsidyDataForm(instance=order))}
    if policy_for(request).route('order_edit', kwargs={'pk': order.pk}) and can_edit_finance(request.user):
        sync['order'] = field_values(OrderEditForm(instance=order))
    if profile:
        sync['operations'] = field_values(context['operations_form'])
    payment_values = {}
    if profile:
        from sales.forms import PaymentRecordForm
        for payment in order.payment_records.filter(entry_type='receipt'):
            payment_values[str(payment.pk)] = field_values(PaymentRecordForm(instance=payment))
    delivery_blockers = [] if order.is_delivered else order.delivery_blockers()
    locked_payments = [str(pk) for pk in order.payment_records.filter(entry_type='receipt', confirmed=True).values_list('pk', flat=True)] if profile else []
    return JsonResponse({
        'ok': True, 'message': '已儲存，修改紀錄已保留。', 'revision': order.revision,
        'financial_revision': profile.updated_at.isoformat() if profile else None,
        'values': values,
        'sync': sync,
        'payment_values': payment_values,
        'locked_payments': locked_payments,
        'customer_balance_due': str(order.customer_balance_due) if profile else None,
        'discount': {'before': str(order.pre_discount_total), 'amount': str(order.approved_discount_amount), 'after': str(order.discounted_total)},
        'delivery_ready': not delivery_blockers,
        'delivery_blocker': delivery_blockers[0] if delivery_blockers else '',
        'receipt_summary': {key: str(value) for key, value in payment_summary(order).items()},
        'summary_html': render_to_string('sales/_workspace_finance_summary.html', {**context, 'order': order}, request=request) if profile else '',
        'subsidy_summary_html': render_to_string('sales/_subsidy_agency_summary.html', {'order': order}, request=request) if profile else '',
    })
