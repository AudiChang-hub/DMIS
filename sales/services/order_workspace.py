"""訂單工作區共用呈現；不新增第二份帳務，也不改既有計算。"""
from django.http import JsonResponse
from django.template.loader import render_to_string

from sales.access.services import policy_for
from sales.forms import OrderOperationsForm, PaymentRecordFormSet, DiscountRequestForm, DiscountDecisionForm, OrderEditForm, SubsidyDataForm
from sales.models import OrderOperationsProfile, SalesOrder
from sales.services.order_intake import can_edit_finance


def is_workspace_save(request):
    return request.headers.get('X-Order-Workspace') == '1'


def finance_allowed(request):
    policy = policy_for(request)
    return policy.screen('order_finance') and policy.route('order_operations') and not policy.dealer


def finance_context(request, order):
    if not finance_allowed(request):
        return {}
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if profile is None:
        return {}
    operations_form = OrderOperationsForm(instance=profile, prefix='operations')
    for name in ('subsidy_amount', 'subsidy_applied_on'):
        operations_form.fields[name].disabled = True
    return {
        'workspace_finance': True,
        'workspace_finance_editable': can_edit_finance(request.user) and policy_for(request).route('order_operations', 'POST'),
        'workspace_discount_editable': can_edit_finance(request.user) and policy_for(request).route('order_discount_decide', 'POST'),
        'profile': profile,
        'operations_form': operations_form,
        'payment_formset': PaymentRecordFormSet(instance=order, prefix='payments'),
        'manual_financial_fields': profile.manual_financial_fields or [],
        'is_electric': order.vehicle_model.energy_type != 'gas',
        'discount_request_form': DiscountRequestForm(initial={'amount': order.discount_requested_amount or None, 'reason': order.discount_reason}),
        'discount_decision_form': DiscountDecisionForm(initial={'decision': 'approve'}),
    }


def apply_inline_discount(request, order, form):
    """已授權人員在同頁直接核定，保留樂觀鎖與前後稽核。"""
    from django.core.exceptions import PermissionDenied
    from django.utils import timezone
    from sales.models import OrderChange, OrderEvent
    from sales.services.operations_sync import sync_order_operations
    if not can_edit_finance(request.user) or not policy_for(request).route('order_discount_decide', 'POST'):
        raise PermissionDenied
    if str(order.revision) != request.POST.get('_order_revision'):
        return save_error('訂單已更新，請重新載入再調整折扣。', status=409)
    if not order.is_editable:
        return save_error('此訂單狀態不可調整折扣。')
    if not form.is_valid():
        return save_error('折扣未儲存，請修正欄位。', forms=(form,))
    before = order.approved_discount_amount
    automatic = order.actual_balance in {order.calculated_balance, order.calculate_balance()}
    order.approved_discount_amount = form.cleaned_data['amount']
    order.discount_requested_amount = order.approved_discount_amount
    order.discount_basis_total = order.pre_discount_total
    order.discount_reason = form.cleaned_data['reason']
    order.discount_status = SalesOrder.DiscountStatus.APPROVED
    order.discount_requested_at = order.discount_decided_at = timezone.now()
    order.discount_requested_by = order.discount_decided_by = request.user.get_username()
    order.discount_decision_note = '金額收支頁直接核定'
    order.calculated_balance = order.calculate_balance()
    if automatic:
        order.actual_balance = order.calculated_balance
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
        for payment in order.payment_records.all():
            payment_values[str(payment.pk)] = field_values(PaymentRecordForm(instance=payment))
    return JsonResponse({
        'ok': True, 'message': '已儲存，修改紀錄已保留。', 'revision': order.revision,
        'financial_revision': profile.updated_at.isoformat() if profile else None,
        'values': values,
        'sync': sync,
        'payment_values': payment_values,
        'customer_balance_due': str(order.customer_balance_due) if profile else None,
        'discount': {'before': str(order.pre_discount_total), 'amount': str(order.approved_discount_amount), 'after': str(order.discounted_total)},
        'delivery_ready': bool(order.source_type == SalesOrder.SourceType.DEALER or any(p.system_key == 'balance' and p.is_settled for p in order.payment_records.all())),
        'summary_html': render_to_string('sales/_workspace_finance_summary.html', {**context, 'order': order}, request=request) if profile else '',
    })
