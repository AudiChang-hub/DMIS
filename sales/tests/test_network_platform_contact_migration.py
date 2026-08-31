from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


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
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_imports_only_non_struck_contacts_and_excludes_huang_yuting(self):
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

        self.assertEqual(PlatformContact.objects.count(), 111)
        self.assertEqual(
            MigratedSource.objects.filter(source_type="platform").count(), 26
        )
        self.assertFalse(
            PlatformContact.objects.filter(contact_person__icontains="黃鈺婷").exists()
        )
        self.assertFalse(
            PlatformContact.objects.filter(email__icontains="christine_huang").exists()
        )
        self.assertFalse(
            PlatformContact.objects.filter(contact_person__icontains="Jimmy 蔡杰榮").exists()
        )
        self.assertFalse(
            MigratedSource.objects.filter(name="Bonny LIVE").exists()
        )

        invoice_contact = PlatformContact.objects.get(
            source__name="遠時", contact_person="(發票)洪聿玟"
        )
        self.assertEqual(invoice_contact.email, "om-paymentservice@friday.tw")
        self.assertEqual(invoice_contact.note, "")
        self.assertEqual(
            PlatformContact.objects.filter(source__name="PC").count(), 8
        )
        self.assertEqual(
            PlatformContact.objects.filter(source__name="蝦皮").count(), 2
        )

        migrated_existing = MigratedSource.objects.get(pk=existing.pk)
        self.assertEqual(migrated_existing.responsible_person, "")
        self.assertEqual(migrated_existing.note, "")
