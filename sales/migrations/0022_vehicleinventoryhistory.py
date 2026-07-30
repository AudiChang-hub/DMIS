from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0021_idocrjob_document_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="VehicleInventoryHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新時間")),
                ("event_type", models.CharField(choices=[("created", "建立庫存"), ("updated", "更新資料"), ("transferred", "調度車輛")], max_length=20, verbose_name="異動類型")),
                ("actor_name", models.CharField(blank=True, max_length=150, verbose_name="異動人員")),
                ("reason", models.TextField(blank=True, verbose_name="異動原因")),
                ("changes", models.JSONField(blank=True, default=dict, verbose_name="異動內容")),
                ("status_snapshot", models.CharField(choices=[("available", "可銷售"), ("reserved", "已預留"), ("transfer_pending", "待調車"), ("in_transfer", "調車中"), ("delivery_pending", "待交車"), ("delivered", "已交車"), ("condition_issue", "車況異常"), ("sold", "已售出"), ("inactive", "停用")], max_length=30, verbose_name="當下狀態")),
                ("condition_note_snapshot", models.TextField(blank=True, verbose_name="當下車況")),
                ("condition_resolution_snapshot", models.TextField(blank=True, verbose_name="當下處理結果")),
                ("condition_photo_snapshot", models.ImageField(blank=True, upload_to="inventory/history/%Y/%m/", verbose_name="當下車況照片")),
                ("from_location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="sales.store", verbose_name="調出位置")),
                ("location_store_snapshot", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="sales.store", verbose_name="當下位置")),
                ("to_location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="sales.store", verbose_name="調入位置")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="history_entries", to="sales.vehicleinventory", verbose_name="庫存車輛")),
            ],
            options={
                "verbose_name": "庫存異動紀錄",
                "verbose_name_plural": "庫存異動紀錄",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
