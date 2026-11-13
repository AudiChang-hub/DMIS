"""T-161（使用者 2026-11-13 逐項確認）：原廠獎勵活動改為項目列，既有活動整理成依品牌合併的活動。

- 正式站形狀（全部活動都是 2.1.0 由車型版本轉來、未改過）：同品牌、同金額、同期間的年式合併成一個活動
  （指定年式，不用品牌條件），促銷另建「促銷補助（網路平台）」只勾網路平台；0 元項目不建列。
  舊活動全部停用保留，名稱前加「（已整理）」，備註寫整理到哪個新活動。
- 其他形狀：逐筆轉成項目列（三項含 0 都建列），通路空白轉三個全勾；促銷限通路時另建兄弟活動，
  每個年式 × 通路的結果與轉換前相同。
- `build_plan(apps)` 只讀資料、不寫入，可在正式站唯讀執行當作 dry-run。
- 反向：依 conversion_batch 還原舊活動、移除項目列；新建的活動沒被訂單採用就刪除，有被採用就停用。
"""
from collections import OrderedDict

from django.db import migrations

BATCH = "t161"
MERGED = "t161-merged"
ITEMS = ("sales_bonus", "promotion_subsidy", "installment_interest_subsidy")
ALL_SOURCES = ["store", "dealer", "platform"]
SOURCE_LABELS = {"store": "本店", "dealer": "車行", "platform": "網路平台"}
PREFIX = "（已整理）"
# 使用者確認的名稱（2026-11-13）；其他群組用品牌，單一年式用「品牌 車名」。
GROUP_NAMES = {
    ("suzuki", frozenset({"SUI 125", "Saluto 125", "New NEX 125", "Swish 125"})): "SUZUKI 速克達",
    ("suzuki", frozenset({"Gixxer 250"})): "Gixxer 250",
    ("suzuki", frozenset({"Gixxer SF 250"})): "Gixxer SF 250",
}


def _models(campaign):
    return list(campaign.vehicle_models.all().order_by("pk"))


def _consolidatable(campaigns):
    """全部活動都是未改過的轉換形狀，才依品牌合併；否則逐筆轉換。"""
    if not campaigns:
        return False
    for campaign in campaigns:
        if not (campaign.active and campaign.kind == "regular" and campaign.legacy_rule_id
                and not campaign.brands and not campaign.energy_types and not campaign.source_types
                and len(_models(campaign)) == 1
                and not (hasattr(campaign, "dealers") and campaign.dealers.exists())):
            return False
    return True


def _short_name(model):
    name = model.name
    if name.lower().startswith(model.brand.lower() + " "):
        name = name[len(model.brand) + 1:]
    return f"{name} {model.model_year}".strip() if model.model_year else name


def _group_label(brand, models):
    key = (brand.casefold(), frozenset(model.name for model in models))
    if key in GROUP_NAMES:
        return GROUP_NAMES[key]
    return brand if len(models) > 1 else f"{brand} {models[0].name}"


def _consolidation_plan(campaigns):
    groups = OrderedDict()
    for campaign in campaigns:
        model = _models(campaign)[0]
        key = (model.brand.casefold(), campaign.sales_bonus, campaign.promotion_subsidy,
               campaign.installment_interest_subsidy, campaign.effective_from, campaign.effective_to,
               tuple(campaign.promotion_source_types or []))
        groups.setdefault(key, []).append((campaign, model))
    plan = []
    for (_brand, sales, promo, interest, start, end, promo_sources), rows in groups.items():
        models = [model for _campaign, model in rows]
        label = _group_label(rows[0][1].brand, models)
        announced = min(campaign.announced_on for campaign, _model in rows)
        later = OrderedDict()
        for campaign, model in rows:
            if campaign.announced_on != announced:
                later.setdefault(campaign.announced_on, []).append(_short_name(model))
        note = "；".join(f"{'、'.join(names)} 公告日 {day.month}/{day.day:02d}" for day, names in later.items())
        common = {"effective_from": start, "effective_to": end, "announced_on": announced, "note": note,
                  "model_ids": [model.pk for model in models], "source_campaign_ids": [c.pk for c, _m in rows]}
        main_items = {item: amount for item, amount in (("sales_bonus", sales), ("installment_interest_subsidy", interest))
                      if amount}
        if main_items:
            plan.append({**common, "name": f"{label} 原廠獎勵", "source_types": list(ALL_SOURCES), "items": main_items})
        if promo:
            sources = [value for value in ALL_SOURCES if not promo_sources or value in promo_sources]
            suffix = "、".join(SOURCE_LABELS[value] for value in sources)
            plan.append({**common, "name": f"{label} 促銷補助（{suffix}）", "source_types": sources,
                         "items": {"promotion_subsidy": promo}})
    return plan


def build_plan(apps):
    """只讀：回傳 {"mode": "consolidate"|"convert", "create": [...], "retire": [...], "convert": [...]}。"""
    Campaign = apps.get_model("sales", "IncentiveCampaign")
    campaigns = Campaign.objects.all()
    if any(field.name == "conversion_batch" for field in Campaign._meta.get_fields()):
        campaigns = campaigns.filter(conversion_batch="")  # dry-run 也能在 2.4.0（沒有這個欄位）唯讀執行
    campaigns = list(campaigns.order_by("pk"))
    if _consolidatable(campaigns):
        return {"mode": "consolidate", "create": _consolidation_plan(campaigns),
                "retire": [campaign.pk for campaign in campaigns], "convert": []}
    return {"mode": "convert", "create": [], "retire": [], "convert": [campaign.pk for campaign in campaigns]}


