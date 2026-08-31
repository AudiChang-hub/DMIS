import importlib
from datetime import date
from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from sales.models import SalesSource


class SalesSourceCodeTests(TestCase):
    def test_new_platform_gets_next_general_source_code(self):
        SalesSource.objects.create(
            name="同日既有來源",
            source_type=SalesSource.SourceType.DEALER,
            code="N26083101",
        )
        expected_code = SalesSource.next_general_source_code(
            code_date=date(2026, 8, 31)
        )

        with patch("sales.models.timezone.localdate", return_value=date(2026, 8, 31)):
            platform = SalesSource.objects.create(
                name="新網路平台",
                source_type=SalesSource.SourceType.PLATFORM,
            )

        self.assertEqual(platform.code, expected_code)

    def test_platform_keeps_existing_source_code(self):
        platform = SalesSource.objects.create(
            name="既有代碼平台",
            source_type=SalesSource.SourceType.PLATFORM,
            code="N26042808",
        )

        self.assertEqual(platform.code, "N26042808")

    def test_data_migration_fills_only_missing_platform_codes(self):
        preserved = SalesSource.objects.create(
            name="保留既有平台",
            source_type=SalesSource.SourceType.PLATFORM,
            code="N26042801",
        )
        first = SalesSource.objects.create(
            name="待補平台一",
            source_type=SalesSource.SourceType.PLATFORM,
            code="TEMP-01",
        )
        second = SalesSource.objects.create(
            name="待補平台二",
            source_type=SalesSource.SourceType.PLATFORM,
            code="TEMP-02",
        )
        SalesSource.objects.filter(pk__in=[first.pk, second.pk]).update(code="")
        SalesSource.objects.create(
            name="占用當日首碼",
            source_type=SalesSource.SourceType.DEALER,
            code="N26083101",
        )

        migration = importlib.import_module(
            "sales.migrations.0106_assign_network_platform_codes"
        )
        with patch.object(migration, "CODE_STEM", "N991231"):
            SalesSource.objects.filter(name="占用當日首碼").update(
                code="N99123101"
            )
            migration.assign_network_platform_codes(apps, None)

        preserved.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(preserved.code, "N26042801")
        self.assertEqual(first.code, "N99123102")
        self.assertEqual(second.code, "N99123103")
        self.assertFalse(
            SalesSource.objects.filter(
                source_type=SalesSource.SourceType.PLATFORM,
                code="",
            ).exists()
        )
