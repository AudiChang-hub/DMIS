"""單筆訂單授權（OrderCustomerAccessGrant）：店內人員的額外查看／列印、撤銷與併發（1.84.0 起已無代開訂單）。"""
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from sales.models import OrderCustomerAccessGrant, OrderEvent, SalesOrder
from sales.services.order_customer_access import customer_orders, set_customer_access
from sales.services.order_intake import scoped_orders
from sales.tests import test_customer_order_access as access_fixtures


class CustomerGrantTests(TestCase):
    setUpTestData = classmethod(access_fixtures.CustomerOrderAccessTests.setUpTestData.__func__)
    make_order = access_fixtures.CustomerOrderAccessTests.make_order
    grant = access_fixtures.CustomerOrderAccessTests.grant

    def setUp(self):
        # 別人建立的訂單：不在 self.user（本人範圍）的一般資料範圍內。
        self.order = self.make_order(self.staff, self.other_source)

    def authorize(self, **changes):
        data = dict(actor=self.admin, order_id=self.order.pk, account_id=self.profile.pk, expected_revision=0,
                    expected_identity_epoch=self.profile.identity_epoch, can_view=True, can_print=False, active=True, reason='測試單筆授權')
        data.update(changes)
        return set_customer_access(**data)

    def test_shared_order_is_view_only_and_does_not_change_original_data(self):
        before = SalesOrder.objects.filter(pk=self.order.pk).values().get()
        self.authorize()
        self.assertFalse(scoped_orders(self.user).filter(pk=self.order.pk).exists())
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('order_detail', args=[self.order.pk])).status_code, 200)
        for name in ('order_edit', 'order_operations', 'subsidy_data_update', 'order_customer_access'):
            self.assertIn(self.client.get(reverse(name, args=[self.order.pk])).status_code, (403, 404), name)
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
        self.assertEqual(self.client.get(url).status_code, 200)  # 已過授權；未設定公司時用馭盛（1.73.1）。
        self.grant('order_documents', 'export', False)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_default_store_change_invalidates_grant_even_after_returning(self):
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
        self.profile.order_scope = 'all'
        self.profile.save(update_fields=['order_scope'])
        self.profile.order_scope = 'own'
        self.profile.save(update_fields=['order_scope'])
        self.assertEqual(self.profile.identity_epoch, 0)
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.grant('orders', enabled=False)
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

    def test_admin_ui_cannot_bypass_scope_and_restores_inheritance(self):
        self.client.force_login(self.admin)
        from sales.permission_workspace import workspace_url
        url = workspace_url(self.user.pk, 'orders', order=self.order.pk)
        self.assertContains(self.client.get(url), '儲存本筆權限')
        self.assertContains(self.client.get(url), '不會自動替你擴權')
        self.grant('order_documents', 'export')
        data = dict(expected_revision=0, expected_identity_epoch=0, can_view='on', can_print='on', reason='admin確認開放', mode='custom')
        self.assertContains(self.client.post(url, data), '內部人員請先調整訂單範圍')
        self.assertFalse(OrderCustomerAccessGrant.objects.exists())
        self.assertFalse(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.profile.order_scope = 'all'
        self.profile.save(update_fields=['order_scope'])
        data.update(can_view='', can_print='', reason='這筆不開放')
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertFalse(customer_orders(self.user).filter(pk=self.order.pk).exists())
        data.update(expected_revision=1, mode='inherit', reason='處理結束')
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())

    def test_disabled_user_cannot_use_grant(self):
        self.authorize(can_print=True)
        self.assertTrue(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertFalse(customer_orders(self.user).exists())
        self.assertFalse(customer_orders(self.user, printing=True).exists())


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
