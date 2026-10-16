"""店內人員的訂單資料範圍（本人／全公司）與獨立的贈送、訂價、列印權限（1.84.0 起只有店內人員）。"""
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.services import AccessPolicy
from sales.forms import AccessoryLineForm
from sales.models import AccessoryLine, AccessoryProduct, OrderAccountProfile, OrderIntakeAttachment, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services.order_intake import scoped_orders


class CustomerOrderAccessTests(TestCase):
    """其他測試模組共用 setUpTestData／make_order／grant；self.user 是只能看本人訂單的店內人員。"""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', password='testing-only-123')
        cls.user = User.objects.create_user('clerk-a')
        cls.peer = User.objects.create_user('clerk-peer')
        cls.staff = User.objects.create_user('own-staff')
        cls.source = SalesSource.objects.create(name='QA甲店', source_type='store')
        cls.other_source = SalesSource.objects.create(name='QA乙店', source_type='store')
        cls.profile = OrderAccountProfile.objects.create(user=cls.user, order_scope='own', source=cls.source)
        OrderAccountProfile.objects.create(user=cls.staff, order_scope='own')
        UserAccessState.objects.create(user=cls.user, configured=True)
        ScreenAccessGrant.objects.create(user=cls.user, screen_key='orders', view=True, operate=True)
        cls.model = VehicleModel.objects.create(brand='QA', name='測試車款', energy_type='gas')
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name='白')
        cls.product = AccessoryProduct.objects.create(name='測試踏板', sale_price=2100, labor_fee=100)

    def make_order(self, user, source=None):
        return SalesOrder.objects.create(submitted_by=user, source=source or self.source, source_type='store',
            owner_name='測試車主', owner_phone='0912345678', owner_address='測試地址', owner_id_number='A123456789', vehicle_model=self.model, color=self.color, vehicle_price=70000)

    def grant(self, key, action='operate', enabled=True):
        ScreenAccessGrant.objects.update_or_create(user=self.user, screen_key=key,
            defaults={'view': enabled, 'operate': enabled and action == 'operate', 'export': enabled and action == 'export'})

    def test_own_scope_is_only_orders_created_by_the_account(self):
        own = self.make_order(self.user)
        own_other_store = self.make_order(self.user, self.other_source)
        peer = self.make_order(self.peer)
        self.make_order(None)
        self.assertCountEqual(scoped_orders(self.user), [own, own_other_store])
        self.client.force_login(self.user)
        page = self.client.get(reverse('order_list'), {'tab': 'all'})
        self.assertEqual(page.context['page_obj'].paginator.count, 2)
        self.assertEqual(self.client.get(reverse('order_detail', args=[own.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('order_detail', args=[peer.pk])).status_code, 404)

    def test_all_scope_sees_company_orders_and_unknown_scope_is_rejected(self):
        own, peer, legacy = self.make_order(self.user), self.make_order(self.peer), self.make_order(None)
        self.profile.order_scope = 'all'
        self.profile.save()
        self.assertCountEqual(scoped_orders(self.user), [own, peer, legacy])
        self.profile.order_scope = 'dealer'
        with self.assertRaises(ValidationError):
            self.profile.full_clean()

    def test_internal_own_scope_and_admin_all(self):
        own, other = self.make_order(self.staff), self.make_order(self.user)
        legacy = self.make_order(None)
        self.assertEqual(list(scoped_orders(self.staff)), [own])
        self.assertCountEqual(scoped_orders(self.admin), [own, other, legacy])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('order_detail', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('customer_detail', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('customer_list')).context['page_obj'].paginator.count, 1)
        self.assertEqual(self.client.get(reverse('order_list')).context['page_obj'].paginator.count, 1)

    def test_lookup_keeps_format_error_and_rejects_foreign_order(self):
        other = self.make_order(self.user)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('installment_plan_options'), {'order_id': 'bad'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], '訂單編號格式錯誤。')
        for route in ('installment_plan_options', 'vehicle_price_options'):
            self.assertEqual(self.client.get(reverse(route), {'order_id': other.pk}).status_code, 404)
        UserAccessState.objects.create(user=self.staff, configured=True)
        self.assertEqual(self.client.get(reverse('installment_plan_options'), {'order_id': 'bad'}).status_code, 403)

    def test_print_is_independent_from_query_and_cross_owner_is_denied(self):
        own, peer = self.make_order(self.user), self.make_order(self.peer)
        self.grant('order_documents', 'export')
        self.grant('orders', enabled=False)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('order_list')).status_code, 403)
        for route in ('contract_print', 'privacy_consent_print', 'order_documents_print'):
            with self.subTest(route=route):
                # 範圍與列印權限通過後才處理開單公司；未設定時用馭盛（1.73.1）。
                self.assertEqual(self.client.get(reverse(route, args=[own.pk])).status_code, 200)
                self.assertIn(self.client.get(reverse(route, args=[peer.pk])).status_code, (403, 404))
        self.grant('order_documents', 'export', False)
        self.assertEqual(self.client.get(reverse('contract_print', args=[own.pk])).status_code, 403)

    def test_restricted_staff_cannot_open_finance_subsidy_or_other_attachments(self):
        own, peer = self.make_order(self.user), self.make_order(self.peer)
        self.client.force_login(self.user)
        for route in ('order_operations', 'subsidy_toggle', 'subsidy_data_update'):
            self.assertEqual(self.client.get(reverse(route, args=[own.pk])).status_code, 403, route)
        self.grant('order_documents', 'export')
        for route in ('order_detail', 'order_edit', 'contract_print'):
            self.assertIn(self.client.get(reverse(route, args=[peer.pk])).status_code, (403, 404), route)
        document = OrderIntakeAttachment.objects.create(order=peer, uploaded_by=self.peer, kind='old_bankbook', checksum='qa', name='qa.pdf', file='qa.pdf')
        self.assertEqual(self.client.get(reverse('order_intake_attachment', args=[document.pk])).status_code, 404)

    def test_gift_and_price_are_independent(self):
        self.grant('order_gift')
        self.assertTrue(AccessPolicy(self.user).screen('order_gift', 'operate'))
        self.assertFalse(AccessPolicy(self.user).screen('order_pricing', 'operate'))
        self.grant('order_gift', enabled=False)
        self.grant('order_pricing')
        self.assertFalse(AccessPolicy(self.user).screen('order_gift', 'operate'))
        self.assertTrue(AccessPolicy(self.user).screen('order_pricing', 'operate'))

    def accessory_form(self, *, gift=True, allowed=True, instance=None, quantity=1):
        return AccessoryLineForm(data={'accessory_product': self.product.pk, 'quantity': quantity,
            'line_type': 'gift' if gift else 'purchase', 'amount': '999', 'labor_fee': '999'},
            instance=instance, allow_manual=False, purchase_only=not allowed)

    def test_gift_is_zero_and_unauthorized_post_is_rejected(self):
        form = self.accessory_form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['amount'], Decimal('0'))
        self.assertEqual(form.cleaned_data['labor_fee'], Decimal('0'))
        self.assertFalse(self.accessory_form(allowed=False).is_valid())
        normal = self.accessory_form(gift=False, allowed=False)
        self.assertTrue(normal.is_valid(), normal.errors)
        self.assertEqual(normal.cleaned_data['amount'], self.product.sale_price)

    def test_existing_gift_survives_revocation_but_cannot_be_increased(self):
        order = self.make_order(self.user)
        line = AccessoryLine.objects.create(order=order, accessory_product=self.product, name=self.product.name,
            quantity=1, line_type='gift', amount=0, labor_fee=0)
        form = self.accessory_form(allowed=False, instance=line)
        self.assertTrue(form.is_valid(), form.errors)
        line.refresh_from_db()
        self.assertFalse(self.accessory_form(allowed=False, instance=line, quantity=2).is_valid())

    def test_scope_form_offers_only_own_and_all_without_creating_profile(self):
        account = get_user_model().objects.create_user('scope-copy-internal')
        self.client.force_login(self.admin)
        page = self.client.get(reverse('order_account_scope', args=[account.pk]), follow=True)
        self.assertContains(page, '<option value="all" selected>全公司訂單</option>', html=True)
        self.assertEqual([value for value, _ in page.context['form'].fields['order_scope'].choices], ['own', 'all'])
        self.assertFalse(OrderAccountProfile.objects.filter(user=account).exists())
        self.assertEqual(page.context['form']['order_scope'].value(), 'all')

    def test_scope_form_rejects_unknown_scope_and_stale_revision(self):
        self.client.force_login(self.admin)
        url = reverse('order_account_scope', args=[self.user.pk])
        data = {'source': self.source.pk, 'order_scope': 'dealer', 'expected_revision': 0}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.order_scope, 'own')
        data['order_scope'] = 'all'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        data['order_scope'] = 'own'
        self.assertContains(self.client.post(url, data), '設定已被其他視窗更新')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.order_scope, 'all')

    def test_scope_wording_release_is_only_visible_to_admin(self):
        from sales.services.audience_content import release_context
        admin_history = release_context(AccessPolicy(self.admin))['release_history']
        staff_history = release_context(AccessPolicy(self.user))['release_history']
        self.assertIn('1.16.2', [item['version'] for item in admin_history])
        self.assertNotIn('1.16.2', [item['version'] for item in staff_history])

    def test_all_order_pk_routes_have_scope_or_admin_guard(self):
        from sales.urls import urlpatterns
        from sales.services.order_intake import ORDER_PK_ROUTES
        # 刪除/還原使用 all_objects 自行套範圍；單筆權限入口僅 root。
        separately_guarded = {'order_delete', 'order_restore', 'order_customer_access'}
        for pattern in urlpatterns:
            if str(pattern.pattern).startswith('orders/<int:pk>/'):
                self.assertIn(pattern.name, ORDER_PK_ROUTES | separately_guarded)
