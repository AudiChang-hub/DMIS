"""測試共用：原廠獎勵與車行附加獎勵改為活動制（T-149；T-161 改為項目列）。

既有測試以「車型版本」描述情境；`legacy_incentive_rule` 先建立舊版本，再依序執行正式的轉換 migration：
0203 轉成活動，0208 的逐筆轉換改成項目列（促銷只給網路平台的部分拆成兄弟活動），驗證轉換後行為不變。
正式站的「依品牌整理」路徑另由 test_incentive_campaign_migration、test_incentive_campaigns 驗證。
"""
import importlib
import pkgutil

from django.apps import apps

import sales.migrations
from sales.models import IncentiveCampaign, IncentiveCampaignItem, VehicleIncentiveRule


def _migration(suffix):
    for module in pkgutil.iter_modules(sales.migrations.__path__):
        if module.name.endswith(suffix):
            return importlib.import_module(f"sales.migrations.{module.name}")
    raise LookupError(f"找不到 migration：{suffix}")


def convert_legacy_versions():
    """執行轉換（已轉換過的略過），並模擬提交後重算未完成領牌的訂單。"""
    from sales.signals import _refresh_campaign_orders

    _migration("_convert_incentive_campaigns").convert(apps, None)
    items = _migration("_consolidate_incentive_campaigns")
    for campaign in IncentiveCampaign.objects.filter(conversion_batch="", items__isnull=True).order_by("pk"):
        items._convert_one(IncentiveCampaign, IncentiveCampaignItem, campaign)
    _refresh_campaign_orders()


def legacy_incentive_rule(**fields):
    rule = VehicleIncentiveRule.objects.create(**fields)
    convert_legacy_versions()
    return rule


def make_campaign(*, items, vehicle_models=(), dealers=(), refresh=True, **fields):
    """建立原廠獎勵活動：items 為 {項目: 金額}；通路預設三個全勾。"""
    from sales.signals import _refresh_campaign_orders

    campaign = IncentiveCampaign.objects.create(**fields)
    for item, amount in items.items():
        IncentiveCampaignItem.objects.create(campaign=campaign, item=item, amount=amount)
    if vehicle_models:
        campaign.vehicle_models.set(vehicle_models)
    if dealers:
        campaign.dealers.set(dealers)
    if refresh:
        _refresh_campaign_orders()
    return campaign
