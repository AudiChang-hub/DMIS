from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0055_source_categories_and_transaction_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="legacyimportbatch",
            name="processing_completed",
            field=models.PositiveIntegerField(default=0, verbose_name="已處理筆數"),
        ),
        migrations.AddField(
            model_name="legacyimportbatch",
            name="processing_error",
            field=models.TextField(blank=True, verbose_name="背景匯入錯誤"),
        ),
        migrations.AddField(
            model_name="legacyimportbatch",
            name="processing_finished_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="結束匯入時間"),
        ),
        migrations.AddField(
            model_name="legacyimportbatch",
            name="processing_heartbeat_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="最後進度時間"),
        ),
        migrations.AddField(
            model_name="legacyimportbatch",
            name="processing_job_id",
            field=models.CharField(blank=True, max_length=80, verbose_name="背景工作編號"),
        ),
        migrations.AddField(
            model_name="legacyimportbatch",
            name="processing_started_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="開始匯入時間"),
        ),
        migrations.AddField(
            model_name="legacyimportbatch",
            name="processing_total",
            field=models.PositiveIntegerField(default=0, verbose_name="預計處理筆數"),
        ),
        migrations.AlterField(
            model_name="legacyimportbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("preview", "待確認"),
                    ("processing", "匯入中"),
                    ("completed", "已匯入"),
                    ("failed", "處理失敗"),
                ],
                default="preview",
                max_length=20,
                verbose_name="批次狀態",
            ),
        ),
    ]
