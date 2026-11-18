import importlib
from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from sales.models import SalesSource


class SalesSourceCodeTests(TestCase):
    def test_new_sources_get_no_code(self):
        """T-238（使用者 2026-11-18）：來源代碼全面取消，車行、網路平台、本店來源存檔都不再自動編碼。"""
        for source_type in SalesSource.SourceType.values:
            with self.subTest(source_type=source_type):
                source = SalesSource.objects.create(name=f"新來源-{source_type}", source_type=source_type)
                source.refresh_from_db()
                self.assertEqual(source.code, "")
        self.assertFalse(hasattr(SalesSource, "next_general_source_code"))

    # 以下測的是歷史 migration（0106），下一版刪欄位時一併移除。
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
