from django.db import migrations


IN_HOUSE_SOURCE_NAMES = ("馭盛", "永湛")


def _replace_source_type(value):
    if isinstance(value, str):
        if value == "合作車行":
            return "本店"
        if value == "dealer":
            return "store"
        return value
    if isinstance(value, list):
        return [_replace_source_type(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_source_type(item) for key, item in value.items()}
    return value


def reclassify_in_house_sales_sources(apps, schema_editor):
    SalesSourceCategory = apps.get_model("sales", "SalesSourceCategory")
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SalesOrderSearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")
    OrderOperationsProfile = apps.get_model("sales", "OrderOperationsProfile")
    SalesSourceBrandPolicy = apps.get_model("sales", "SalesSourceBrandPolicy")
    SalesSourceCooperationProfile = apps.get_model(
        "sales", "SalesSourceCooperationProfile"
    )
    DealerVolumeBonusRule = apps.get_model("sales", "DealerVolumeBonusRule")

    store_category, _ = SalesSourceCategory.objects.get_or_create(
        name="馭盛",
        defaults={
            "system_behavior": "store",
            "active": True,
            "note": "馭盛與永湛等本店來源使用。",
        },
    )
    if store_category.system_behavior != "store":
        store_category.system_behavior = "store"
        store_category.active = True
        store_category.save(
            update_fields=["system_behavior", "active", "updated_at"]
        )

    sources = list(
        SalesSource.objects.filter(name__in=IN_HOUSE_SOURCE_NAMES).order_by("pk")
    )
    if not sources:
        return
    source_ids = [source.pk for source in sources]
    order_ids = list(
        SalesOrder.objects.filter(source_id__in=source_ids).values_list(
            "pk", flat=True
        )
    )

    # 尚未結算的規則是錯誤主檔，直接移除；若曾結算則保留歷史稽核資料，
    # 但服務層仍會拒絕把本店來源納入日後計算。
    DealerVolumeBonusRule.objects.filter(
        dealer_id__in=source_ids,
        settlement__isnull=True,
    ).delete()
    SalesSourceBrandPolicy.objects.filter(source_id__in=source_ids).delete()
    SalesSourceCooperationProfile.objects.filter(source_id__in=source_ids).delete()

    SalesOrder.objects.filter(pk__in=order_ids).update(source_type="store")
    OrderOperationsProfile.objects.filter(order_id__in=order_ids).update(
        dealer_name="",
        dealer_commission_base=0,
        dealer_commission_adjustment=0,
        dealer_commission_expense=0,
        dealer_commission_policy_id=None,
        dealer_commission_locked_at=None,
    )
    for search_index in SalesOrderSearchIndex.objects.filter(order_id__in=order_ids):
        search_index.search_text = (
            (search_index.search_text or "")
            .replace("合作車行", "本店")
            .replace("dealer", "store")
        )
        search_index.match_payload = _replace_source_type(
            search_index.match_payload
        )
        search_index.save(
            update_fields=["search_text", "match_payload", "updated_at"]
        )

    SalesSource.objects.filter(pk__in=source_ids).update(
        source_type="store",
        category_id=store_category.pk,
        has_line_group=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0094_remove_incentive_disbursement_rates"),
    ]

    operations = [
        migrations.RunPython(
            reclassify_in_house_sales_sources,
            migrations.RunPython.noop,
        ),
    ]
