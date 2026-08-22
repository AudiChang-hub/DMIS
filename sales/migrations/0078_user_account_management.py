from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0077_userappearancepreference"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSecurityProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新時間")),
                ("must_change_password", models.BooleanField(default=False, verbose_name="下次登入須變更密碼")),
                ("password_changed_at", models.DateTimeField(blank=True, null=True, verbose_name="密碼變更時間")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="security_profile", to=settings.AUTH_USER_MODEL, verbose_name="使用者")),
            ],
            options={"verbose_name": "使用者安全設定", "verbose_name_plural": "使用者安全設定"},
        ),
        migrations.CreateModel(
            name="UserAccountAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新時間")),
                ("target_username", models.CharField(max_length=150, verbose_name="帳號快照")),
                ("action", models.CharField(choices=[("create", "建立帳號"), ("update", "修改帳號"), ("activate", "啟用帳號"), ("deactivate", "停用帳號"), ("reset_password", "重設密碼"), ("change_password", "使用者變更密碼"), ("grant_admin", "授予管理者"), ("revoke_admin", "移除管理者")], max_length=30, verbose_name="動作")),
                ("description", models.CharField(max_length=500, verbose_name="說明")),
                ("metadata", models.JSONField(blank=True, default=dict, verbose_name="變更摘要")),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="account_actions_performed", to=settings.AUTH_USER_MODEL, verbose_name="操作人")),
                ("target", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="account_actions_received", to=settings.AUTH_USER_MODEL, verbose_name="對象")),
            ],
            options={"verbose_name": "帳號異動紀錄", "verbose_name_plural": "帳號異動紀錄", "ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddIndex(
            model_name="useraccountauditlog",
            index=models.Index(fields=["target", "-created_at"], name="sales_usera_target__eb56c6_idx"),
        ),
        migrations.AddIndex(
            model_name="useraccountauditlog",
            index=models.Index(fields=["actor", "-created_at"], name="sales_usera_actor_i_3433f9_idx"),
        ),
    ]
