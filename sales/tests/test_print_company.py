from copy import deepcopy
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from pypdf import PdfReader

from sales.models import OrderAccountProfile, PrintCompany, PrintCompanyChange, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services.print_company import company_data, correct_order_company, initialize_company
from sales.services.order_contract_pdf import build_order_contract_pdf


class PrintCompanyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('admin', password='test-pass-123')
        cls.staff = get_user_model().objects.create_user('print-staff')
        cls.dealer = get_user_model().objects.create_user('dealer-print')
        cls.source = SalesSource.objects.create(name='測試甲車行', source_type='dealer')
        cls.other = SalesSource.objects.create(name='測試乙車行', source_type='dealer')
        cls.profile = OrderAccountProfile.objects.create(user=cls.dealer, kind='dealer', source=cls.source)
        cls.company = PrintCompany.objects.create(key=f'dealer:{cls.source.pk}', source=cls.source,
            legal_name='甲車業有限公司', tax_id='12345678', address='測試市測試路一號', phone='02-12345678')
        cls.home = PrintCompany.objects.get(key='home')
        cls.model = VehicleModel.objects.create(brand='QA', name='列印測試', energy_type='gas')
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name='白')

    def make_order(self, actor=None, **kwargs):
        order = SalesOrder(owner_name='文件測試', owner_phone='0912345678', owner_address='測試地址',
            owner_id_number='A123456789', vehicle_model=self.model, color=self.color, vehicle_price=70000,
            actual_balance=70000, **kwargs)
        if actor:
            order.submitted_by = actor
            initialize_company(order, actor)
        order.save()
        return order

    def setUp(self):
        self.client.force_login(self.admin)

    def test_dealer_and_internal_defaults_are_separate_from_commission_source(self):
        dealer_order = self.make_order(self.dealer, source=self.source, source_type='dealer')
        internal_order = self.make_order(self.admin, source=self.source, source_type='dealer')
        self.assertEqual(dealer_order.print_company, self.company)
        self.assertEqual(internal_order.print_company, self.home)

    def test_admin_reprint_and_profile_change_do_not_change_snapshot(self):
        order = self.make_order(self.dealer, source=self.source, source_type='dealer')
        before = deepcopy(order.print_company_snapshot)
        self.company.legal_name = '新版甲公司'
        self.company.save()
        self.profile.source = self.other
        self.profile.save()
        response = self.client.get(reverse('contract_print', args=[order.pk]))
        reader = PdfReader(BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(len(reader.pages), 2)
        self.assertEqual(reader.metadata.author, before['legal_name'])
        for page in reader.pages:
            self.assertIn(before['legal_name'], page.extract_text())
            self.assertNotIn('新版甲公司', page.extract_text())
        order.refresh_from_db()
        self.assertEqual(order.print_company_snapshot, before)

    def test_old_order_and_missing_dealer_configuration_never_fallback(self):
        self.profile.source = self.other
        self.profile.save()
        for order in [self.make_order(), self.make_order(self.dealer, source=self.other, source_type='dealer')]:
            for route in ['contract_print', 'privacy_consent_print', 'order_documents_print']:
                response = self.client.get(reverse(route, args=[order.pk]))
                self.assertEqual(response.status_code, 409)
                self.assertContains(response, '請先確認開單公司', status_code=409)
            order.refresh_from_db()
            self.assertEqual(order.print_company_snapshot, {})

    def test_dealer_can_print_own_but_not_other_order_or_manage_company(self):
        own = self.make_order(self.dealer, source=self.source, source_type='dealer')
        other = self.make_order(self.admin)
        self.client.force_login(self.dealer)
        self.assertEqual(self.client.get(reverse('contract_print', args=[own.pk])).status_code, 200)
        self.assertIn(self.client.get(reverse('contract_print', args=[other.pk])).status_code, [403, 404])
        for route, args in [('print_company_settings', []), ('dealer_print_company', [self.source.pk]), ('order_print_company', [own.pk])]:
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 403)
            self.assertEqual(self.client.post(reverse(route, args=args), {}).status_code, 403)
        self.profile.can_view_orders = False
        self.profile.save()
        self.assertEqual(self.client.get(reverse('contract_print', args=[own.pk])).status_code, 403)

    def test_non_admin_even_superuser_cannot_manage(self):
        self.staff.is_superuser = True
        self.staff.save()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('print_company_settings')).status_code, 403)
        with self.assertRaises(PermissionDenied):
            correct_order_company(user=self.staff, pk=999, company_id=self.company.pk, revision=0, reason='x', acknowledged=True)

    def test_company_settings_are_audited_and_old_order_unchanged(self):
        order = self.make_order(self.dealer)
        before = deepcopy(order.print_company_snapshot)
        url = reverse('dealer_print_company', args=[self.source.pk])
        response = self.client.post(url, {'legal_name':'新甲公司', 'tax_id':'23456789', 'address':'新地址',
            'phone':'02-22222222', 'expected_revision':self.company.revision, 'reason':'公司遷址'})
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.revision, 1)
        change = PrintCompanyChange.objects.get(company=self.company)
        self.assertEqual(change.before['legal_name'], before['legal_name'])
        self.assertEqual(change.after['address'], '新地址')
        order.refresh_from_db()
        self.assertEqual(order.print_company_snapshot, before)
        stale = self.client.post(url, {'legal_name':'過期內容', 'tax_id':'23456789', 'address':'舊地址',
            'phone':'02-22222222', 'expected_revision':0, 'reason':'過期'})
        self.assertContains(stale, '已被其他人修改')
        self.company.refresh_from_db()
        self.assertEqual(self.company.legal_name, '新甲公司')

    def test_get_does_not_create_company_and_invalid_data_rejected(self):
        url = reverse('dealer_print_company', args=[self.other.pk])
        count = PrintCompany.objects.count()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(PrintCompany.objects.count(), count)
        response = self.client.post(url, {'legal_name':'乙', 'tax_id':'abc', 'address':'地址', 'phone':'電話',
                                        'expected_revision':0, 'reason':'設定'})
        self.assertContains(response, '8 碼數字')
        self.assertEqual(PrintCompany.objects.count(), count)

    def test_correction_preserves_money_receipts_source_and_signed_document(self):
        order = self.make_order(self.admin, signed_contract='contracts/existing.pdf')
        money = (order.actual_balance, order.source_id, order.signed_contract.name)
        payments = list(order.payment_records.values())
        correct_order_company(user=self.admin, pk=order.pk, company_id=self.company.pk,
            revision=order.revision, reason='確認實際銷售方', acknowledged=True)
        order.refresh_from_db()
        self.assertEqual((order.actual_balance, order.source_id, order.signed_contract.name), money)
        self.assertEqual(list(order.payment_records.values()), payments)
        self.assertEqual(order.print_company, self.company)
        self.assertEqual(order.print_company_changes.get().reason, '確認實際銷售方')

    def test_correction_requires_reason_confirmation_and_current_revision(self):
        order = self.make_order()
        for reason, acknowledged, revision in [('', True, order.revision), ('原因', False, order.revision), ('原因', True, order.revision + 1)]:
            with self.assertRaises(ValidationError):
                correct_order_company(user=self.admin, pk=order.pk, company_id=self.company.pk,
                    revision=revision, reason=reason, acknowledged=acknowledged)
        self.assertFalse(order.print_company_changes.exists())

    def test_combined_documents_and_author_use_same_company(self):
        order = self.make_order(self.dealer, source=self.source, source_type='dealer')
        response = self.client.get(reverse('order_documents_print', args=[order.pk]))
        reader = PdfReader(BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(len(reader.pages), 3)
        self.assertEqual(reader.metadata.author, self.company.legal_name)
        for page in reader.pages:
            self.assertIn(self.company.legal_name, page.extract_text())
            self.assertNotIn('馭盛國際有限公司', page.extract_text())
            for private_field in ('淨利', '佣金', '車輛成本', '分期公司撥款'):
                self.assertNotIn(private_field, page.extract_text())

    def test_long_header_does_not_overlap_title_or_body(self):
        order = self.make_order(self.dealer)
        order.print_company_snapshot.update(legal_name='長公司名稱測試' * 8, address='測試地址' * 30, phone='1' * 40)
        pdf = build_order_contract_pdf(order)
        reader = PdfReader(BytesIO(pdf))
        self.assertEqual(len(reader.pages), 2)
        self.assertIn('統編', reader.pages[0].extract_text())

    def test_order_confirmation_view_round_trip(self):
        order = self.make_order()
        response = self.client.post(reverse('order_print_company', args=[order.pk]), {
            'company': self.company.pk, 'expected_revision': order.revision, 'reason':'舊單人工核對', 'acknowledged':'on'})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), '舊單人工核對')
        self.assertEqual(self.client.get(reverse('contract_print', args=[order.pk])).status_code, 200)


class PrintCompanyConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_admin_corrections_only_one_revision_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from sales.services.print_company import correct_order_company
        PrintCompany.objects.get_or_create(key='home', defaults={'legal_name':'測試店', 'tax_id':'12345678', 'address':'測試地址', 'phone':'123'})
        PrintCompanyTests.setUpTestData.__func__(type(self))
        order = PrintCompanyTests.make_order(self)
        revision = order.revision
        barrier = Barrier(2)

        def update(reason):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.admin.pk)
                barrier.wait(timeout=10)
                correct_order_company(user=user, pk=order.pk, company_id=self.company.pk,
                    revision=revision, reason=reason, acknowledged=True)
                return 'saved'
            except ValidationError:
                return 'stale'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, ['更正一', '更正二']))
        self.assertCountEqual(results, ['saved', 'stale'])
        self.assertEqual(order.print_company_changes.count(), 1)
