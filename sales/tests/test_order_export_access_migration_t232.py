"""資料遷移 0215（T-232）：營運匯出併入訂單匯出，原本能匯出營運資料的帳號補上訂單匯出授權。"""
import importlib
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

from sales.access.models import ScreenAccessGrant, UserAccessRevision, UserAccessState
from sales.access.services import AccessPolicy

migration = importlib.import_module("sales.migrations.0215_order_export_access")


class OrderExportAccessMigrationTests(TestCase):
    def account(self, name, *grants, configured=True):
        user = get_user_model().objects.create_user(name, password="Migrate-test-232!")
        UserAccessState.objects.create(user=user, configured=configured, version=3)
        for key, actions in grants:
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, **actions)
        return user

    def run_migration(self):
        migration.grant_order_export(apps, SimpleNamespace(connection=connection))

    def test_accounts_that_could_export_operations_keep_exporting(self):
        exporter = self.account("ops-exporter", ("operations", {"export": True}), ("profit", {"export": True}),
                                ("orders", {"operate": True}))
        no_profit = self.account("ops-no-profit", ("operations", {"export": True}), ("profit", {}))
        already = self.account("orders-exporter", ("operations", {"export": True}), ("profit", {"export": True}),
                               ("orders", {"export": True}))
        legacy = self.account("legacy", configured=False)
        new_grant = self.account("ops-only", ("operations", {"export": True}), ("profit", {"export": True}))
        self.assertFalse(AccessPolicy(exporter).route("order_export_download", "POST"))

        self.run_migration()

        # 原本能匯出（營運匯出＋淨利匯出）→ 補上訂單匯出，原有的操作授權保留，留權限歷程。
        grant = ScreenAccessGrant.objects.get(user=exporter, screen_key="orders")
        self.assertEqual((grant.view, grant.operate, grant.export), (True, True, True))
        self.assertTrue(AccessPolicy(exporter).route("order_export_download", "POST"))
        revision = UserAccessRevision.objects.get(user=exporter)
        self.assertEqual((revision.version, revision.actor_name), (4, migration.ACTOR))
        self.assertEqual(revision.before["screens"]["orders"], {"view": True, "operate": True, "export": False})
        self.assertEqual(revision.after["screens"]["orders"], {"view": True, "operate": True, "export": True})
        self.assertEqual(UserAccessState.objects.get(user=exporter).version, 4)
        # 沒有 orders 授權列的也補一列（只給查看＋匯出）。
        grant = ScreenAccessGrant.objects.get(user=new_grant, screen_key="orders")
        self.assertEqual((grant.view, grant.operate, grant.export), (True, False, True))
        # 原本就不能匯出（缺淨利匯出）、已經有訂單匯出、未設定權限的帳號都不動。
        self.assertFalse(ScreenAccessGrant.objects.filter(user=no_profit, screen_key="orders").exists())
        for user in (no_profit, already, legacy):
            self.assertFalse(UserAccessRevision.objects.filter(user=user).exists())
            self.assertEqual(UserAccessState.objects.get(user=user).version, 3)

        # 重跑不會重複補。
        self.run_migration()
        self.assertEqual(UserAccessRevision.objects.filter(user=exporter).count(), 1)
