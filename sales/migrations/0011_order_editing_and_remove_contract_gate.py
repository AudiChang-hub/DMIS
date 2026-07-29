from django.db import migrations, models
import django.db.models.deletion


def move_contract_pending_to_allocation(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SalesOrder.objects.filter(status="contract_pending").update(
        status="allocation_pending"
    )


class Migration(migrations.Migration):
    dependencies = [("sales", "0010_salesorder_contract_fields")]

    operations = [
        migrations.AddField(
            model_name="salesorder",
            name="revision",
            field=models.PositiveIntegerField(default=1, verbose_name="資料版本"),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="editing_session",
            field=models.CharField(blank=True, max_length=40, verbose_name="編輯工作階段"),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="editing_by",
            field=models.CharField(blank=True, max_length=150, verbose_name="目前編輯人員"),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="editing_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="最後編輯心跳"),
        ),
        migrations.CreateModel(
            name="OrderChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新時間")),
                ("reason", models.TextField(verbose_name="變更原因")),
                ("changes", models.JSONField(default=dict, verbose_name="欄位變更")),
                ("actor_name", models.CharField(max_length=150, verbose_name="操作人員")),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="changes", to="sales.salesorder")),
            ],
            options={
                "verbose_name": "訂單變更",
                "verbose_name_plural": "訂單變更",
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(move_contract_pending_to_allocation, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="salesorder",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "草稿"),
                    ("allocation_pending", "待配車"),
                    ("allocated", "已配車"),
                    ("transfer_pending", "待調車"),
                    ("in_transfer", "調車中"),
                    ("delivery_pending", "待交車"),
                    ("delivered_docs_pending", "已交車／待補文件"),
                    ("completed", "已完成"),
                    ("cancel_refund_pending", "取消待退款"),
                    ("cancelled", "已取消／已退款"),
                ],
                default="draft",
                max_length=32,
                verbose_name="訂單狀態",
            ),
        ),
    ]
