from django.conf import settings
from django.db import models


class ReportClassification(models.Model):
    """單一全站報表車種分類；草稿不影響發布快照。"""
    version = models.PositiveIntegerField(default=1)
    published_version = models.PositiveIntegerField(default=1)
    draft = models.JSONField(default=dict)
    published = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'sales'
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name='report_classification_singleton')]
        verbose_name = '報表分類設定'


class ReportClassificationRevision(models.Model):
    classification = models.ForeignKey(ReportClassification, on_delete=models.PROTECT, related_name='revisions')
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=30)
    snapshot = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    actor_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'sales'
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['classification', 'version'], name='unique_classification_revision')]
        verbose_name = '報表分類版本'


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
