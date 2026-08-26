from django.db import migrations, models
from django.db.models import Q


def migrate_cooperation_scopes(apps, schema_editor):
    Policy = apps.get_model("sales", "SalesSourceBrandPolicy")

    Policy.objects.filter(brand__iexact="SYM").update(
        brand="SYM",
        cooperation_scope="sym",
    )

    legacy_suzuki = list(
        Policy.objects.filter(brand__iexact="SUZUKI").order_by(
            "source_id", "effective_from", "id"
        )
    )
    for policy in legacy_suzuki:
        Policy.objects.filter(pk=policy.pk).update(
            brand="SUZUKI／油車",
            cooperation_scope="suzuki_gas",
        )
        Policy.objects.update_or_create(
            source_id=policy.source_id,
            cooperation_scope="suzuki_electric",
            effective_from=policy.effective_from,
            defaults={
                "brand": "SUZUKI／電車",
                "cooperates": policy.cooperates,
                "commission_adjustment": policy.commission_adjustment,
                "effective_to": policy.effective_to,
                "note": policy.note,
            },
        )

    for policy in Policy.objects.filter(brand__iexact="eMOVING").order_by(
        "source_id", "effective_from", "id"
    ):
        electric_exists = Policy.objects.filter(
            source_id=policy.source_id,
            cooperation_scope="suzuki_electric",
            effective_from=policy.effective_from,
        ).exists()
        if electric_exists:
            continue
        Policy.objects.filter(pk=policy.pk).update(
            brand="SUZUKI／電車",
            cooperation_scope="suzuki_electric",
        )


def reverse_cooperation_scopes(apps, schema_editor):
    Policy = apps.get_model("sales", "SalesSourceBrandPolicy")
    Policy.objects.filter(cooperation_scope="suzuki_electric").delete()
    Policy.objects.filter(cooperation_scope="suzuki_gas").update(
        brand="SUZUKI",
        cooperation_scope=None,
    )
    Policy.objects.filter(cooperation_scope="sym").update(
        brand="SYM",
        cooperation_scope=None,
    )


class Migration(migrations.Migration):
    dependencies = [("sales", "0083_alter_vehicleinventory_current_dealer")]

    operations = [
        migrations.AddField(
            model_name="salessourcebrandpolicy",
            name="cooperation_scope",
            field=models.CharField(
                blank=True,
                choices=[
                    ("sym", "三陽 SYM"),
                    ("suzuki_gas", "台鈴油車"),
                    ("suzuki_electric", "台鈴電車"),
                ],
                help_text="目前只區分三陽、台鈴油車與台鈴電車。",
                max_length=30,
                null=True,
                verbose_name="合作類別",
            ),
        ),
        migrations.RunPython(migrate_cooperation_scopes, reverse_cooperation_scopes),
        migrations.AddConstraint(
            model_name="salessourcebrandpolicy",
            constraint=models.UniqueConstraint(
                condition=Q(cooperation_scope__isnull=False),
                fields=("source", "cooperation_scope", "effective_from"),
                name="unique_source_scope_policy_start",
            ),
        ),
        migrations.AddIndex(
            model_name="salessourcebrandpolicy",
            index=models.Index(
                fields=["source", "cooperation_scope", "effective_from"],
                name="source_scope_policy_lookup",
            ),
        ),
        migrations.AlterField(
            model_name="salessourcebrandpolicy",
            name="brand",
            field=models.CharField(
                help_text="保留舊資料相容；新設定請使用合作類別。",
                max_length=80,
                verbose_name="歷史品牌值",
            ),
        ),
    ]
