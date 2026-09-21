"""隔離資料库真實瀏覽器驗證：python manage.py test tests.browser.ppt_refinements --noinput"""
import tempfile
import asyncio
import sys
import os
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect

from sales.models import SystemAnnouncement, AnnouncementImage
from sales.tests import test_order_workspace as fixtures
from sales.tests.test_ppt_refinements import picture, pdf_document


@override_settings(DEBUG=True, ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'], SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False)
class PptBrowserTests(StaticLiveServerTestCase):
    def test_intake_previews_other_accessory_and_same_owner(self):
        if sys.platform == 'win32':
            previous_policy = asyncio.get_event_loop_policy()
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self.addCleanup(asyncio.set_event_loop_policy, previous_policy)
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
                page.goto(self.live_server_url + reverse('order_create'))
                page.locator('#owner').evaluate('(node) => node.open = true')
                upload = page.locator('[name="owner_bankbook"]')
                upload.set_input_files({'name': 'bank.png', 'mimeType': 'image/png', 'buffer': picture().read()})
                expect(page.locator('.upload-previews img')).to_be_visible()
                page.locator('.upload-previews .document-thumbnail').click()
                expect(page.locator('.document-preview-dialog')).to_be_visible()
                page.get_by_role('button', name='關閉預覽').click()
                page.locator('#extras').evaluate('(node) => node.open = true')
                same = page.locator('[name="old_owner_same_as_owner"]')
                expect(same).not_to_be_checked()
                page.locator('[name="trade_in_intent"]').select_option('yes')
                expect(page.locator('[data-trade-in-uploads]')).to_be_visible()
                same.check()
                expect(page.locator('[data-trade-in-uploads]')).to_be_hidden()
                expect(page.locator('[name="old_bankbook"]')).to_be_disabled()
                same.uncheck()
                expect(page.locator('[name="old_bankbook"]')).to_be_enabled()
                row = page.locator('[data-accessory-row]').first
                expect(row.locator('[data-custom-accessory]')).to_be_hidden()
                row.locator('[name$="-accessory_product"]').select_option('other')
                expect(row.locator('[data-custom-accessory]')).to_be_visible()
                row.locator('[name$="-custom_name"]').fill('加裝手機架')
                row.locator('[name$="-amount"]').fill('1000')
                row.locator('[name$="-labor_fee"]').fill('200')
                row.locator('[name$="-line_type"]').select_option('gift')
                expect(row.locator('[name$="-amount"]')).to_have_value('0')
                expect(row.locator('[name$="-labor_fee"]')).to_have_value('0')
                screenshots = Path(tempfile.mkdtemp(prefix='dmis-intake-fixes-'))
                for width in (1440, 820, 390):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    page.locator('.upload-previews').first.scroll_into_view_if_needed()
                    page.screenshot(path=str(screenshots / f'preview-{width}.png'))
                    row.scroll_into_view_if_needed()
                    page.screenshot(path=str(screenshots / f'accessory-{width}.png'))
                page.wait_for_load_state('networkidle')
                self.assertFalse(errors, errors)
                print(f'Intake screenshots: {screenshots}', flush=True)
            finally:
                browser.close()

    def test_tabs_media_and_responsive_layout(self):
        if sys.platform == 'win32':
            previous_policy = asyncio.get_event_loop_policy()
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            self.addCleanup(asyncio.set_event_loop_policy, previous_policy)
        fixtures.OrderWorkspaceTests.setUpTestData.__func__(type(self))
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.order.id_front = picture('front.png')
            self.order.signed_contract = pdf_document()
            self.order.save()
            item = SystemAnnouncement.objects.create(title='公告畫面驗收', body='圖片下方內容', published=True)
            first = AnnouncementImage.objects.create(announcement=item, image=picture('first.png'))
            second = AnnouncementImage.objects.create(announcement=item, image=picture('second.png'))
            self.client.force_login(self.admin)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel=os.environ.get('DMIS_BROWSER_CHANNEL', 'chrome'), headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                context.add_cookies([{'name': 'sessionid', 'value': self.client.cookies['sessionid'].value, 'url': self.live_server_url}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('order_detail', args=[self.order.pk]))
                page.locator('.document-thumbnail').first.click()
                expect(page.locator('dialog.document-preview-dialog')).to_be_visible()
                page.get_by_role('button', name='關閉預覽').click()
                pdf_button = page.locator('.document-thumbnail:has(iframe)').first
                for summary in pdf_button.locator('xpath=ancestor::details[not(@open)]/summary').all():
                    summary.click()
                pdf_button.click()
                expect(page.locator('dialog.document-preview-dialog iframe')).to_be_visible()
                page.get_by_role('button', name='關閉預覽').click()
                page.locator('[data-workspace-tab="finance"]').click()
                field = page.locator('[name="operations-shipping_expense"]')
                for summary in field.locator('xpath=ancestor::details[not(@open)]/summary').all():
                    summary.click()
                field.fill('1234')
                page.locator('[data-workspace-tab="subsidy"]').click()
                page.locator('[name="old_owner_same_as_owner"]').check()
                expect(page.locator('[name="old_owner_name"]')).to_have_value(self.order.owner_name)
                page.locator('[data-subsidy-items] [name$="-expected_amount"]').first.fill('1250')
                expect(page.locator('[data-subsidy-total]')).to_have_text('1,250')
                page.locator('[data-workspace-tab="finance"]').click()
                expect(field).to_have_value('1234')
                self.assertEqual(page.evaluate('performance.getEntriesByType("navigation").length'), 1)
                screenshots = Path(tempfile.mkdtemp(prefix='dmis-ppt-browser-'))
                for width in (1440, 820, 390):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    for tab in ('order', 'finance', 'subsidy'):
                        page.locator(f'[data-workspace-tab="{tab}"]').click()
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1, f'{width}/{tab} horizontal overflow')
                    page.screenshot(path=str(screenshots / f'order-{width}.png'))
                page.locator('[data-workspace-tab="finance"]').click()
                finance = page.locator('[data-workspace-save="operations"]')
                with page.expect_response(lambda response: '/operations/' in response.url and response.request.method == 'POST') as saved:
                    finance.locator('button[type="submit"]').click()
                self.assertTrue(saved.value.json()['ok'], saved.value.json())
                expect(field).to_have_value('1234.0000')
                page.evaluate("document.documentElement.dataset.theme = 'night-blue'")
                section = finance.locator('.operation-section').first
                self.assertEqual(section.evaluate('(node) => getComputedStyle(node).color'), 'rgb(232, 238, 240)')
                self.assertEqual(page.locator('.mobile-nav>a.active').evaluate('(node) => getComputedStyle(node).color'), 'rgb(232, 238, 240)')
                page.screenshot(path=str(screenshots / 'finance-night-390.png'))
                page.on('dialog', lambda dialog: dialog.accept())
                page.wait_for_load_state('networkidle')
                page.close()
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse('announcement_detail', args=[item.pk]))
                print('Announcement browser page:', page.url, page.locator('h1').all_text_contents(), flush=True)
                page.screenshot(path=str(screenshots / 'announcement-before.png'))
                page.locator('[data-announcement-edit]').click()
                page.locator('[data-announcement-editor] [name="title"]').fill('已編輯公告')
                page.locator('[data-announcement-image]').first.locator('[data-image-move="down"]').click()
                expect(page.locator('[name="image_order"]')).to_have_value(f'{second.pk},{first.pk}')
                with page.expect_response(lambda response: '/news/' in response.url and response.request.method == 'POST'):
                    page.locator('[data-announcement-editor] button[type="submit"]').click()
                print('Announcement after save:', page.url, page.locator('.errorlist').all_text_contents(), flush=True)
                page.screenshot(path=str(screenshots / 'announcement-after.png'))
                expect(page.get_by_role('heading', name='已編輯公告')).to_be_visible()
                page.screenshot(path=str(screenshots / 'announcement-390.png'))
                page.locator('.announcement-images img').evaluate_all('(images) => images.forEach(img => img.loading = "eager")')
                page.wait_for_function('Array.from(document.querySelectorAll(".announcement-images img")).every(img => img.complete)')
                page.wait_for_load_state('networkidle')
                self.assertFalse(errors, errors)
                print(f'Browser screenshots: {screenshots}')
                browser.close()
