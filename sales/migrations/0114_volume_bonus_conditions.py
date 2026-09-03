from django.db import migrations, models
import django.db.models.deletion


def backfill_dealer(apps, schema_editor):
    Settlement = apps.get_model('sales', 'DealerVolumeBonusSettlement')
    for row in Settlement.objects.using(schema_editor.connection.alias).select_related('rule').iterator():
        row.dealer_id = row.rule.dealer_id
        row.save(update_fields=['dealer'])


class Migration(migrations.Migration):
    dependencies = [('sales', '0113_user_calendar_view')]
    operations = [
        migrations.RemoveConstraint('dealervolumebonusrule', 'unique_dealer_volume_bonus_period'),
        migrations.AddField('dealervolumebonusrule', 'name', models.CharField('規則名稱', max_length=120, blank=True)),
        migrations.AlterField('dealervolumebonusrule', 'dealer', models.ForeignKey(blank=True, null=True, limit_choices_to={'source_type': 'dealer'}, on_delete=django.db.models.deletion.PROTECT, related_name='volume_bonus_rules', to='sales.salessource', verbose_name='合作車行')),
        migrations.AlterField('dealervolumebonusrule', 'brand', models.CharField('品牌', max_length=80, blank=True)),
        migrations.AddField('dealervolumebonusrule', 'energy_type', models.CharField('能源別', max_length=20, blank=True, choices=[('gas', '油車'), ('electric', '電動車'), ('light_electric', '輕型電動車'), ('micro_electric', '微型電動二輪車')])),
        migrations.AddField('dealervolumebonusrule', 'vehicle_models', models.ManyToManyField(blank=True, related_name='volume_bonus_rules', to='sales.vehiclemodel', verbose_name='指定車型')),
        migrations.AddField('dealervolumebonussettlement', 'dealer', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='volume_bonus_settlements', to='sales.salessource', verbose_name='收款車行')),
        migrations.RunPython(backfill_dealer, migrations.RunPython.noop),
        migrations.AlterField('dealervolumebonussettlement', 'dealer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='volume_bonus_settlements', to='sales.salessource', verbose_name='收款車行')),
        migrations.AlterField('dealervolumebonussettlement', 'rule', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='settlements', to='sales.dealervolumebonusrule', verbose_name='台數獎金規則')),
        migrations.AddConstraint('dealervolumebonussettlement', models.UniqueConstraint(fields=('rule', 'dealer'), name='unique_bonus_rule_dealer_settlement')),
    ]
