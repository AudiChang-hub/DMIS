"""隔離測試資料的公司設定、文件更正與 PDF 視覺驗證。"""
import asyncio
import sys
import tempfile
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect

from sales.tests.test_print_company import PrintCompanyTests
from sales.services.order_contract_pdf import build_order_contract_pdf
from sales.services.privacy_consent_pdf import build_privacy_consent_pdf


@override_settings(DEBUG=True, ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'], SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False)
class CompanyBrowserTests(StaticLiveServerTestCase):
    def test_company_flow(self):
        if sys.platform == 'win32':
            previous = asyncio.get_event_loop_policy()
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self.addCleanup(asyncio.set_event_loop_policy, previous)
        PrintCompanyTests.setUpTestData.__func__(type(self))
        order = PrintCompanyTests.make_order(self, self.dealer, source=self.source, source_type='dealer')
        self.client.force_login(self.admin)
        output = Path(tempfile.mkdtemp(prefix='dmis-company-browser-'))
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                context = browser.new_context(viewport={'width':1440, 'height':900})
                context.add_cookies([{'name':'sessionid', 'value':self.client.cookies['sessionid'].value, 'url':self.live_server_url}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('dealer_print_company', args=[self.source.pk]))
                page.get_by_label('公司／商號全名').fill('新版甲車業有限公司')
                page.get_by_label('設定／修改原因').fill('隔離測試遷址')
                expect(page.locator('[data-company-preview="legal_name"]')).to_have_text('新版甲車業有限公司')
                page.get_by_role('button', name='儲存公司資料', exact=True).click()
                expect(page.get_by_label('公司／商號全名')).to_have_value('新版甲車業有限公司')
                for width in (1440, 820, 390):
                    page.set_viewport_size({'width':width, 'height':1000})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    page.screenshot(path=str(output / f'company-{width}.png'), full_page=True)
                page.goto(self.live_server_url + reverse('order_print_company', args=[order.pk]))
                expect(page.get_by_role('heading', name='甲車業有限公司', exact=True)).to_be_visible()
                page.get_by_label('確認／更正原因').fill('本單採用新公司資料')
                page.get_by_label('我已確認銷售方', exact=False).check()
                page.get_by_role('button', name='確認並保留公司資料', exact=True).click()
                expect(page.get_by_role('heading', name='新版甲車業有限公司', exact=True)).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                browser.close()
        order.refresh_from_db()
        self.assertEqual(order.print_company_snapshot['legal_name'], '新版甲車業有限公司')
        import fitz
        for name, content in [('contract', build_order_contract_pdf(order)), ('privacy', build_privacy_consent_pdf(order))]:
            document = fitz.open(stream=content, filetype='pdf')
            for index, page in enumerate(document):
                page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(str(output / f'{name}-{index+1}.png'))
        order.print_company_snapshot.update(legal_name='長公司名稱測試' * 8, address='測試地址' * 30, phone='1' * 40)
        document = fitz.open(stream=build_order_contract_pdf(order), filetype='pdf')
        document[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(str(output / 'contract-long.png'))
        print(f'Company and PDF verification: {output}')
