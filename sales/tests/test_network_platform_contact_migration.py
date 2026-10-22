from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, tag


@tag("migration")
class NetworkPlatformContactMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0103_network_platform_contacts")
    migrate_to = ("sales", "0104_import_network_platform_contacts")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.old_apps.get_model(
            "sales", "SalesSourcePlatformContact"
        ).objects.all().delete()
        self.old_apps.get_model("sales", "SalesSource").objects.filter(
            source_type="platform"
        ).delete()
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_creates_platform_sources_without_any_contact_personal_data(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        SalesSourceCategory = self.old_apps.get_model("sales", "SalesSourceCategory")
        category, _ = SalesSourceCategory.objects.get_or_create(
            name="網路平台",
            defaults={"system_behavior": "platform", "active": True},
        )
        existing = SalesSource.objects.create(
            name="Friday",
            source_type="platform",
            category_id=category.pk,
            responsible_person="Friday",
            note="歷史聯絡資料：Friday（負責人）",
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        MigratedSource = apps.get_model("sales", "SalesSource")
        PlatformContact = apps.get_model("sales", "SalesSourcePlatformContact")

        # repo 公開：migration 不可再帶合作平台窗口的姓名、手機或 Email。
        self.assertEqual(PlatformContact.objects.count(), 0)
        self.assertEqual(
            MigratedSource.objects.filter(source_type="platform").count(), 26
        )
        self.assertTrue(MigratedSource.objects.filter(name="遠時").exists())
        self.assertFalse(MigratedSource.objects.filter(name="Bonny LIVE").exists())

        migrated_existing = MigratedSource.objects.get(pk=existing.pk)
        self.assertEqual(migrated_existing.responsible_person, "")
        self.assertEqual(migrated_existing.note, "")

    def test_migration_source_has_no_phone_or_email(self):
        from pathlib import Path
        import re

        source = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0104_import_network_platform_contacts.py"
        ).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"09\d{2}-?\d{3}-?\d{3}", source))
        self.assertNotIn("@", source)
