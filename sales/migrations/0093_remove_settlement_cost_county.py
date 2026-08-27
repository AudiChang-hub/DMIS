from django.db import migrations, models
from django.db.models import Count


def consolidate_same_day_rules(apps, schema_editor):
    Rule = apps.get_model("sales", "VehicleSettlementCostRule")
    OperationsProfile = apps.get_model("sales", "OrderOperationsProfile")

    duplicate_groups = (
        Rule.objects.values("vehicle_model_id", "effective_from")
        .annotate(rule_count=Count("id"))
        .filter(rule_count__gt=1)
    )
    for group in duplicate_groups:
        rules = list(
            Rule.objects.filter(
                vehicle_model_id=group["vehicle_model_id"],
                effective_from=group["effective_from"],
            ).order_by("-updated_at", "-id")
        )
        keeper = rules[0]
        duplicate_ids = [rule.id for rule in rules[1:]]
        OperationsProfile.objects.filter(
            vehicle_cost_rule_id__in=duplicate_ids
        ).update(vehicle_cost_rule_id=keeper.id)
        Rule.objects.filter(id__in=duplicate_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0092_remove_subsidy_application_pseudo_source"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="vehiclesettlementcostrule",
            name="unique_settlement_cost_rule_start",
        ),
        migrations.RemoveIndex(
            model_name="vehiclesettlementcostrule",
            name="settlement_cost_lookup",
        ),
        migrations.RunPython(
            consolidate_same_day_rules,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="vehiclesettlementcostrule",
            name="registration_county",
        ),
        migrations.RemoveField(
            model_name="orderoperationsprofile",
            name="vehicle_cost_county",
        ),
        migrations.AlterModelOptions(
            name="vehiclesettlementcostrule",
            options={
                "ordering": ["vehicle_model", "-effective_from", "-id"],
                "verbose_name": "代銷結算成本規則",
                "verbose_name_plural": "代銷結算成本規則",
            },
        ),
        migrations.AddConstraint(
            model_name="vehiclesettlementcostrule",
            constraint=models.UniqueConstraint(
                fields=("vehicle_model", "effective_from"),
                name="unique_settlement_cost_rule_start",
            ),
        ),
        migrations.AddIndex(
            model_name="vehiclesettlementcostrule",
            index=models.Index(
                fields=["vehicle_model", "effective_from"],
                name="settlement_cost_lookup",
            ),
        ),
    ]
