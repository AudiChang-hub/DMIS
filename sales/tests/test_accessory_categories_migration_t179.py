"""資料遷移 0210（T-179）：配件多類別先擴充。舊的單一類別回填到多對多；反向時外鍵保留排序最前的類別。"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, tag


@tag("migration")
class AccessoryCategoriesMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0209_order_tax_consent")
    migrate_to = ("sales", "0210_accessory_product_categories")

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate([self.migrate_from])
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _apps(self, target):
        return MigrationExecutor(connection).loader.project_state([target]).apps

    def test_backfills_single_category_and_reverses(self):
        apps = self._apps(self.migrate_from)
        Category = apps.get_model("sales", "AccessoryCategory")
        Product = apps.get_model("sales", "AccessoryProduct")
        helmet = Category.objects.create(name="遷移測試安全帽", sort_order=10)
        parts = Category.objects.create(name="遷移測試改裝", sort_order=20)
        with_category = Product.objects.create(name="遷移測試帽", category=helmet)
        uncategorised = Product.objects.create(name="遷移測試未分類")

        MigrationExecutor(connection).migrate([self.migrate_to])
        Product = self._apps(self.migrate_to).get_model("sales", "AccessoryProduct")
        self.assertEqual(list(Product.objects.get(pk=with_category.pk).categories.values_list("pk", flat=True)), [helmet.pk])
        self.assertFalse(Product.objects.get(pk=uncategorised.pk).categories.exists())
        # 新版多掛一個類別（外鍵照同步規則留在排序最前的類別）。
        product = Product.objects.get(pk=with_category.pk)
        product.categories.add(parts.pk)

        MigrationExecutor(connection).migrate([self.migrate_from])
        Product = self._apps(self.migrate_from).get_model("sales", "AccessoryProduct")
        self.assertEqual(Product.objects.get(pk=with_category.pk).category_id, helmet.pk)
        self.assertIsNone(Product.objects.get(pk=uncategorised.pk).category_id)

    def test_reverse_moves_foreign_key_to_first_remaining_category(self):
        apps = self._apps(self.migrate_from)
        Category = apps.get_model("sales", "AccessoryCategory")
        Product = apps.get_model("sales", "AccessoryProduct")
        first = Category.objects.create(name="遷移測試甲", sort_order=10)
        second = Category.objects.create(name="遷移測試乙", sort_order=20)
        product = Product.objects.create(name="遷移測試品")

        MigrationExecutor(connection).migrate([self.migrate_to])
        Product = self._apps(self.migrate_to).get_model("sales", "AccessoryProduct")
        Product.objects.get(pk=product.pk).categories.add(second.pk, first.pk)  # 歷史模型不觸發同步訊號

        MigrationExecutor(connection).migrate([self.migrate_from])
        Product = self._apps(self.migrate_from).get_model("sales", "AccessoryProduct")
        self.assertEqual(Product.objects.get(pk=product.pk).category_id, first.pk)
