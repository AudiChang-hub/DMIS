from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SalesSourceNoteMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0086_sales_source_line_group")
    migrate_to = ("sales", "0087_consolidate_sales_source_notes")
    restore_to = ("sales", "0088_sales_source_contact_and_cooperation_profiles")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.restore_to])

    def test_notes_and_contact_details_are_preserved_in_one_note(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        SalesSourceContact = self.old_apps.get_model("sales", "SalesSourceContact")
        source = SalesSource.objects.create(
            name="測試車行",
            source_type="dealer",
            note="原內部備註",
            relationship_note="重要合作車行",
        )
        SalesSourceContact.objects.create(
            source_id=source.pk,
            name="王先生",
            relationship="負責人",
            phone="02-12345678",
            extension="12",
            mobile="0912345678",
            email="owner@example.com",
            note="下午聯繫",
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        new_apps = self.executor.loader.project_state([self.migrate_to]).apps
        migrated = new_apps.get_model("sales", "SalesSource").objects.get(pk=source.pk)

        self.assertEqual(
            migrated.note,
            "\n".join(
                [
                    "原內部備註",
                    "重要合作車行",
                    "歷史聯絡資料：王先生（負責人）｜電話：02-12345678 分機 12／手機：0912345678／Email：owner@example.com／下午聯繫",
                ]
            ),
        )
        self.assertNotIn(
            "relationship_note", {field.name for field in migrated._meta.fields}
        )
        with self.assertRaises(LookupError):
            new_apps.get_model("sales", "SalesSourceContact")
