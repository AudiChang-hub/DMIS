"""T-179：配件可屬於多個類別（先擴充）。

新增 AccessoryProduct.categories（多對多），把舊的單一類別回填進去；舊的 category 外鍵這一版保留，
新程式同步寫入排序最前的類別，下一版再移除。反向時多對多表整個移除，外鍵一直同步著，不需還原。
"""
from django.db import migrations, models


def backfill_categories(apps, schema_editor):
    Product = apps.get_model("sales", "AccessoryProduct")
    Through = Product.categories.through
    Through.objects.bulk_create(
        [Through(accessoryproduct_id=pk, accessorycategory_id=category_id)
         for pk, category_id in Product.objects.exclude(category__isnull=True).values_list("pk", "category_id")],
        ignore_conflicts=True,
    )


def restore_single_category(apps, schema_editor):
    # 反向前把外鍵改成排序最前的類別（正常情況下本來就同步著），之後多對多表由 RemoveField 移除。
    Product = apps.get_model("sales", "AccessoryProduct")
    for product in Product.objects.all():
        first = product.categories.order_by("sort_order", "name").values_list("pk", flat=True).first()
        if first is not None and product.category_id != first:
            Product.objects.filter(pk=product.pk).update(category_id=first)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0209_order_tax_consent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="accessoryproduct",
            name="category",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=models.deletion.SET_NULL,
                related_name="products", to="sales.accessorycategory", verbose_name="類別（舊）",
            ),
        ),
        migrations.AddField(
            model_name="accessoryproduct",
            name="categories",
            field=models.ManyToManyField(
                blank=True, related_name="category_products", to="sales.accessorycategory", verbose_name="類別",
            ),
        ),
        migrations.RunPython(backfill_categories, restore_single_category),
    ]
