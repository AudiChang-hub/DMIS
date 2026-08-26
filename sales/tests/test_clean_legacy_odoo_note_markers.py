from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from sales.models import (
    DealerVolumeBonusRule,
    SalesSource,
    SalesSourceBrandPolicy,
)


class CleanLegacyOdooNoteMarkersTests(TestCase):
    def test_marker_is_removed_but_human_note_is_preserved(self):
        source = SalesSource.objects.create(
            name="測試車行",
            source_type=SalesSource.SourceType.DEALER,
            note="[Odoo 遷移 ID:183]\n真正的人工作業備註",
        )
        policy = SalesSourceBrandPolicy.objects.create(
            source=source,
            brand="SUZUKI",
            note="[Odoo 品牌授權 遷移 ID:88]\n原品牌授權：authorized",
        )
        bonus = DealerVolumeBonusRule.objects.create(
            dealer=source,
            brand="SUZUKI",
            starts_on="2026-01-01",
            ends_on="2026-12-31",
            note="說明前段\n[Odoo 台數獎金 遷移 ID:50]\n說明後段",
        )

        migration = import_module(
            "sales.migrations.0085_clean_legacy_odoo_note_markers"
        )
        migration.clean_legacy_odoo_note_markers(django_apps, None)

        source.refresh_from_db()
        policy.refresh_from_db()
        bonus.refresh_from_db()
        self.assertEqual(source.note, "真正的人工作業備註")
        self.assertEqual(policy.note, "原品牌授權：authorized")
        self.assertEqual(bonus.note, "說明前段\n說明後段")
