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
        'profile': profile,
        'operations_form': operations_form,
        'payment_formset': PaymentRecordFormSet(instance=order, prefix='payments'),
        'manual_financial_fields': profile.manual_financial_fields or [],
        'is_electric': order.vehicle_model.energy_type != 'gas',
        'discount_request_form': DiscountRequestForm(initial={'amount': order.discount_requested_amount or None, 'reason': order.discount_reason}),
        'discount_decision_form': DiscountDecisionForm(initial={'decision': 'approve'}),
    }


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
    return JsonResponse({
        'ok': True, 'message': '已儲存，修改紀錄已保留。', 'revision': order.revision,
        'financial_revision': profile.updated_at.isoformat() if profile else None,
        'values': values,
        'sync': sync,
        'summary_html': render_to_string('sales/_workspace_finance_summary.html', {**context, 'order': order}, request=request) if profile else '',
    })
