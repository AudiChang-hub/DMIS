"""修正已核對的總銷售機種圖預設層級；保留其他發布設定及未發布草稿。"""
import copy
from django.db import migrations
from django.utils import timezone


def correct_month(apps, schema_editor):
    Report = apps.get_model('sales', 'ReportDefinition')
    Revision = apps.get_model('sales', 'ReportRevision')
    for report in Report.objects.using(schema_editor.connection.alias).select_for_update().all():
        config = report.published
        if not config or config.get('reader_layout') != 'sales_overview':
            continue
        next_config = copy.deepcopy(config)
        changed = False
        for card in next_config.get('cards', []):
            if card.get('chart') == 'stacked' and card.get('series') == 'legacy_motor_type' and card.get('dimension') == 'day':
                card['dimension'] = 'month'
                changed = True
        if not changed:
            continue
        if report.draft == config:
            report.draft = next_config
        report.published = next_config
        report.version += 1
        report.published_at = timezone.now()
        report.save()
        Revision.objects.using(schema_editor.connection.alias).create(report_id=report.pk, version=report.version, action='publish', config=next_config)


class Migration(migrations.Migration):
    dependencies = [('sales', '0120_reportdefinition_reportrevision')]
    # 反向部署不改動後續使用者的發布；舊版本由原有報表版本還原功能復原。
    operations = [migrations.RunPython(correct_month, migrations.RunPython.noop)]
