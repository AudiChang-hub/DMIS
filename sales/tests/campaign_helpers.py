"""測試共用：原廠獎勵與車行附加獎勵改為活動制（T-149）。

既有測試以「車型版本」描述情境；`legacy_incentive_rule` 先建立舊版本，再用正式的轉換 migration
轉成等效的常態活動（指定該年式、促銷只給網路平台），讓舊情境驗證轉換後的行為不變。
"""
import importlib
import pkgutil

from django.apps import apps

import sales.migrations
from sales.models import IncentiveCampaign, VehicleIncentiveRule


def _conversion_module():
    for module in pkgutil.iter_modules(sales.migrations.__path__):
        if module.name.endswith("_convert_incentive_campaigns"):
            return importlib.import_module(f"sales.migrations.{module.name}")
    raise LookupError("找不到原廠獎勵活動的轉換 migration")


def convert_legacy_versions():
    """執行轉換 migration 的資料轉換（已轉換過的略過），並模擬提交後重算未完成領牌的訂單。"""
    from sales.signals import _refresh_campaign_orders

    _conversion_module().convert(apps, None)
    _refresh_campaign_orders()


def legacy_incentive_rule(**fields):
    rule = VehicleIncentiveRule.objects.create(**fields)
    convert_legacy_versions()
    return rule


def incentive_campaign(*, vehicle_models=(), **fields):
    """直接建立活動並模擬提交後重算；條件欄位可用 brands、energy_types、vehicle_models。"""
    from sales.signals import _refresh_campaign_orders

    campaign = IncentiveCampaign.objects.create(**fields)
    if vehicle_models:
        campaign.vehicle_models.set(vehicle_models)
    _refresh_campaign_orders()
    return campaign
