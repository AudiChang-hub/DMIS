from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from sales.reporting.models import ReportDefinition, ReportRevision
from sales.reporting.source_templates import SOURCE_TEMPLATES
from sales.reporting.views import initial_config


class ReportNameTests(TestCase):
    def test_all_templates_use_production_titles(self):
        for factory in SOURCE_TEMPLATES.values():
            self.assertNotIn('核對版', factory()['title'])

    def test_migration_preserves_settings_history_and_is_idempotent(self):
        old = {**initial_config(), 'title': '總車輛銷售｜原報表核對版'}
        report = ReportDefinition.objects.create(draft=old, published=old, version=1)
        revision = ReportRevision.objects.create(report=report, version=1, action='save', config=old)
        draft = ReportDefinition.objects.create(draft={**old, 'title': '油車｜原報表核對版（複本）'}, version=0)
        custom = ReportDefinition.objects.create(draft={**old, 'title': '自訂正式分析'}, version=0)
        migrate = import_module('sales.migrations.0128_production_report_names').rename_reports
        migrate(apps, SimpleNamespace(connection=connection))
        report.refresh_from_db()
        expected = {**deepcopy(old), 'title': '總車輛銷售'}
        self.assertEqual(report.draft, expected)
        self.assertEqual(report.published, expected)
        self.assertEqual(report.version, 2)
        revision.refresh_from_db()
        self.assertEqual(revision.config, old)
        draft.refresh_from_db()
        self.assertIsNone(draft.published)
        self.assertEqual(draft.draft['title'], '油車（複本）')
        custom.refresh_from_db()
        self.assertEqual(custom.version, 0)
        migrate(apps, SimpleNamespace(connection=connection))
        report.refresh_from_db()
        self.assertEqual(report.version, 2)
        self.assertEqual(report.revisions.count(), 2)

    def test_restoring_old_revision_does_not_restore_obsolete_name(self):
        admin = get_user_model().objects.create_superuser('admin', password='Test-Only-123')
        self.client.force_login(admin)
        old = {**initial_config(), 'title': '總車輛銷售｜原報表核對版'}
        report = ReportDefinition.objects.create(draft={**old, 'title': '總車輛銷售'}, version=2)
        ReportRevision.objects.create(report=report, version=1, action='save', config=old)
        response = self.client.post(reverse('report_lifecycle', args=[report.pk]), {'version':2, 'action':'restore', 'revision':1})
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.draft['title'], '總車輛銷售')
