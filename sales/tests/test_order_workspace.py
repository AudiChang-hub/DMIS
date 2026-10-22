from datetime import date

from django.contrib.auth import get_user_model
from django.forms import BooleanField, FileField
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.forms import OrderOperationsForm, PaymentRecordFormSet, SubsidyDataForm, SubsidyItemFormSet
from sales.models import SalesOrder, VehicleModel, VehicleColor, SalesSource, OrderChange


def form_data(form):
    data = {}
    for field in form:
        if isinstance(field.field, FileField) or field.field.disabled:
            continue
        value = field.value()
        if isinstance(field.field, BooleanField):
            if value:
                data[field.html_name] = 'on'
        elif isinstance(value, (list, tuple)):  # 多選欄位（例如補助方案）
            data[field.html_name] = [str(item) for item in value]
        else:
            data[field.html_name] = '' if value is None else str(value)
    return data


def formset_data(formset):
    data = form_data(formset.management_form)
    for form in formset:
        data.update(form_data(form))
    return data


class OrderWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('admin', password='test-pass-123')
        cls.staff = get_user_model().objects.create_user('workspace-reader')
        UserAccessState.objects.create(user=cls.staff, configured=True)
        ScreenAccessGrant.objects.create(user=cls.staff, screen_key='orders', view=True)
        model = VehicleModel.objects.create(brand='QA', name='工作區車型', energy_type='gas')
        color = VehicleColor.objects.create(vehicle_model=model, name='白')
        source = SalesSource.objects.create(name='馭盛', source_type='store')
        cls.order = SalesOrder.objects.create(source_type='store', source=source, order_date=date(2026, 9, 18),
            owner_type='company', owner_name='測試公司', owner_id_number='83739807', owner_phone='0912345678',
            owner_address='測試地址', vehicle_model=model, color=color, vehicle_price=70000,
            actual_balance=70000, calculated_balance=70000, payment_type='cash', delivery_method='store_pickup')
        from sales.services.print_company import initialize_company
        initialize_company(cls.order, cls.admin)
        cls.order.save(update_fields=['print_company', 'print_company_snapshot'])

    def setUp(self):
        self.client.force_login(self.admin)

    def post(self, route, data):
        return self.client.post(reverse(route, args=[self.order.pk]), data, HTTP_X_ORDER_WORKSPACE='1')

    def operations_data(self):
        self.order.refresh_from_db()
        return {**form_data(OrderOperationsForm(instance=self.order.operations, prefix='operations')),
                **formset_data(PaymentRecordFormSet(instance=self.order, prefix='payments'))}

    def test_detail_has_three_tabs_and_finance_shows_profit_for_admin(self):
        response = self.client.get(reverse('order_detail', args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        for name in ('訂車與配件', '收入與支出', '補助', 'data-order-step-bar', 'data-workspace-save="operations"'):
            self.assertContains(response, name)
        self.assertContains(response, 'data-profit-value')  # 2026-10-15 起淨利不再需要解鎖
        self.assertNotContains(response, '<iframe')

    def test_edit_uses_same_workspace_and_keeps_distinct_forms(self):
        response = self.client.get(reverse('order_detail', args=[self.order.pk]), {"tab": "order"})
        self.assertEqual(response.status_code, 200)
        for kind in ('order', 'operations', 'subsidy'):
            self.assertContains(response, f'data-workspace-save="{kind}"')
        # 「新舊車主為同一人」只在有汰舊類補助時顯示（2026-10-22 T-80）。
        self.assertContains(response, 'id="tradein-card-title"')

    def test_reader_does_not_receive_financial_form_or_ajax_access(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('order_detail', args=[self.order.pk]))
        self.assertNotContains(response, 'name="operations-vehicle_cost"')
        self.assertNotContains(response, 'data-workspace-tab="finance"')
        self.assertEqual(self.post('order_operations', {}).status_code, 403)

    def test_ajax_finance_save_keeps_audit_and_returns_summary(self):
        data = self.operations_data()
        data['operations-shipping_expense'] = '800'
        response = self.post('order_operations', data)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.order.operations.refresh_from_db()
        self.assertEqual(self.order.operations.shipping_expense, 800)
        self.assertIn('data-profit-value', payload['summary_html'])  # 有淨利授權直接顯示
        self.assertNotIn('net_profit', payload['sync']['operations'])
        self.assertTrue(OrderChange.objects.filter(order=self.order).exists())

    def test_ajax_finance_stale_revision_is_rejected(self):
        data = self.operations_data()
        data['operations-financial_revision'] = 'stale'
        data['operations-shipping_expense'] = '800'
        response = self.post('order_operations', data)
        # 版本衝突不是欄位錯誤：回 409、只給「請重新整理」的說明，不叫人修正欄位（使用者 2026-10-22 T-92）。
        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error'], '這張訂單剛被系統或他人更新，請重新整理頁面後再修改。')
        self.assertEqual(payload['errors'], {})
        self.assertEqual(self.order.operations.shipping_expense, 0)

    def test_ajax_finance_field_error_keeps_field_list(self):
        data = self.operations_data()
        data['operations-shipping_expense'] = 'abc'
        response = self.post('order_operations', data)
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload['error'], '收支資料未儲存，請修正下列欄位。')
        self.assertIn('operations-shipping_expense', payload['errors'])

    def test_ajax_finance_cannot_override_subsidy_item_total(self):
        data = self.operations_data()
        data['operations-subsidy_amount'] = '999999'
        response = self.post('order_operations', data)
        self.assertEqual(response.status_code, 200, response.content)
        self.order.operations.refresh_from_db()
        self.assertEqual(self.order.operations.subsidy_amount, 0)

    def test_subsidy_ajax_validation_preserves_data(self):
        data = {**form_data(SubsidyDataForm(instance=self.order)), '_order_revision': self.order.revision,
                **formset_data(SubsidyItemFormSet(instance=self.order, prefix='subsidy_items'))}
        # 用超過長度的舊車車牌觸發驗證錯誤，確認其他欄位也不被寫入。
        data.update(trade_in_plate='T' * 21, old_owner_name='不應寫入')
        response = self.post('subsidy_data_update', data)
        self.assertEqual(response.status_code, 400)
        self.assertIn('trade_in_plate', response.json()['errors'])
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.old_owner_name, '不應寫入')

    def test_subsidy_ajax_save_and_stale_revision(self):
        data = {**form_data(SubsidyDataForm(instance=self.order)), '_order_revision': self.order.revision,
                **formset_data(SubsidyItemFormSet(instance=self.order, prefix='subsidy_items'))}
        data.update(change_reason='補正合成資料', trade_in_plate='TEST123')
        response = self.post('subsidy_data_update', data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(self.post('subsidy_data_update', data).status_code, 409)

    def test_order_ajax_save_and_stale_revision(self):
        response = self.client.get(reverse('order_detail', args=[self.order.pk]), {"tab": "order"})
        data = {**form_data(response.context['form']), **formset_data(response.context['formset']),
                **formset_data(response.context['fee_formset']), '_order_revision': self.order.revision, '_workspace':'1'}
        data.update(change_reason='工作區驗收', note='平順切換', id_verified='on')
        response = self.post('order_edit', data)
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.note, '平順切換')
        self.assertEqual(self.post('order_edit', data).status_code, 409)
