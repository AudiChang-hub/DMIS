"""真實 Chrome、隔離資料：配件條件欄位及授權操作。"""
import asyncio
import sys
import tempfile
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect
from sales.tests import test_customer_order_access as fixtures
from sales.access.models import ScreenAccessGrant


@override_settings(DEBUG=True, ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'], SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False)
class CustomerAccessBrowserTests(StaticLiveServerTestCase):
    def test_accessory_fields_and_permissions(self):
        if sys.platform == 'win32':
            previous = asyncio.get_event_loop_policy()
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self.addCleanup(asyncio.set_event_loop_policy, previous)
        fixtures.CustomerOrderAccessTests.setUpTestData.__func__(type(self))
        ScreenAccessGrant.objects.create(user=self.user, screen_key='order_gift', view=True, operate=True)
        self.client.force_login(self.admin)
        admin_cookie = self.client.cookies['sessionid'].value
        dealer_client = Client()
        dealer_client.force_login(self.user)
        dealer_cookie = dealer_client.cookies['sessionid'].value
        output = Path(tempfile.mkdtemp(prefix='dmis-customer-access-'))
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                context = browser.new_context(viewport={'width':1440, 'height':900})
                context.add_cookies([{'name':'sessionid', 'value':admin_cookie, 'url':self.live_server_url}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('dealer_account_edit', args=[self.user.pk]))
                page.get_by_label('顯示名稱', exact=False).fill('測試車行人員')
                expect(page.get_by_label('可贈送配件', exact=False)).to_be_checked()
                expect(page.get_by_label('下單金額調整', exact=False)).not_to_be_checked()
                page.get_by_label('可列印客戶簽署文件', exact=False).check()
                page.get_by_label('訂單資料範圍', exact=False).select_option('dealer')
                page.get_by_role('button', name='確認儲存帳號與功能').click()
                expect(page).to_have_url(self.live_server_url + reverse('dealer_accounts', args=[self.source.pk]))
                page.goto(self.live_server_url + reverse('order_start'))
                # 新訂單仍是步驟導覽，需求頁含配件。
                page.get_by_role('link', name='5 需求', exact=True).click()
                row = page.locator('[data-accessory-row]').first
                # Accordion sections may be collapsed, but field state is still initialized.
                expect(row.locator('[data-custom-accessory]')).to_have_attribute('hidden', '')
                select = row.locator('select[name$="-accessory_product"]')
                select.select_option('other', force=True)
                expect(row.locator('[data-custom-accessory]')).not_to_have_attribute('hidden', '')
                select.select_option(str(self.product.pk), force=True)
                expect(row.locator('[data-custom-accessory]')).to_have_attribute('hidden', '')
                row.locator('select[name$="-line_type"]').select_option('gift', force=True)
                expect(row.locator('input[name$="-amount"]')).to_have_value('0')
                expect(row.locator('input[name$="-labor_fee"]')).to_have_value('0')
                context.add_cookies([{'name':'sessionid', 'value':dealer_cookie, 'url':self.live_server_url}])
                page.goto(self.live_server_url + reverse('order_start'))
                page.get_by_role('link', name='5 需求', exact=True).click()
                row = page.locator('[data-accessory-row]').first
                expect(row.locator('[data-custom-accessory]')).to_have_attribute('hidden', '')
                self.assertIn('gift', row.locator('select[name$="-line_type"] option').evaluate_all('(els)=>els.map(e=>e.value)'))
                self.assertNotIn('other', row.locator('select[name$="-accessory_product"] option').evaluate_all('(els)=>els.map(e=>e.value)'))
                page.get_by_role('button', name='新增配件', exact=False).click()
                expect(page.locator('[data-accessory-row]').nth(1).locator('[data-custom-accessory]')).to_have_attribute('hidden', '')
                for width in (1440, 820, 390):
                    page.set_viewport_size({'width':width, 'height':1000})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    page.screenshot(path=str(output / f'order-{width}.png'), full_page=True)
                self.assertEqual(errors, [])
            finally:
                browser.close()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.order_scope, 'dealer')
        self.assertFalse(ScreenAccessGrant.objects.get(user=self.user, screen_key='order_pricing').operate)
        print(f'Customer access browser screenshots: {output}')
