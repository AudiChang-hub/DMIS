from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0051_backfill_legacy_holiday_gift_dealers"),
    ]

    operations = [
        migrations.AddField(
            model_name="legacyimportbatch",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="封存時間"),
        ),
        migrations.AddField(
            model_name="legacyimportbatch",
            name="archived_by",
            field=models.CharField(blank=True, max_length=150, verbose_name="封存人員"),
        ),
        migrations.AddField(
            model_name="legacyimportrow",
            name="corrected_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="最後修正時間"),
        ),
        migrations.AddField(
            model_name="legacyimportrow",
            name="corrected_by",
            field=models.CharField(blank=True, max_length=150, verbose_name="最後修正人員"),
        ),
        migrations.AddField(
            model_name="legacyimportrow",
            name="excluded",
            field=models.BooleanField(default=False, verbose_name="人工排除"),
        ),
        migrations.AddField(
            model_name="legacyimportrow",
            name="manually_corrected",
            field=models.BooleanField(default=False, verbose_name="已人工修正"),
        ),
        migrations.AlterField(
            model_name="legacyimportrow",
            name="action",
            field=models.CharField(
                choices=[
                    ("create", "新增"),
                    ("update", "更新"),
                    ("skip", "略過"),
                    ("exclude", "不匯入"),
                    ("conflict", "衝突"),
                    ("error", "錯誤"),
                ],
                max_length=20,
                verbose_name="預計動作",
            ),
        ),
        migrations.CreateModel(
            name="LegacyImportCorrection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新時間")),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("correct", "修正後匯入"),
                            ("exclude", "排除此列"),
                            ("restore", "恢復匯入"),
                        ],
                        max_length=20,
                        verbose_name="處理方式",
                    ),
                ),
                ("before_data", models.JSONField(default=dict, verbose_name="處理前資料")),
                ("after_data", models.JSONField(default=dict, verbose_name="處理後資料")),
                ("reason", models.TextField(verbose_name="處理原因")),
                ("corrected_by", models.CharField(max_length=150, verbose_name="處理人員")),
                (
                    "row",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="corrections",
                        to="sales.legacyimportrow",
                        verbose_name="匯入資料列",
                    ),
                ),
            ],
            options={
                "verbose_name": "歷史匯入人工修正紀錄",
                "verbose_name_plural": "歷史匯入人工修正紀錄",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="legacyimportrow",
            index=models.Index(fields=["batch", "action"], name="legacy_row_batch_action_idx"),
        ),
    ]
