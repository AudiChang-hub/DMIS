"""隔離資料的代開確認、單筆授權與撤銷：桌機／平板／手機 Chrome。"""
import asyncio
import sys
import tempfile
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect

from sales.models import PrintCompany
from sales.tests import test_customer_order_access as fixtures


@override_settings(DEBUG=True, ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'], SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False)
class AssistedOrderBrowserTests(StaticLiveServerTestCase):
    def test_company_confirmation_and_grant_revoke(self):
        if sys.platform == 'win32':
            previous = asyncio.get_event_loop_policy()
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self.addCleanup(asyncio.set_event_loop_policy, previous)
        fixtures.CustomerOrderAccessTests.setUpTestData.__func__(type(self))
        order = fixtures.CustomerOrderAccessTests.make_order(self, self.staff, self.other_source)
        PrintCompany.objects.create(key=f'dealer:{self.source.pk}', source=self.source,
            legal_name='試作甲車行有限公司', tax_id='12345678', address='測試地址', phone='02-12345678')
        self.client.force_login(self.admin)
        admin_cookie = self.client.cookies['sessionid'].value
        dealer_client = Client()
        dealer_client.force_login(self.user)
        dealer_cookie = dealer_client.cookies['sessionid'].value
        output = Path(tempfile.mkdtemp(prefix='dmis-assisted-orders-'))
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                context = browser.new_context(viewport={'width':1440, 'height':900})
                context.add_cookies([{'name':'sessionid','value':admin_cookie,'url':self.live_server_url}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('order_start'))
                page.get_by_role('link', name='2 來源', exact=True).click()
                expect(page.locator('[data-assisted-company]')).to_be_hidden()
                page.locator('#id_source_type').select_option('dealer')
                expect(page.locator(f'#id_source option[value="{self.source.pk}"]')).to_have_count(1)
                page.locator('#id_source').select_option(str(self.source.pk), force=True)
                expect(page.locator('[data-assisted-company-summary]')).to_contain_text('試作甲車行有限公司')
                expect(page.locator('[data-assisted-company]')).to_be_visible()
                page.locator('#id_assisted_company_confirmed').check()
                for width in (1440, 820, 390):
                    page.set_viewport_size({'width':width,'height':1000})
                    page.locator('#id_assisted_company_confirmed').uncheck()
                    page.locator('#id_assisted_company_confirmed').check()
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width+1)
                    page.locator('#source').screenshot(path=str(output / f'assisted-{width}.png'))
                page.locator('#id_source').select_option(str(self.other_source.pk), force=True)
                expect(page.locator('#id_assisted_company_confirmed')).not_to_be_checked()
                expect(page.locator('[data-assisted-company-summary]')).to_contain_text('admin')
                url = self.live_server_url + reverse('order_customer_access', args=[order.pk])
                page.goto(url)
                page.locator('#grant-account-select').select_option(str(self.profile.pk))
                page.get_by_role('button', name='載入授權設定').click()
                page.locator('#id_can_view').check()
                page.locator('#id_can_print').check()
                page.locator('#id_reason').fill('隔離測試：交由車行查看文件')
                page.get_by_role('button', name='儲存授權', exact=True).click()
                expect(page.locator('body')).to_contain_text('單筆額外授權已更新')
                for width in (1440, 820, 390):
                    page.set_viewport_size({'width':width,'height':1000})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width+1)
                    page.screenshot(path=str(output / f'grant-{width}.png'), full_page=True)
                context.add_cookies([{'name':'sessionid','value':dealer_cookie,'url':self.live_server_url}])
                response = page.goto(self.live_server_url + reverse('order_detail', args=[order.pk]))
                self.assertEqual(response.status, 200)
                expect(page.locator('body')).not_to_contain_text('金額收支資訊')
                context.add_cookies([{'name':'sessionid','value':admin_cookie,'url':self.live_server_url}])
                page.goto(url + f'?account={self.profile.pk}')
                page.locator('#id_reason').fill('隔離測試：撤銷授權')
                page.get_by_role('button', name='撤銷額外授權', exact=True).click()
                expect(page.locator('body')).to_contain_text('已撤銷')
                context.add_cookies([{'name':'sessionid','value':dealer_cookie,'url':self.live_server_url}])
                response = page.goto(self.live_server_url + reverse('order_detail', args=[order.pk]))
                self.assertEqual(response.status, 404)
                self.assertEqual(errors, [])
            finally:
                browser.close()
        print(f'Assisted orders browser screenshots: {output}')
