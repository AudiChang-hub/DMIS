from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sales.access.services import AccessPolicy
from sales.models import OrderCustomerAccessGrant, OrderEvent
from sales.permission_workspace import workspace_url
from sales.services.order_customer_access import customer_orders, set_customer_access
from sales.tests import test_customer_order_access as fixtures


class PermissionWorkspaceTests(TestCase):
    setUpTestData = classmethod(fixtures.CustomerOrderAccessTests.setUpTestData.__func__)
    make_order = fixtures.CustomerOrderAccessTests.make_order
    grant = fixtures.CustomerOrderAccessTests.grant

    def setUp(self):
        self.order = self.make_order(self.user)
        self.grant('order_documents', 'export')
        self.client.force_login(self.admin)

    def override(self, **changes):
        data = dict(actor=self.admin, order_id=self.order.pk, account_id=self.profile.pk,
                    expected_revision=0, expected_identity_epoch=self.profile.identity_epoch,
                    can_view=True, can_print=False, active=True, is_override=True, reason='測試明確權限')
        data.update(changes)
        return set_customer_access(**data)

    def test_base_permission_is_checked_on_initial_load(self):
        response = self.client.get(workspace_url(self.user.pk, 'orders', order=self.order.pk))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['effective_print'])
        self.assertTrue(response.context['form']['can_print'].value())
        self.assertEqual(response.context['form']['mode'].value(), 'inherit')
        self.assertFalse(OrderCustomerAccessGrant.objects.exists())

    def test_explicit_print_denial_wins_over_own_order(self):
        self.override()
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.assertFalse(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())
        self.assertFalse(AccessPolicy(self.user).route('contract_print', kwargs={'pk': self.order.pk}))
        self.client.force_login(self.user)
        from sales.services.order_intake import CUSTOMER_DOCUMENT_ROUTES
        for route in CUSTOMER_DOCUMENT_ROUTES:
            self.assertIn(self.client.get(reverse(route, args=[self.order.pk])).status_code, (403, 404))
        page = self.client.get(reverse('order_detail', args=[self.order.pk]))
        self.assertNotContains(page, reverse('contract_print', args=[self.order.pk]))

    def test_both_unchecked_is_a_valid_deny_not_a_revoke(self):
        self.override(can_view=False)
        self.assertFalse(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.assertFalse(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())

    def test_restore_inheritance_recovers_base_permission(self):
        row = self.override(can_view=False)
        self.override(expected_revision=row.revision, active=False, can_view=False)
        self.assertTrue(customer_orders(self.user).filter(pk=self.order.pk).exists())
        self.assertTrue(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())

    def test_legacy_grant_preserves_effective_print_until_explicitly_saved(self):
        self.override(is_override=False)
        self.assertTrue(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())
        page = self.client.get(workspace_url(self.user.pk, 'orders', order=self.order.pk))
        self.assertTrue(page.context['form']['can_print'].value())
        self.assertContains(page, '既有額外授權')

    def test_global_permission_off_cannot_be_overridden(self):
        self.grant('order_documents', 'export', False)
        with self.assertRaisesMessage(ValidationError, '帳號尚未開放客戶文件列印'):
            self.override(can_print=True)
        self.assertFalse(OrderCustomerAccessGrant.objects.exists())

    def test_stale_revision_and_identity_rejected(self):
        self.override()
        with self.assertRaises(ValidationError):
            self.override()
        self.profile.source = self.other_source
        self.profile.save()
        with self.assertRaises(ValidationError):
            self.override(expected_revision=1, expected_identity_epoch=0)

    def test_central_save_audits_and_loads_effective_result(self):
        url = workspace_url(self.user.pk, 'orders', order=self.order.pk)
        page = self.client.post(url, {'mode': 'custom', 'can_view': 'on', 'expected_revision': 0,
            'expected_identity_epoch': self.profile.identity_epoch, 'reason': '不允許這張列印'}, follow=True)
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context['effective_print'])
        self.assertFalse(page.context['form']['can_print'].value())
        self.assertEqual(OrderEvent.objects.filter(event_type='customer_access_updated').count(), 1)

    def test_all_tabs_render_for_internal_and_dealer(self):
        for user in (self.user, self.staff, self.admin):
            for tab in ('account', 'features', 'scope', 'orders'):
                with self.subTest(user=user.username, tab=tab):
                    response = self.client.get(workspace_url(user.pk, tab))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, '人員權限工作區')

    def test_non_admin_cannot_open_or_post_any_tab(self):
        for user in (self.user, self.staff):
            self.client.force_login(user)
            for tab in ('account', 'features', 'scope', 'orders'):
                url = workspace_url(self.user.pk, tab)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_old_entry_points_redirect_to_same_workspace(self):
        for route, tab in (('dealer_account_edit', 'account'), ('order_account_scope', 'scope'), ('access_edit', 'features')):
            self.assertRedirects(self.client.get(reverse(route, args=[self.user.pk])), workspace_url(self.user.pk, tab), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('order_customer_access', args=[self.order.pk]), {'account': self.profile.pk}),
                             workspace_url(self.user.pk, 'orders', order=self.order.pk), fetch_redirect_response=False)

    def test_dealer_account_tab_does_not_change_hidden_feature_fields(self):
        page = self.client.get(workspace_url(self.user.pk, 'account'))
        form = page.context['form']
        data = {'username': self.user.username, 'display_name': '新名稱', 'is_active': 'on',
                'expected_revision': self.profile.revision, 'can_adjust_pricing': 'on'}
        response = self.client.post(workspace_url(self.user.pk, 'account'), data)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, '新名稱')
        self.assertTrue(AccessPolicy(self.user).screen('order_documents', 'export'))
        self.assertFalse(AccessPolicy(self.user).screen('order_pricing', 'operate'))

    def test_dealer_features_tab_preserves_identity_and_scope(self):
        self.user.first_name = '測試'
        self.user.last_name = '人員'
        self.user.save()
        self.profile.order_scope = 'dealer'
        self.profile.save()
        response = self.client.post(workspace_url(self.user.pk, 'features'), {
            'expected_revision': self.profile.revision, 'can_print_documents': 'on', 'can_view_orders': 'on',
            'username': 'tampered', 'order_scope': 'all', 'is_active': ''})
        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.context else '')
        self.profile.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.profile.order_scope, 'dealer')
        self.assertEqual(self.user.username, 'dealer-a')
        self.assertEqual((self.user.first_name, self.user.last_name), ('測試', '人員'))
        self.assertTrue(self.user.is_active)

    def test_account_name_change_does_not_activate_legacy_grants(self):
        from sales.access.models import UserAccessState
        UserAccessState.objects.filter(user=self.user).update(configured=False)
        self.grant('order_pricing', 'operate')
        self.assertFalse(AccessPolicy(self.user).screen('order_pricing', 'operate'))
        response = self.client.post(workspace_url(self.user.pk, 'account'), {
            'username': self.user.username, 'display_name': '更名而已', 'is_active': 'on',
            'expected_revision': self.profile.revision})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AccessPolicy(self.user).screen('order_pricing', 'operate'))
        self.assertFalse(UserAccessState.objects.get(user=self.user).configured)

    def test_search_only_returns_matches(self):
        page = self.client.get(workspace_url(self.user.pk, 'orders', q=self.order.number))
        self.assertContains(page, self.order.number)
        self.assertEqual(page.context['page_obj'].paginator.count, 1)
        blank = self.client.get(workspace_url(self.user.pk, 'orders'))
        self.assertEqual(blank.context['page_obj'].paginator.count, 0)

    def test_internal_denial_applies_to_list_detail_and_print(self):
        from sales.models import OrderAccountProfile
        from sales.services.order_intake import scoped_orders
        order = self.make_order(self.staff)
        profile = OrderAccountProfile.objects.get(user=self.staff)
        self.override(order_id=order.pk, account_id=profile.pk, can_view=False)
        self.assertFalse(scoped_orders(self.staff).filter(pk=order.pk).exists())
        self.assertFalse(AccessPolicy(self.staff).route('contract_print', kwargs={'pk': order.pk}))
        self.client.force_login(self.staff)
        self.assertIn(self.client.get(reverse('order_detail', args=[order.pk])).status_code, (403, 404))

    def test_audit_failure_rolls_back_denial(self):
        from unittest.mock import patch
        with patch('sales.services.order_customer_access.OrderEvent.objects.create', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.override(can_view=False)
        self.assertTrue(customer_orders(self.user, printing=True).filter(pk=self.order.pk).exists())
        self.assertFalse(OrderCustomerAccessGrant.objects.exists())

    def test_inactive_account_and_other_account_remain_isolated(self):
        self.override(can_view=False)
        self.assertTrue(customer_orders(self.admin).filter(pk=self.order.pk).exists())
        from sales.models import OrderAccountProfile
        OrderAccountProfile.objects.create(user=self.peer, kind='dealer', source=self.source)
        self.assertFalse(customer_orders(self.peer).filter(pk=self.order.pk).exists())
        self.user.is_active = False
        self.user.save()
        self.assertFalse(customer_orders(self.user, printing=True).exists())
