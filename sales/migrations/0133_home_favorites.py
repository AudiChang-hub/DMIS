from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0132_systemannouncement_systemannouncementrevision")]

    operations = [
        migrations.AddField(model_name="userappearancepreference", name="home_favorites",
                            field=models.JSONField("首頁我的最愛", null=True, blank=True, default=None)),
        migrations.AddField(model_name="userappearancepreference", name="home_favorites_version",
                            field=models.PositiveIntegerField("首頁收藏設定版本", default=0)),
    ]
