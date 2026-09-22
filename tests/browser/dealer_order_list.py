"""Customer list: responsive layout, theme readability, filters and navigation on isolated data."""
import asyncio
import sys
import tempfile
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import sync_playwright, expect

from sales.models import SalesOrder
from sales.tests import test_customer_order_access as fixtures


@override_settings(DEBUG=True, ALLOWED_HOSTS=['localhost','127.0.0.1','testserver'], SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False)
class DealerOrderListBrowserTests(StaticLiveServerTestCase):
    def test_list_layout_themes_search_and_open(self):
        if sys.platform == 'win32':
            previous = asyncio.get_event_loop_policy()
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self.addCleanup(asyncio.set_event_loop_policy, previous)
        fixtures.CustomerOrderAccessTests.setUpTestData.__func__(type(self))
        self.model.brand, self.model.name, self.model.model_number, self.model.model_year = 'SUZUKI', 'SWISH 125', 'UG125DA', 2026
        self.model.save()
        self.color.name = '紳士藍'
        self.color.save()
        order = fixtures.CustomerOrderAccessTests.make_order(self, self.user)
        SalesOrder.objects.filter(pk=order.pk).update(accepted_name='接單測試人員',accepted_at=timezone.now())
        cancelled = fixtures.CustomerOrderAccessTests.make_order(self,self.user)
        SalesOrder.objects.filter(pk=cancelled.pk).update(status='cancelled',owner_name='較長車主姓名顯示測試有限公司')
        self.client.force_login(self.user)
        output = Path(tempfile.mkdtemp(prefix='dmis-dealer-list-'))
        with sync_playwright() as tool:
            browser = tool.chromium.launch(channel='chrome',headless=True)
            try:
                context = browser.new_context()
                context.add_cookies([{'name':'sessionid','value':self.client.cookies['sessionid'].value,'url':self.live_server_url}])
                page = context.new_page()
                errors = []
                page.on('pageerror',lambda error:errors.append(str(error)))
                url = self.live_server_url + reverse('order_list')
                page.goto(url)
                expect(page.locator('.dealer-order-row')).to_have_count(2)
                for width in (1440,820,390,320):
                    page.set_viewport_size({'width':width,'height':900})
                    for theme in ('professional','night-blue','deep-blue','graphite-gold','bright-indigo','high-contrast'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme',theme)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width+1)
                        expect(page.locator('.dealer-order-open').first).to_be_visible()
                        self.assertGreaterEqual(page.locator('#dealer-order-query').bounding_box()['height'],44)
                        contrasts = page.evaluate('''() => {
                          const rgb = value => (value.match(/[\\d.]+/g) || []).map(Number);
                          const luminance = channels => channels.slice(0,3).reduce((sum,value,index) => {
                            const c=value/255; return sum + (c<=.04045 ? c/12.92 : ((c+.055)/1.055)**2.4)*[.2126,.7152,.0722][index];
                          },0);
                          return ['.dealer-orders-eyebrow','.dealer-orders-count strong','.dealer-order-open'].map(selector => {
                            const element=document.querySelector(selector); let parent=element, bg;
                            while(parent) { bg=rgb(getComputedStyle(parent).backgroundColor); if(bg.length===3 || bg[3]>0) break; parent=parent.parentElement; }
                            const fg=luminance(rgb(getComputedStyle(element).color)), background=luminance(bg);
                            return (Math.max(fg,background)+.05)/(Math.min(fg,background)+.05);
                          });
                        }''')
                        self.assertTrue(all(ratio>=4.5 for ratio in contrasts),(theme,contrasts))
                        if width in (1440,390) and theme in ('professional','night-blue'):
                            page.screenshot(path=str(output / f'{width}-{theme}.png'),full_page=True)
                page.evaluate("document.documentElement.dataset.theme='professional'")
                page.set_viewport_size({'width':390,'height':844})
                page.get_by_label('搜尋訂單／車主／車款',exact=True).fill(order.number)
                page.get_by_role('button',name='查詢',exact=True).click()
                expect(page.locator('.dealer-order-row')).to_have_count(1)
                expect(page.locator('.dealer-order-vehicle')).to_contain_text('紳士藍')
                self.assertEqual(page.locator('.dealer-order-vehicle').inner_text().count('SWISH 125'),1)
                page.locator('.dealer-order-open').click()
                expect(page).to_have_url(self.live_server_url + reverse('order_detail',args=[order.pk]))
                page.goto(url)
                page.get_by_label('訂單狀態',exact=True).select_option('cancelled')
                page.get_by_role('button',name='查詢',exact=True).click()
                expect(page.locator('.dealer-order-row')).to_have_count(1)
                expect(page.locator('.status-cancelled')).to_be_visible()
                page.get_by_label('搜尋訂單／車主／車款',exact=True).fill('沒有這張單')
                page.get_by_role('button',name='查詢',exact=True).click()
                expect(page.get_by_role('heading',name='沒有符合條件的訂單')).to_be_visible()
                page.get_by_role('link',name='清除條件',exact=True).first.click()
                expect(page.locator('.dealer-order-row')).to_have_count(2)
                self.assertEqual(errors,[])
            finally:
                browser.close()
        print(f'Dealer order list screenshots: {output}')