def _create_campaign(Campaign, Item, row, kind="regular", **extra):
    campaign = Campaign.objects.create(
        name=row["name"][:120], kind=kind, brands=[], energy_types=[], source_types=row["source_types"],
        effective_from=row["effective_from"], effective_to=row["effective_to"], announced_on=row["announced_on"],
        note=row["note"], active=row.get("active", True), conversion_batch=BATCH, **extra,
    )
    campaign.vehicle_models.set(row["model_ids"])
    for item, amount in row["items"].items():
        Item.objects.create(campaign=campaign, item=item, amount=amount)
    return campaign


def _convert_one(Campaign, Item, campaign):
    """逐筆轉換：三項含 0 都建列；促銷限通路時拆出兄弟活動，維持每個通路的結果。"""
    channels = list(campaign.source_types) or list(ALL_SOURCES)
    promo_sources = list(campaign.promotion_source_types or []) or list(ALL_SOURCES)
    given = [value for value in channels if value in promo_sources]
    zero = [value for value in channels if value not in promo_sources]
    campaign.source_types = channels
    campaign.save(update_fields=["source_types"])
    Item.objects.create(campaign=campaign, item="sales_bonus", amount=campaign.sales_bonus)
    Item.objects.create(campaign=campaign, item="installment_interest_subsidy", amount=campaign.installment_interest_subsidy)
    if not zero:
        Item.objects.create(campaign=campaign, item="promotion_subsidy", amount=campaign.promotion_subsidy)
        return
    base = {"effective_from": campaign.effective_from, "effective_to": campaign.effective_to,
            "announced_on": campaign.announced_on, "note": campaign.note, "active": campaign.active,
            "model_ids": list(campaign.vehicle_models.values_list("pk", flat=True))}
    for sources, amount in ((given, campaign.promotion_subsidy), (zero, 0)):
        if not sources:
            continue
        label = "、".join(SOURCE_LABELS[value] for value in sources)
        sibling = _create_campaign(Campaign, Item, {**base, "name": f"{campaign.name} 促銷補助（{label}）",
                                                    "source_types": sources, "items": {"promotion_subsidy": amount}},
                                   kind=campaign.kind)
        sibling.brands, sibling.energy_types = campaign.brands, campaign.energy_types
        sibling.save(update_fields=["brands", "energy_types"])
        sibling.dealers.set(campaign.dealers.all())
    campaign.conversion_batch = f"{BATCH}-split"
    campaign.save(update_fields=["conversion_batch"])


def forwards(apps, schema_editor):
    Campaign = apps.get_model("sales", "IncentiveCampaign")
    Item = apps.get_model("sales", "IncentiveCampaignItem")
    plan = build_plan(apps)
    if plan["mode"] == "convert":
        for campaign in Campaign.objects.filter(pk__in=plan["convert"]).order_by("pk"):
            _convert_one(Campaign, Item, campaign)
        return
    targets = {}
    for row in plan["create"]:
        campaign = _create_campaign(Campaign, Item, row)
        for source_id in row["source_campaign_ids"]:
            targets.setdefault(source_id, []).append(campaign.name)
    for campaign in Campaign.objects.filter(pk__in=plan["retire"]).order_by("pk"):
        # 舊活動保留做追溯：項目列照原金額建（顯示用），停用後不會套用。
        for item in ITEMS:
            amount = getattr(campaign, item)
            if amount:
                Item.objects.create(campaign=campaign, item=item, amount=amount)
        campaign.name = (PREFIX + campaign.name)[:120]
        line = "已整理至：" + "、".join(targets.get(campaign.pk, []))
        campaign.note = f"{campaign.note}\n{line}" if campaign.note else line
        campaign.active = False
        campaign.conversion_batch = MERGED
        campaign.save(update_fields=["name", "note", "active", "conversion_batch"])


def backwards(apps, schema_editor):
    Campaign = apps.get_model("sales", "IncentiveCampaign")
    Item = apps.get_model("sales", "IncentiveCampaignItem")
    for campaign in Campaign.objects.filter(conversion_batch=BATCH):
        if campaign.order_applications.exists():
            campaign.active = False
            campaign.save(update_fields=["active"])
        else:
            campaign.delete()
    for campaign in Campaign.objects.filter(conversion_batch=MERGED):
        campaign.name = campaign.name[len(PREFIX):] if campaign.name.startswith(PREFIX) else campaign.name
        lines = campaign.note.split("\n")
        campaign.note = "\n".join(lines[:-1]) if lines and lines[-1].startswith("已整理至：") else campaign.note
        campaign.active = True
        campaign.source_types = []
        campaign.conversion_batch = ""
        campaign.save(update_fields=["name", "note", "active", "source_types", "conversion_batch"])
    for campaign in Campaign.objects.filter(conversion_batch=f"{BATCH}-split"):
        campaign.conversion_batch = ""
        campaign.save(update_fields=["conversion_batch"])
    Item.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0207_incentive_campaign_items"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
