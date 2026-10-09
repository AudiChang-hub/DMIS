"""資料遷移 0167：既有的 admin 刪除草稿紀錄改為「刪除草稿」，其他「修改帳號」紀錄不動；可反向還原。"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class AuditLogDraftDeletionMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0166_audit_log_delete_draft_action")
    migrate_to = ("sales", "0167_audit_log_mark_draft_deletions")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _apps(self, target):
        return MigrationExecutor(connection).loader.project_state([target]).apps

    def test_marks_only_draft_deletions_and_reverses(self):
        Log = self._apps(self.migrate_from).get_model("sales", "UserAccountAuditLog")
        reception = Log.objects.create(target_username="Sylvia", action="update",
                                       description="admin 刪除接待草稿 405a785a（建立人 Sylvia）；原因：測試草稿")
        normal = Log.objects.create(target_username="admin", action="update",
                                    description="admin 刪除草稿 1234abcd（建立人 admin）；原因：重複")
        account = Log.objects.create(target_username="Sylvia", action="update", description="修改權限：訂單")

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        Log = self._apps(self.migrate_to).get_model("sales", "UserAccountAuditLog")
        self.assertEqual(Log.objects.get(pk=reception.pk).action, "delete_draft")
        self.assertEqual(Log.objects.get(pk=normal.pk).action, "delete_draft")
        self.assertEqual(Log.objects.get(pk=account.pk).action, "update")

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        Log = self._apps(self.migrate_from).get_model("sales", "UserAccountAuditLog")
        self.assertEqual(set(Log.objects.values_list("action", flat=True)), {"update"})
