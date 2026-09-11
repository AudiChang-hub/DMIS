"""凍結 2026-09-11 等價分類快照；不更新任何訂單或報表設計。"""
from django.db import migrations


def seed(apps, schema_editor):
    groups = (
        (('EV062','EV060L','EV076','EV070V','EV076S','EV076SZV','Gogoro','Pulse','S2 ABS','S2ABS'), '白牌電車'),
        (('JEGO','VIVA','EZ1','EZZY','Ur2'), '綠牌電車'),
        (('BOBE','SHINE','TSV57','M02','M01','JDL-B1'), '微型電車'),
        (('UQ','UC','UG','UT','UT125XZ'), '速克達'),
        (('DRZ-4SM','GSX','DS','DS250'), '擋車'),
    )
    colors = ['#737373','#7ac36a','#faa75a','#f15a60','#5a9bd4','#a86e11']
    categories, rules = [], []
    for index, (models, name) in enumerate(groups):
        category = f'category-{index}'
        categories.append(dict(id=category, name=name, color=colors[index], order=index, enabled=True))
        for text in models:
            rules.append(dict(id=f'rule-{len(rules)}', match='exact', text=text, category=category, enabled=True))
    categories.append(dict(id='other', name='其他', color=colors[5], order=99, enabled=True))
    for text in ('UQ','UC','UG','UT','GSX','DS'):
        numeric = text in ('UQ','UC','UG','UT')
        rules.append(dict(id=f'rule-{len(rules)}', match='numeric' if numeric else 'series', text=text,
                          category='category-3' if numeric else 'category-4', enabled=True))
    snapshot = dict(categories=categories, rules=rules)
    State = apps.get_model('sales', 'ReportClassification')
    Revision = apps.get_model('sales', 'ReportClassificationRevision')
    state, created = State.objects.using(schema_editor.connection.alias).get_or_create(pk=1,
        defaults=dict(version=1, published_version=1, draft=snapshot, published=snapshot))
    if created:
        Revision.objects.using(schema_editor.connection.alias).create(classification=state, version=1, action='initial',
                                                                     snapshot=snapshot, actor_name='系統初始版本')


class Migration(migrations.Migration):
    dependencies = [('sales', '0124_report_classification')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
