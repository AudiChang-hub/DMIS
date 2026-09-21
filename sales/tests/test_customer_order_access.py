from importlib import import_module
from decimal import Decimal
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.services import AccessPolicy
from sales.dealer_account_views import DealerEditForm
from sales.forms import AccessoryLineForm
from sales.models import AccessoryLine, AccessoryProduct, OrderAccountProfile, OrderIntakeAttachment, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services.order_intake import scoped_orders


class CustomerOrderAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', password='testing-only-123')
        cls.user = User.objects.create_user('dealer-a')
        cls.peer = User.objects.create_user('dealer-peer')
        cls.staff = User.objects.create_user('own-staff')
        cls.source = SalesSource.objects.create(name='QA甲車行', source_type='dealer')
        cls.other_source = SalesSource.objects.create(name='QA乙車行', source_type='dealer')
        cls.profile = OrderAccountProfile.objects.create(user=cls.user, kind='dealer', source=cls.source)
        OrderAccountProfile.objects.create(user=cls.staff, order_scope='own')
        UserAccessState.objects.create(user=cls.user, configured=True)
        cls.model = VehicleModel.objects.create(brand='QA', name='測試車款', energy_type='gas')
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name='白')
        cls.product = AccessoryProduct.objects.create(name='測試踏板', sale_price=2100, labor_fee=100)

    def make_order(self, user, source=None):
        return SalesOrder.objects.create(submitted_by=user, source=source or self.source, source_type='dealer',
            owner_name='測試車主', owner_phone='0912345678', owner_address='測試地址', owner_id_number='A123456789', vehicle_model=self.model, color=self.color, vehicle_price=70000)

    def grant(self, key, action='operate', enabled=True):
        ScreenAccessGrant.objects.update_or_create(user=self.user, screen_key=key,
            defaults={'view': enabled, 'operate': enabled and action == 'operate', 'export': enabled and action == 'export'})

    def test_default_scope_is_owner_and_dealer_intersection(self):
        own = self.make_order(self.user)
        self.make_order(self.peer)
        self.make_order(None)
        self.make_order(self.user, self.other_source)
        self.assertEqual(list(scoped_orders(self.user)), [own])
        self.client.force_login(self.user)
        page = self.client.get(reverse('order_list'))
        self.assertContains(page, '我的訂單')
        self.assertEqual(page.context['page_obj'].paginator.count, 1)
        self.assertEqual(self.client.get(reverse('order_detail', args=[own.pk])).status_code, 200)

    def test_dealership_scope_is_explicit_and_never_companywide(self):
        own, peer = self.make_order(self.user), self.make_order(self.peer)
        self.make_order(self.user, self.other_source)
        self.profile.order_scope = 'dealer'
        self.profile.save()
        self.assertCountEqual(scoped_orders(self.user), [own, peer])
        self.profile.order_scope = 'all'
        with self.assertRaises(ValidationError):
            self.profile.full_clean()
        self.profile.save()  # Simulate an invalid write: runtime still fails closed.
        self.assertEqual(list(scoped_orders(self.user)), [own])

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

    def test_print_is_independent_from_query_and_cross_owner_is_denied(self):
        own, peer = self.make_order(self.user), self.make_order(self.peer)
        self.grant('order_documents', 'export')
        self.profile.can_view_orders = False
        self.profile.save()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('order_list')).status_code, 403)
        for route in ('contract_print', 'privacy_consent_print', 'order_documents_print'):
            with self.subTest(route=route):
                # Missing company header is handled only AFTER successful scope/print checks.
                self.assertEqual(self.client.get(reverse(route, args=[own.pk])).status_code, 409)
                self.assertEqual(self.client.get(reverse(route, args=[peer.pk])).status_code, 404)
        self.assertContains(self.client.get(reverse('order_submitted', args=[own.pk])), '列印全部客戶簽署文件')
        self.grant('order_documents', 'export', False)
        self.assertEqual(self.client.get(reverse('contract_print', args=[own.pk])).status_code, 403)

    def test_dealer_cannot_open_finance_subsidy_or_other_attachments(self):
        own, peer = self.make_order(self.user), self.make_order(self.peer)
        self.client.force_login(self.user)
        for route in ('order_operations', 'order_edit', 'subsidy_toggle', 'subsidy_data_update'):
            self.assertEqual(self.client.get(reverse(route, args=[own.pk])).status_code, 403)
        for route in ('order_detail', 'contract_print'):
            self.grant('order_documents', 'export')
            self.assertEqual(self.client.get(reverse(route, args=[peer.pk])).status_code, 404)
        document = OrderIntakeAttachment.objects.create(order=own, uploaded_by=self.user, kind='old_bankbook', checksum='qa', name='qa.pdf', file='qa.pdf')
        self.assertEqual(self.client.get(reverse('order_intake_attachment', args=[document.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse('order_detail', args=[own.pk])), 'qa.pdf')

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

    def test_migration_preserves_latest_dealer_flags_and_pricing(self):
        self.grant('order_pricing')
        self.grant('orders')
        before = dict(OrderAccountProfile.objects.filter(pk=self.profile.pk).values('kind', 'source_id', 'can_view_orders', 'can_submit_orders', 'can_browse_catalog').get())
        pricing = ScreenAccessGrant.objects.filter(user=self.user, screen_key='order_pricing').values('view', 'operate', 'export').get()
        import_module('sales.migrations.0149_order_scope_and_customer_permissions').preserve_permissions(apps, None)
        self.assertEqual(OrderAccountProfile.objects.filter(pk=self.profile.pk).values(*before).get(), before)
        self.assertEqual(ScreenAccessGrant.objects.filter(user=self.user, screen_key='order_pricing').values(*pricing).get(), pricing)
        self.assertTrue(AccessPolicy(self.user).screen('order_gift', 'operate'))
        self.assertTrue(AccessPolicy(self.user).screen('order_documents', 'export'))
        self.assertFalse(AccessPolicy(self.user).screen('order_finance'))
        self.profile.refresh_from_db()
        form = DealerEditForm(instance=self.user, profile=self.profile)
        self.assertTrue(form.fields['can_adjust_pricing'].initial)
        self.assertTrue(form.fields['can_gift_accessories'].initial)
        self.assertEqual(form.fields['order_scope'].initial, 'own')

    def test_scope_form_rejects_cross_dealer_and_stale_revision(self):
        self.client.force_login(self.admin)
        url = reverse('order_account_scope', args=[self.user.pk])
        data = {'kind': 'dealer', 'source': self.source.pk, 'order_scope': 'all', 'expected_revision': 0}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.order_scope, 'own')
        data['order_scope'] = 'dealer'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        data['order_scope'] = 'own'
        self.assertContains(self.client.post(url, data), '設定已被其他視窗更新')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.order_scope, 'dealer')

    def test_all_order_pk_routes_have_scope_or_admin_guard(self):
        from sales.urls import urlpatterns
        from sales.services.order_intake import ORDER_PK_ROUTES
        # 刪除/還原使用 all_objects 自行套範圍，開單公司僅 root。
        separately_guarded = {'order_delete', 'order_restore', 'order_print_company'}
        for pattern in urlpatterns:
            if str(pattern.pattern).startswith('orders/<int:pk>/'):
                self.assertIn(pattern.name, ORDER_PK_ROUTES | separately_guarded)

    def test_migration_preserves_legacy_dealer_print_without_enabling_stale_pricing(self):
        UserAccessState.objects.filter(user=self.user).delete()
        self.grant('order_pricing')  # 沒有 configured state 時此舊 grant 原本無效。
        self.assertFalse(AccessPolicy(self.user).screen('order_pricing', 'operate'))
        import_module('sales.migrations.0149_order_scope_and_customer_permissions').preserve_permissions(apps, None)
        self.assertTrue(AccessPolicy(self.user).route('contract_print'))
        self.assertFalse(AccessPolicy(self.user).screen('order_pricing', 'operate'))
        self.assertFalse(AccessPolicy(self.user).screen('order_gift', 'operate'))
        ScreenAccessGrant.objects.filter(user=self.user, screen_key='order_documents').delete()
        self.assertFalse(AccessPolicy(self.user).route('contract_print'))
