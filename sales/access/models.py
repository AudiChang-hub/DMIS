from django.conf import settings
from django.db import models


class UserAccessState(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="screen_access_state")
    configured = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "sales"
        verbose_name = "人員畫面權限狀態"


class ScreenAccessGrant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    screen_key = models.CharField(max_length=40)
    view = models.BooleanField(default=False)
    operate = models.BooleanField(default=False)
    export = models.BooleanField(default=False)

    class Meta:
        app_label = "sales"
        constraints = [
            models.UniqueConstraint(fields=["user", "screen_key"], name="unique_user_screen_access"),
            models.CheckConstraint(condition=models.Q(view=True) | models.Q(operate=False, export=False), name="screen_actions_require_view"),
        ]


class ReportAccessGrant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    report = models.ForeignKey("sales.ReportDefinition", on_delete=models.CASCADE)
    view = models.BooleanField(default=False)
    export = models.BooleanField(default=False)

    class Meta:
        app_label = "sales"
        constraints = [
            models.UniqueConstraint(fields=["user", "report"], name="unique_user_report_access"),
            models.CheckConstraint(condition=models.Q(view=True) | models.Q(export=False), name="report_export_requires_view"),
        ]


class UserAccessRevision(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="access_revisions")
    version = models.PositiveIntegerField()
    before = models.JSONField()
    after = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="access_actions")
    actor_name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "sales"
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["user", "version"], name="unique_user_access_revision")]
        verbose_name = "人員畫面權限歷程"
