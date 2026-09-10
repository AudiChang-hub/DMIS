"""設計預覽沿用正式讀取端點，唯讀且限制於當前報表。"""
import copy
from django.test import Client, TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError
from sales.tests import test_reporting as fixtures
from sales.models import ReportDefinition, ReportRevision, SalesOrder
from sales.reporting.engine import validate_config
from sales.reporting.source_templates import SOURCE_TEMPLATES


class ReportDesignerTests(TestCase):
    login = fixtures.ReportingTests.login
    data = fixtures.ReportingTests.data
    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def designer_payload(self, config):
        payload = self.data(config, action='canvas')
        for key, value in config.items():
            if key not in ('cards', 'fixed_filters'):
                payload[key] = value
        for key, value in config.get('fixed_filters', {}).items():
            payload['fixed_' + key] = '\n'.join(value) if key in ('model_include', 'model_exclude', 'model_prefix') else value
        for index, card in enumerate(config['cards']):
            for key, value in card.get('fixed_filters', {}).items():
                from sales.reporting.engine import MODEL_TEXT_SCOPES
                payload[f'cards-{index}-fixed_{key}'] = '\n'.join(value) if key in MODEL_TEXT_SCOPES else value
        return payload

    def test_whole_canvas_all_official_pages_readonly(self):
        self.login()
        versions = list(ReportRevision.objects.values_list('pk', flat=True))
        orders = list(SalesOrder.objects.values())
        before = copy.deepcopy(self.report.draft)
        session = dict(self.client.session)
        for name, factory in SOURCE_TEMPLATES.items():
            with self.subTest(page=name):
                config = factory()
                payload = self.designer_payload(config)
                response = self.client.post(reverse('report_edit', args=[self.report.pk]), payload)
                self.assertEqual(response.status_code, 200, response.content[:600])
                result = response.json()
                self.assertEqual(result['status'], 200)
                self.assertIn('data-reader-layout="' + config['reader_layout'] + '"', result['document'])
                self.assertIn('report-designer-frame.js', result['document'])
                self.assertIn('report-overview.js', result['document'])
                self.assertNotIn('height:520px;overflow:auto', result['document'])
                self.assertNotIn('data-reader-pages', result['document'])
                self.assertEqual(result['document'].count('data-chart-index='), len(config['cards']))
        self.report.refresh_from_db()
        self.assertEqual(self.report.draft, before)
        self.assertEqual(self.report.version, 1)
        self.assertEqual(list(ReportRevision.objects.values_list('pk', flat=True)), versions)
        self.assertEqual(list(SalesOrder.objects.values()), orders)
        self.assertEqual(dict(self.client.session), session)

    def test_canvas_route_allowlist_and_csv_detail(self):
        self.login()
        endpoint = reverse('report_edit', args=[self.report.pk])
        for target in ('https://example.com/reports/1/', 'https://[', '//example.com/reports/1/', '/orders/', '/reports/999/', '/reports/1/../', '/data/report-design/1/'):
            payload = self.data(action='canvas'); payload['preview_url'] = target
            self.assertEqual(self.client.post(endpoint, payload).status_code, 400, target)
        for route, args, suffix, marker in (
            ('report_detail', [self.report.pk, 0], '?inline=1&group=__all__', 'data-detail-content'),
            ('report_export', [self.report.pk, 0], '?format=excel', '\ufeff'),
        ):
            payload = self.data(action='canvas'); payload['preview_url'] = reverse(route, args=args) + suffix
            response = self.client.post(endpoint, payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 200)
            self.assertIn(marker, response.json()['document'])
        client = Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(endpoint, self.data(action='canvas')).status_code, 403)
        for user in (self.user, self.other_admin):
            self.login(user)
            self.assertEqual(self.client.post(endpoint, self.data(action='canvas')).status_code, 403)

    def test_designer_style_validation_publish_restore(self):
        self.login()
        config = copy.deepcopy(self.config)
        config['cards'][0].update(font_size=20, title_align='right', palette='accessible', show_legend='hide', show_tooltip='hide', cross_filter='off')
        validate_config(config)
        endpoint = reverse('report_edit', args=[self.report.pk])
        payload = self.data(config, action='publish')
        self.assertEqual(self.client.post(endpoint, payload).status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.published['cards'][0]['palette'], 'accessible')
        published = self.client.get(reverse('report_display', args=[self.report.pk]))
        self.assertContains(published, 'data-font-size="20"')
        self.assertContains(published, 'data-cross-filter="off"')
        for key, value in (('font_size', True), ('font_size', 15), ('title_align', 'left;display:none'), ('palette', '<script>'), ('show_tooltip', True), ('cross_filter', 'eval')):
            invalid = copy.deepcopy(config); invalid['cards'][0][key] = value
            with self.assertRaises(ValidationError): validate_config(invalid)

    def test_all_official_canvas_chart_markup_matches_publication(self):
        import re
        self.login()
        endpoint = reverse('report_edit', args=[self.report.pk])
        for name, factory in SOURCE_TEMPLATES.items():
            with self.subTest(page=name):
                payload = self.designer_payload(factory())
                payload['version'] = self.report.version
                preview = self.client.post(endpoint, payload).json()['document']
                payload['action'] = 'publish'
                response = self.client.post(endpoint, payload)
                self.assertEqual(response.status_code, 302)
                self.report.refresh_from_db()
                public = self.client.get(reverse('report_display', args=[self.report.pk])).content.decode()
                pattern = r'<div class="report-grid">(.*?)</div>\s*<section class="report-panel report-inline-detail'
                self.assertEqual(re.search(pattern, preview, re.S).group(1), re.search(pattern, public, re.S).group(1))
