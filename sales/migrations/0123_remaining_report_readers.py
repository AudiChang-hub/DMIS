"""升級已選定的 11 個閱讀頁；不改來源訂單、財務或管理者未發布草稿。"""
import copy
from django.db import migrations
from django.utils import timezone


def upgrade_readers(apps, schema_editor):
    Report = apps.get_model('sales', 'ReportDefinition')
    Revision = apps.get_model('sales', 'ReportRevision')
    alias = schema_editor.connection.alias
    mapping = {
        '電動車－網路平台銷售統計': ('platform_overview', 1, 'month'),
        '油車－網路平台銷售統計': ('platform_overview', 1, 'month'),
        '電動車－車行銷售統計': ('dealer_overview', 1, 'legacy_dealer'),
        '油車－車行銷售統計': ('dealer_overview', 1, 'legacy_dealer'),
        '電動車－台數統計': ('count_overview', 1, 'legacy_dealer'),
        '油車－台數統計': ('count_overview', 1, 'legacy_dealer'),
        '油車銷售統計': ('gasoline_overview', 3, 'month'),
        '性別 X 年齡': ('analysis_overview', 2, 'age_group'),
        '車型 X 性別': ('analysis_overview', 4, 'sex'),
        '車型 X 顏色': ('analysis_overview', 4, 'color'),
        '性別 X 車型顏色': ('analysis_overview', 4, 'color'),
    }
    for report in Report.objects.using(alias).select_for_update().all():
        current = report.published
        if not current or current.get('audience') != 'admin':
            continue
        name = current.get('title', '').split('｜')[0]
        if name not in mapping:
            continue
        layout, count, dimension = mapping[name]
        cards = current.get('cards', [])
        if len(cards) != count or cards[0].get('dimension') != dimension:
            continue
        updated = copy.deepcopy(current)
        updated['reader_layout'] = layout
        if layout == 'gasoline_overview':
            updated['cards'][0]['width'] = 12
            model = updated['cards'][1]
            if model.get('dimension') == 'day' and model.get('series') == 'legacy_model':
                model['dimension'] = 'month'
                model['title'] = model['title'].replace('每日', '每月')
        if name == '電動車－車行銷售統計' and 'legacy_notes' not in updated.get('records_columns', []):
            updated.setdefault('records_columns', []).append('legacy_notes')
        updated['description'] = updated.get('description', '').replace('電動車頁原始備註尚待安全欄位映射，尚未完整驗收。', '電動車頁歷史備註取原始備註欄，僅供 admin 查閱。')
        if updated == current:
            continue
        if report.draft == current:
            report.draft = copy.deepcopy(updated)
        report.published = updated
        report.version += 1
        report.published_at = timezone.now()
        report.save(using=alias)
        Revision.objects.using(alias).create(report_id=report.pk, version=report.version, action='publish', config=updated)


class Migration(migrations.Migration):
    dependencies = [('sales', '0122_electric_sales_overview')]
    operations = [migrations.RunPython(upgrade_readers, migrations.RunPython.noop)]
