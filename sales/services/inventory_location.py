"""庫存「實際位置」選項（T-230 B）與列表直接改位置（T-308 B）共用。

實際位置＝`current_dealer`（車行，空白＝在本店）＋`location_store`（本店門市馭盛／永湛）。
選單最上面固定本店門市（值 home-<門市 pk>），下面是啟用中的車行（值＝車行 pk）；
這台車目前放的車行即使已停用，也列在選單裡，表示「維持原位」。
編輯表單與庫存列表共用這裡的選項，兩邊顯示與存法一致。
"""
from django.db.models import Q

from sales.models import SalesSource
from sales.services.home_stores import home_location_stores

HOME_PREFIX = "home-"
# 沒有本店門市資料時沿用舊選單：值空白＝本店。
LEGACY_HOME_VALUE = ""


def location_dealer_queryset(current_dealer_id=None):
    """啟用中的車行，加上目前放的車行（即使已停用），依名稱排序。"""
    condition = Q(active=True, source_type=SalesSource.SourceType.DEALER)
    if current_dealer_id:
        condition |= Q(pk=current_dealer_id)
    return SalesSource.objects.filter(condition).order_by("name")


def home_location_map():
    """{"home-<pk>": Store}，馭盛在前；沒有本店門市資料時為空。"""
    return {f"{HOME_PREFIX}{store.pk}": store for store in home_location_stores()}


def location_choice_list(home_locations, dealers):
    """[(值, 顯示名稱)]：本店門市在前，再來是車行。dealers 為 {"<pk>": SalesSource}。"""
    return [(value, f"本店：{store.name}") for value, store in home_locations.items()] + [
        (value, dealer.name) for value, dealer in dealers.items()
    ]


def current_location_value(vehicle, home_locations):
    """這台車在選單上的值，規則同編輯表單的預設選取。"""
    if vehicle.current_dealer_id:
        return str(vehicle.current_dealer_id)
    if not home_locations:
        return LEGACY_HOME_VALUE
    home_value = f"{HOME_PREFIX}{vehicle.location_store_id}"
    return home_value if home_value in home_locations else next(iter(home_locations))


class LocationOptions:
    """一頁庫存列表共用的一份位置選項（不每列各放一份完整選單）。"""

    def __init__(self):
        self.home_locations = home_location_map()
        self.dealers = {str(dealer.pk): dealer for dealer in location_dealer_queryset()}

    @property
    def home_choices(self):
        if not self.home_locations:
            return [(LEGACY_HOME_VALUE, "本店")]
        return location_choice_list(self.home_locations, {})

    @property
    def dealer_choices(self):
        return location_choice_list({}, self.dealers)

    def value_for(self, vehicle):
        return current_location_value(vehicle, self.home_locations)

    def label_for(self, vehicle):
        return current_location_option_label(vehicle, self.home_locations)


def current_location_option_label(vehicle, home_locations):
    """選單上這台車目前選項的文字（和完整選項一致，例如「本店：馭盛」）。"""
    value = current_location_value(vehicle, home_locations)
    if value in home_locations:
        return f"本店：{home_locations[value].name}"
    if vehicle.current_dealer_id:
        return vehicle.current_dealer.name
    return "本店"


def resolve_location(vehicle, value, home_locations):
    """選項值換成 (車行, 門市)。不在選單上的值回傳 None。

    選本店門市＝清空車行、改實際存放門市；選車行＝只改車行，門市不變（同編輯表單）。
    """
    value = str(value if value is not None else "")
    if value in home_locations:
        return None, home_locations[value]
    if not home_locations and value == LEGACY_HOME_VALUE:
        return None, vehicle.location_store
    if not value.isdigit():
        return None
    dealer = location_dealer_queryset(vehicle.current_dealer_id).filter(pk=int(value)).first()
    if dealer is None:
        return None
    return dealer, vehicle.location_store
