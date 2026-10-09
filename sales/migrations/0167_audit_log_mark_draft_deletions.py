"""把既有的 admin 刪除草稿稽核紀錄從「修改帳號」改為「刪除草稿」（1.56.0 起寫入的紀錄）。"""
from django.db import migrations
from django.db.models import Q

DRAFT_DELETIONS = Q(description__startswith="admin 刪除接待草稿 ") | Q(description__startswith="admin 刪除草稿 ")


def mark_draft_deletions(apps, schema_editor):
    log = apps.get_model("sales", "UserAccountAuditLog")
    log.objects.filter(DRAFT_DELETIONS, action="update").update(action="delete_draft")


def unmark_draft_deletions(apps, schema_editor):
    log = apps.get_model("sales", "UserAccountAuditLog")
    log.objects.filter(DRAFT_DELETIONS, action="delete_draft").update(action="update")


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0166_audit_log_delete_draft_action"),
    ]

    operations = [
        migrations.RunPython(mark_draft_deletions, unmark_draft_deletions),
    ]
