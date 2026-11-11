from django.db import migrations

# 使用者 2026-11-11 T-149 方案 A：原廠獎勵與補助、車行附加獎勵改成活動制。
# 既有的車型版本一對一轉成活動（指定年式＝原車型），舊表與舊資料保留不動（先擴充、後收斂）。
# 原廠：轉成「常態」活動，全部通路適用、促銷補助只給網路平台，與轉換前的套用結果相同。
# 車行附加：轉成全部車行適用的活動，項目與成本快照照抄。
# 已轉換過的版本（legacy_* 已有活動）略過，重跑不重複建立；reverse 只刪除由轉換建立的活動。


def _model_label(model):
    parts = [model.brand, model.name]
    if model.model_year:
        parts.append(f"{model.model_year} 年式")
    return " ".join(part for part in parts if part)


def convert(apps, schema_editor):
    Rule = apps.get_model("sales", "VehicleIncentiveRule")
    Campaign = apps.get_model("sales", "IncentiveCampaign")
    Plan = apps.get_model("sales", "DealerVehicleRewardPlan")
    RewardCampaign = apps.get_model("sales", "DealerRewardCampaign")
    RewardItem = apps.get_model("sales", "DealerRewardCampaignItem")

    for rule in Rule.objects.select_related("vehicle_model").order_by("pk"):
        if Campaign.objects.filter(legacy_rule_id=rule.pk).exists():
            continue
        campaign = Campaign.objects.create(
            name=f"{_model_label(rule.vehicle_model)} 原廠獎勵"[:120],
            kind="regular",
            brands=[],
            energy_types=[],
            source_types=[],
            promotion_source_types=["platform"],
            sales_bonus=rule.sales_bonus,
            promotion_subsidy=rule.promotion_subsidy,
            installment_interest_subsidy=rule.installment_interest_subsidy,
            announced_on=rule.announced_on,
            effective_from=rule.effective_from,
            effective_to=rule.effective_to,
            note=rule.note,
            active=rule.active,
            legacy_rule_id=rule.pk,
        )
        campaign.vehicle_models.add(rule.vehicle_model_id)

    for plan in Plan.objects.select_related("vehicle_model").prefetch_related("items").order_by("pk"):
        if RewardCampaign.objects.filter(legacy_plan_id=plan.pk).exists():
            continue
        campaign = RewardCampaign.objects.create(
            name=f"{_model_label(plan.vehicle_model)} 附加獎勵"[:120],
            brands=[],
            energy_types=[],
            effective_from=plan.effective_from,
            effective_to=plan.effective_to,
            note=plan.note,
            active=plan.active,
            legacy_plan_id=plan.pk,
        )
        campaign.vehicle_models.add(plan.vehicle_model_id)
        for item in plan.items.all().order_by("pk"):
            RewardItem.objects.create(
                campaign=campaign,
                catalog_item_id=item.catalog_item_id,
                reward_type=item.reward_type,
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                unit_cost_snapshot=item.unit_cost_snapshot,
                cost_effective_on_snapshot=item.cost_effective_on_snapshot,
                note=item.note,
            )


def unconvert(apps, schema_editor):
    apps.get_model("sales", "IncentiveCampaign").objects.filter(legacy_rule__isnull=False).delete()
    apps.get_model("sales", "DealerRewardCampaign").objects.filter(legacy_plan__isnull=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0202_incentive_campaigns"),
    ]

    operations = [
        migrations.RunPython(convert, unconvert),
    ]
