from django.conf import settings
from django.db import models


class ReportDefinition(models.Model):
    draft = models.JSONField(default=dict)
    published = models.JSONField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "sales"
        ordering = ["-updated_at", "-pk"]
        verbose_name = "自助報表"


class ReportRevision(models.Model):
    report = models.ForeignKey(ReportDefinition, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    config = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "sales"
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["report", "version"], name="unique_report_revision")]
