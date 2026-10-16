from copy import deepcopy
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from pypdf import PdfReader

from sales.models import PrintCompany, PrintCompanyChange, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services.print_company import initialize_company
from sales.services.order_contract_pdf import build_order_contract_pdf


class PrintCompanyTests(TestCase):
    """1.84.0（使用者 2026-10-16）：系統只有本店人員使用，訂購單一律用本店公司（key="home"）。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('admin', password='test-pass-123')
        cls.staff = get_user_model().objects.create_user('print-staff')
        cls.source = SalesSource.objects.create(name='測試甲車行', source_type='dealer')
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

    def post_settings(self, **overrides):
        data = {'legal_name': '新本店公司', 'tax_id': '23456789', 'address': '新地址', 'phone': '02-22222222',
                'expected_revision': PrintCompany.objects.get(key='home').revision, 'reason': '公司遷址'}
        data.update(overrides)
        return self.client.post(reverse('print_company_settings'), data)

    def test_new_order_uses_home_company_even_for_dealer_source(self):
        order = self.make_order(self.admin, source=self.source, source_type='dealer')
        self.assertEqual(order.print_company, self.home)
        self.assertEqual(order.print_company_snapshot['legal_name'], self.home.legal_name)
        self.assertEqual(order.print_company_snapshot['company_id'], self.home.pk)

    def test_removed_dealer_and_per_order_company_routes_do_not_reverse(self):
        order = self.make_order()
        for route, args in [('dealer_print_company', [self.source.pk]), ('order_print_company', [order.pk])]:
            with self.assertRaises(NoReverseMatch):
                reverse(route, args=args)

    def test_company_edit_and_reprint_do_not_change_snapshot(self):
        order = self.make_order(self.admin, source=self.source, source_type='dealer')
        before = deepcopy(order.print_company_snapshot)
        self.assertEqual(self.post_settings(legal_name='新版本店公司').status_code, 302)
        response = self.client.get(reverse('contract_print', args=[order.pk]))
        reader = PdfReader(BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(len(reader.pages), 2)
        self.assertEqual(reader.metadata.author, before['legal_name'])
        for page in reader.pages:
            self.assertIn(before['legal_name'], page.extract_text())
            self.assertNotIn('新版本店公司', page.extract_text())
        order.refresh_from_db()
        self.assertEqual(order.print_company_snapshot, before)

    def test_order_without_company_prints_with_home_company(self):
        # 1.73.1（使用者 2026-10-13）：沒有開單公司的訂單一律用馭盛，第一次列印時保存，不再要求 admin 逐筆確認。
        order = self.make_order(source=self.source, source_type='dealer')
        self.assertEqual(order.print_company_snapshot, {})
        for route in ['contract_print', 'privacy_consent_print', 'order_documents_print']:
            self.assertEqual(self.client.get(reverse(route, args=[order.pk])).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.print_company_id, self.home.pk)
        self.assertEqual(order.print_company_snapshot['legal_name'], self.home.legal_name)

    def test_missing_home_company_page_links_root_to_settings(self):
        order = self.make_order()
        PrintCompany.objects.filter(pk=self.home.pk).update(tax_id='')
        response = self.client.get(reverse('contract_print', args=[order.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, '本店（馭盛）的公司全名', status_code=409)
        self.assertContains(response, '設定本店公司資料', status_code=409)
        self.assertContains(response, reverse('print_company_settings'), status_code=409)
        order.refresh_from_db()
        self.assertEqual(order.print_company_snapshot, {})

    def test_only_root_can_manage_company_settings(self):
        from sales.access.models import ScreenAccessGrant, UserAccessState
        UserAccessState.objects.create(user=self.staff, configured=True)
        ScreenAccessGrant.objects.create(user=self.staff, screen_key='order_documents', view=True, export=True)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('print_company_settings')).status_code, 403)
        self.assertEqual(self.post_settings().status_code, 403)
        self.staff.is_superuser = True
        self.staff.save()
        self.assertEqual(self.client.get(reverse('print_company_settings')).status_code, 403)
        self.assertEqual(self.post_settings().status_code, 403)
        self.home.refresh_from_db()
        self.assertNotEqual(self.home.legal_name, '新本店公司')

    def test_company_settings_are_audited_and_old_order_unchanged(self):
        order = self.make_order(self.admin)
        before = deepcopy(order.print_company_snapshot)
        revision = self.home.revision
        self.assertEqual(self.post_settings().status_code, 302)
        self.home.refresh_from_db()
        self.assertEqual(self.home.revision, revision + 1)
        change = PrintCompanyChange.objects.get(company=self.home)
        self.assertEqual(change.actor, self.admin)
        self.assertEqual(change.reason, '公司遷址')
        self.assertEqual(change.before['legal_name'], before['legal_name'])
        self.assertEqual(change.after['address'], '新地址')
        self.assertContains(self.client.get(reverse('print_company_settings')), '公司遷址')
        order.refresh_from_db()
        self.assertEqual(order.print_company_snapshot, before)
        stale = self.post_settings(legal_name='過期內容', expected_revision=revision, reason='過期')
        self.assertContains(stale, '已被其他人修改')
        self.home.refresh_from_db()
        self.assertEqual(self.home.legal_name, '新本店公司')
        self.assertEqual(PrintCompanyChange.objects.filter(company=self.home).count(), 1)

    def test_get_does_not_create_company_and_invalid_data_rejected(self):
        PrintCompany.objects.filter(pk=self.home.pk).delete()
        url = reverse('print_company_settings')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertFalse(PrintCompany.objects.exists())
        response = self.client.post(url, {'legal_name': '本店', 'tax_id': 'abc', 'address': '地址', 'phone': '電話',
                                          'expected_revision': 0, 'reason': '設定'})
        self.assertContains(response, '8 碼數字')
        self.assertFalse(PrintCompany.objects.exists())
        response = self.client.post(url, {'legal_name': '新本店公司', 'tax_id': '23456789', 'address': '新地址',
                                          'phone': '02-22222222', 'expected_revision': 0, 'reason': '首次設定'})
        self.assertEqual(response.status_code, 302)
        created = PrintCompany.objects.get(key='home')
        self.assertEqual((created.legal_name, created.revision), ('新本店公司', 1))
        self.assertEqual(PrintCompanyChange.objects.get(company=created).before, {})

    def test_combined_documents_and_author_use_same_company(self):
        self.post_settings(legal_name='合併文件測試公司')
        order = self.make_order(self.admin, source=self.source, source_type='dealer')
        response = self.client.get(reverse('order_documents_print', args=[order.pk]))
        reader = PdfReader(BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(len(reader.pages), 3)
        self.assertEqual(reader.metadata.author, '合併文件測試公司')
        for page in reader.pages:
            self.assertIn('合併文件測試公司', page.extract_text())
            for private_field in ('淨利', '佣金', '車輛成本', '分期公司撥款'):
                self.assertNotIn(private_field, page.extract_text())

    def test_long_header_does_not_overlap_title_or_body(self):
        order = self.make_order(self.admin)
        order.print_company_snapshot.update(legal_name='長公司名稱測試' * 8, address='測試地址' * 30, phone='1' * 40)
        pdf = build_order_contract_pdf(order)
        reader = PdfReader(BytesIO(pdf))
        self.assertEqual(len(reader.pages), 2)
        self.assertIn('統編', reader.pages[0].extract_text())
