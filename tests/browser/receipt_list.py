"""隔離資料庫的列表新增、二次儲存、取消確認與響應式驗證。"""
import asyncio
import sys
import tempfile
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect

from sales.tests import test_order_workspace as fixtures


@override_settings(DEBUG=True, ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'], SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False)
class ReceiptBrowserTests(StaticLiveServerTestCase):
    def test_receipt_list_full_flow(self):
        if sys.platform == 'win32':
            previous = asyncio.get_event_loop_policy()
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self.addCleanup(asyncio.set_event_loop_policy, previous)
        fixtures.OrderWorkspaceTests.setUpTestData.__func__(type(self))
        self.client.force_login(self.admin)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                context = browser.new_context(viewport={'width': 1440, 'height': 900})
                context.add_cookies([{'name': 'sessionid', 'value': self.client.cookies['sessionid'].value, 'url': self.live_server_url}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('order_detail', args=[self.order.pk]) + '?tab=finance')
                page.locator('[data-workspace-tab="finance"]').click()
                rows = page.locator('#payment-records [data-payment-row]:visible')
                expect(rows).to_have_count(1)
                expect(rows.first.locator('[name$="-item_name"]')).to_have_value('訂金')
                page.get_by_role('button', name='＋ 新增收款', exact=True).click()
                expect(rows).to_have_count(2)
                row = rows.last
                expect(row.locator('[name$="-confirmed"]')).not_to_be_checked()
                row.locator('[name$="-item_name"]').fill('客戶分次匯款')
                row.locator('[name$="-receipt_kind"]').select_option('customer')
                row.locator('[name$="-received_amount"]').fill('70000')
                row.locator('[name$="-received_on"]').fill('2026-09-21')
                row.locator('[name$="-payment_method"]').select_option('匯款')
                row.locator('[name$="-confirmed"]').check()
                finance = page.locator('[data-workspace-save="operations"]')
                with page.expect_response(lambda r: '/operations/' in r.url and r.request.method == 'POST') as saved:
                    finance.locator('button[type="submit"]').click()
                self.assertTrue(saved.value.json()['ok'], saved.value.json())
                expect(page.locator('[data-receipt-value="customer_due"]')).to_have_text('0')
                receipt_id = row.locator('[name$="-id"]').input_value()
                self.assertTrue(receipt_id)
                row.locator('[name$="-confirmed"]').uncheck()
                with page.expect_response(lambda r: '/operations/' in r.url and r.request.method == 'POST') as saved:
                    finance.locator('button[type="submit"]').click()
                self.assertTrue(saved.value.json()['ok'], saved.value.json())
                expect(page.locator('[data-receipt-value="customer_due"]')).to_have_text('70,000')
                expect(row.locator('[name$="-id"]')).to_have_value(receipt_id)
                expect(row.locator('[name$="-confirmed"]')).not_to_be_checked()
                screenshots = Path(tempfile.mkdtemp(prefix='dmis-receipt-browser-'))
                for width in (1440, 820, 390):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    row.scroll_into_view_if_needed()
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    expect(row.locator('[name$="-received_amount"]')).to_be_visible()
                    page.screenshot(path=str(screenshots / f'receipts-{width}.png'))
                row.locator('summary').click()
                row.get_by_role('button', name='移除此筆收款').click()
                with page.expect_response(lambda r: '/operations/' in r.url and r.request.method == 'POST') as saved:
                    finance.locator('button[type="submit"]').click()
                self.assertTrue(saved.value.json()['ok'], saved.value.json())
                self.assertEqual(page.evaluate('performance.getEntriesByType("navigation").length'), 1)
                self.assertEqual(errors, [])
                print(f'Receipt browser screenshots: {screenshots}')
            finally:
                browser.close()
        self.assertFalse(self.order.payment_records.filter(item_name='客戶分次匯款').exists())
