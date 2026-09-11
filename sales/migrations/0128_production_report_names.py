from django.db import migrations
from django.utils import timezone


def rename_reports(apps, schema_editor):
    Report = apps.get_model('sales', 'ReportDefinition')
    Revision = apps.get_model('sales', 'ReportRevision')
    alias = schema_editor.connection.alias
    for report in Report.objects.using(alias).select_for_update().all():
        changed = []
        for field in ('draft', 'published'):
            config = getattr(report, field)
            if not isinstance(config, dict):
                continue
            updated = dict(config)
            title = updated.get('title', '')
            if isinstance(title, str) and '原報表核對版' in title:
                updated['title'] = title.replace('｜原報表核對版', '').replace('原報表核對版', '').rstrip(' ｜|')
            description = updated.get('description')
            if isinstance(description, str):
                updated['description'] = description.replace('依原報表四圖與明細建立的核對版本。', '依原報表四圖與明細建立。')
            if updated != config:
                setattr(report, field, updated)
                changed.append(field)
        if changed:
            report.version += 1
            report.updated_at = timezone.now()
            report.save(using=alias, update_fields=[*changed, 'version', 'updated_at'])
            Revision.objects.using(alias).create(report_id=report.pk, version=report.version, action='rename', config=report.draft)


class Migration(migrations.Migration):
    dependencies = [('sales', '0127_report_operate_access')]
    operations = [migrations.RunPython(rename_reports, migrations.RunPython.noop)]
