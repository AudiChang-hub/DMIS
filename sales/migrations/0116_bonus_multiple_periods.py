import django.db.models.deletion
from django.db import migrations, models


def backfill_periods(apps, schema_editor):
    Rule = apps.get_model('sales', 'DealerVolumeBonusRule')
    Period = apps.get_model('sales', 'DealerVolumeBonusPeriod')
    Settlement = apps.get_model('sales', 'DealerVolumeBonusSettlement')
    alias = schema_editor.connection.alias
    for rule in Rule.objects.using(alias).iterator():
        period, _ = Period.objects.using(alias).get_or_create(rule_id=rule.pk, starts_on=rule.starts_on, ends_on=rule.ends_on)
        Settlement.objects.using(alias).filter(rule_id=rule.pk).update(period_id=period.pk)


def verify_reverse_is_safe(apps, schema_editor):
    Rule = apps.get_model('sales', 'DealerVolumeBonusRule')
    for rule in Rule.objects.using(schema_editor.connection.alias).prefetch_related('periods').iterator(chunk_size=200):
        periods = list(rule.periods.all())
        if len(periods) != 1 or (periods[0].starts_on, periods[0].ends_on) != (rule.starts_on, rule.ends_on):
            raise RuntimeError('已有多期資料或期間已改動，不能直接降版；請保留資料並依備份還原流程處理。')


class Migration(migrations.Migration):
    dependencies = [('sales', '0115_bonus_periods_and_brands')]
    operations = [
        migrations.CreateModel(name='DealerVolumeBonusPeriod', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('starts_on', models.DateField('統計開始日')),
            ('ends_on', models.DateField('統計結束日')),
            ('rule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='periods', to='sales.dealervolumebonusrule')),
        ], options={'ordering': ['starts_on', 'id'], 'constraints': [models.UniqueConstraint(fields=('rule', 'starts_on', 'ends_on'), name='unique_bonus_rule_period')]}),
        migrations.AddField('dealervolumebonussettlement', 'period', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='settlements', to='sales.dealervolumebonusperiod', verbose_name='統計期間')),
        migrations.RunPython(backfill_periods, migrations.RunPython.noop),
        migrations.AlterField('dealervolumebonussettlement', 'period', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='settlements', to='sales.dealervolumebonusperiod', verbose_name='統計期間')),
        migrations.RemoveConstraint('dealervolumebonussettlement', 'unique_bonus_rule_dealer_settlement'),
        migrations.AddConstraint('dealervolumebonussettlement', models.UniqueConstraint(fields=('rule', 'period', 'dealer'), name='unique_bonus_rule_period_dealer_settlement')),
        migrations.RunPython(migrations.RunPython.noop, verify_reverse_is_safe),
    ]
