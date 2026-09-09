"""升級指定電動車報表的閱讀版型，不改動業務資料或其他報表。"""
import copy
from django.db import migrations
from django.utils import timezone


def upgrade_electric(apps, schema_editor):
    Report = apps.get_model('sales', 'ReportDefinition')
    Revision = apps.get_model('sales', 'ReportRevision')
    alias = schema_editor.connection.alias
    for report in Report.objects.using(alias).select_for_update().all():
        config = report.published
        if not config or config.get('title', '').split('｜')[0] != '電動車銷售統計':
            continue
        cards = config.get('cards', [])
        if (config.get('fixed_filters', {}).get('legacy_energy') != ['電車'] or len(cards) != 3
                or cards[0].get('series') != 'legacy_sales_source'
                or cards[1].get('series') != 'legacy_model'
                or cards[2].get('dimension') != 'legacy_model'):
            continue
        updated = copy.deepcopy(config)
        updated['reader_layout'] = 'electric_overview'
        updated['cards'][0]['width'] = 12
        model_card = updated['cards'][1]
        if model_card.get('dimension') == 'day':
            model_card['dimension'] = 'month'
        if model_card.get('title') == '電動車每日銷售型號':
            model_card['title'] = '電動車每月銷售型號'
        if updated == config:
            continue
        if report.draft == config:
            report.draft = copy.deepcopy(updated)
        report.published = updated
        report.version += 1
        report.published_at = timezone.now()
        report.save(using=alias)
        Revision.objects.using(alias).create(report_id=report.pk, version=report.version, action='publish', config=updated)


class Migration(migrations.Migration):
    dependencies = [('sales', '0121_total_sales_month_grain')]
    # 原版本由報表設計管理還原；不覆寫遷移後的管理者編輯。
    operations = [migrations.RunPython(upgrade_electric, migrations.RunPython.noop)]
