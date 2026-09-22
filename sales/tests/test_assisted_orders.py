from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from sales.models import OrderCustomerAccessGrant, OrderEvent, PrintCompany, SalesOrder
from sales.services.order_customer_access import customer_orders, set_customer_access
from sales.services.order_intake import scoped_orders
from sales.tests import test_customer_order_access as access_fixtures
from sales.tests import test_order_intake as intake_fixtures


class CustomerGrantTests(TestCase):
    setUpTestData = classmethod(access_fixtures.CustomerOrderAccessTests.setUpTestData.__func__)
    make_order = access_fixtures.CustomerOrderAccessTests.make_order
    grant = access_fixtures.CustomerOrderAccessTests.grant

    def setUp(self):
        self.order = self.make_order(self.staff, self.other_source)

    def authorize(self, **changes):
        data = dict(actor=self.admin, order_id=self.order.pk, account_id=self.profile.pk, expected_revision=0,
                    expected_identity_epoch=self.profile.identity_epoch, can_view=True, can_print=False, active=True, reason='測試單筆授權')
        data.update(changes)
        return set_customer_access(**data)

    def test_shared_order_is_customer_only_and_does_not_change_original_data(self):
        before = SalesOrder.objects.filter(pk=self.order.pk).values().get()
        self.authorize()
        self.assertFalse(scoped_orders(self.user).filter(pk=self.order.pk).exists())
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('order_list')).context['page_obj'].paginator.count, 1)
        response = self.client.get(reverse('order_detail', args=[self.order.pk]))
        self.assertTemplateUsed(response, 'sales/dealer_order_detail.html')
        self.assertNotContains(response, '金額收支')
        for name in ('order_edit', 'order_operations', 'subsidy_data_update', 'order_customer_access'):
            self.assertEqual(self.client.get(reverse(name, args=[self.order.pk])).status_code, 403, name)
        self.assertEqual(SalesOrder.objects.filter(pk=self.order.pk).values().get(), before)
        self.assertEqual(OrderEvent.objects.filter(order=self.order, event_type='customer_access_updated').count(), 1)

    def test_view_print_and_global_permissions_are_independent(self):
        self.grant('order_documents', 'export')
        grant = self.authorize()
        self.client.force_login(self.user)
        url = reverse('order_documents_print', args=[self.order.pk])
        self.assertIn(self.client.get(url).status_code, (403, 404))
        self.authorize(expected_revision=grant.revision, can_view=False, can_print=True)
        self.assertEqual(self.client.get(reverse('order_list')).context['page_obj'].paginator.count, 0)
        self.assertEqual(self.client.get(reverse('order_detail', args=[self.order.pk])).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 409)  # 已過授權；此試作單未設定公司。
        self.grant('order_documents', 'export', False)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_transfer_invalidates_grant_even_after_returning_to_original_dealer(self):
        grant = self.authorize(can_print=True)
        self.profile.source = self.other_source
        self.profile.save(update_fields=['source'])
        self.assertFalse(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.profile.source = self.source
        self.profile.save(update_fields=['source'])
        self.assertFalse(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())
        self.authorize(expected_revision=grant.revision, expected_identity_epoch=self.profile.identity_epoch)
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())

    def test_routine_profile_edits_preserve_identity_and_grant(self):
        self.authorize()
        self.profile.can_submit_orders = False
        self.profile.save(update_fields=['can_submit_orders'])
        self.assertEqual(self.profile.identity_epoch, 0)
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.profile.can_view_orders = False
        self.profile.save(update_fields=['can_view_orders'])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('order_list')).status_code, 403)

    def test_stale_forms_and_unauthorized_changes_are_rejected(self):
        self.authorize()
        with self.assertRaises(ValidationError):
            self.authorize()
        with self.assertRaises(ValidationError):
            self.authorize(expected_revision=1, expected_identity_epoch=999)
        with self.assertRaises(PermissionDenied):
            self.authorize(actor=self.user, expected_revision=1)
        with self.assertRaises(ValidationError):
            self.authorize(expected_revision=1, reason=' ')

    def test_revoke_and_audit_failure_do_not_leave_access(self):
        with patch('sales.services.order_customer_access.OrderEvent.objects.create', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.authorize()
        self.assertFalse(OrderCustomerAccessGrant.objects.exists())
        grant = self.authorize(can_print=True)
        self.authorize(expected_revision=grant.revision, active=False)
        self.assertFalse(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.assertFalse(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())

    def test_admin_ui_and_revoke(self):
        self.client.force_login(self.admin)
        url = reverse('order_customer_access', args=[self.order.pk])
        self.assertContains(self.client.get(url + f'?account={self.profile.pk}'), '儲存授權')
        self.assertContains(self.client.get(url + f'?account={self.profile.pk}'), '本頁不會自動開啟帳號功能')
        self.assertFalse(OrderCustomerAccessGrant.objects.exists())
        data = dict(account=self.profile.pk, expected_revision=0, expected_identity_epoch=0, can_view='on', can_print='on', reason='admin確認交給車行', action='save')
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())
        data.update(expected_revision=1, action='revoke', reason='處理結束')
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertFalse(customer_orders(self.user).filter(pk=self.order.pk).exists())

    def test_disabled_user_or_source_cannot_use_grant(self):
        self.authorize(can_print=True)
        self.source.active = False
        self.source.save(update_fields=['active'])
        self.assertFalse(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.assertFalse(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())
        self.source.active = True
        self.source.save(update_fields=['active'])
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertFalse(customer_orders(self.user).exists())
        self.assertFalse(customer_orders(self.user, printing=True).exists())


class AssistedIntakeTests(TestCase):
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    setUp = intake_fixtures.OrderIntakeTests.setUp

    def company(self):
        return PrintCompany.objects.create(key=f'dealer:{self.dealer.pk}', source=self.dealer,
            legal_name='試作甲車行有限公司', tax_id='12345678', address='試作地址', phone='02-12345678')

    def submit_assisted(self, **changes):
        self.client.force_login(self.root)
        data = self.complete_data()
        data.update(source_type='dealer', source=self.dealer.pk, assisted_company_confirmed='on', assisted_company_revision=0,
                    id_front=self.image('front.png'), id_back=self.image('back.png'))
        data.update(changes)
        return self.client.post(reverse('order_start'), data)

    def test_assisted_order_company_and_dealer_print_before_acceptance(self):
        company = self.company()
        response = self.submit_assisted()
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.source_id, self.dealer.pk)
        self.assertEqual(order.submitted_by, self.root)
        self.assertEqual(order.status, 'intake_pending')
        self.assertIsNone(order.accepted_at)
        self.assertEqual(order.print_company_id, company.pk)
        self.assertEqual(order.print_company_snapshot['legal_name'], company.legal_name)
        self.profile.order_scope = 'dealer'
        self.profile.save()
        from sales.access.models import ScreenAccessGrant
        ScreenAccessGrant.objects.create(user=self.dealer_user, screen_key='order_documents', view=True, export=True)
        self.client.force_login(self.dealer_user)
        self.assertContains(self.client.get(reverse('order_list')), order.number)
        for name in ('contract_print', 'privacy_consent_print', 'order_documents_print'):
            response = self.client.get(reverse(name, args=[order.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')
            self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
        order.refresh_from_db()
        self.assertIsNone(order.accepted_at)
        self.assertEqual(order.status, 'intake_pending')

    def test_missing_confirmation_company_and_stale_revision_are_rejected(self):
        response = self.submit_assisted()
        self.assertIn('assisted_company_confirmed', response.context['form'].errors)
        self.assertFalse(SalesOrder.objects.exists())
        self.company()
        for changes in ({'assisted_company_confirmed': ''}, {'assisted_company_revision': 999}):
            response = self.submit_assisted(**changes)
            self.assertIn('assisted_company_confirmed', response.context['form'].errors)
            self.assertFalse(SalesOrder.objects.exists())

    def test_dealer_cannot_spoof_sales_source_or_print_company(self):
        company = self.company()
        self.client.force_login(self.dealer_user)
        data = self.complete_data()
        data.update(source_type='store', source=self.other_dealer.pk, print_company='home',
                    id_front=self.image('front.png'), id_back=self.image('back.png'))
        response = self.client.post(reverse('order_start'), data)
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.source_id, self.dealer.pk)
        self.assertEqual(order.print_company_id, company.pk)


class CustomerGrantConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_competing_grants_only_one_revision_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        access_fixtures.CustomerOrderAccessTests.setUpTestData.__func__(type(self))
        order = access_fixtures.CustomerOrderAccessTests.make_order(self, self.staff, self.other_source)
        barrier = Barrier(2)

        def save(reason):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                set_customer_access(actor=self.admin, order_id=order.pk, account_id=self.profile.pk,
                    expected_revision=0, expected_identity_epoch=0, can_view=True, can_print=True, active=True, reason=reason)
                return 'saved'
            except ValidationError:
                return 'stale'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['授權一', '授權二']))
        self.assertCountEqual(results, ['saved', 'stale'])
        self.assertEqual(OrderCustomerAccessGrant.objects.filter(order=order).count(), 1)
        self.assertEqual(OrderEvent.objects.filter(order=order, event_type='customer_access_updated').count(), 1)
