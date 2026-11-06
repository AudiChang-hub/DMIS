"""現有台數表：依品牌＋車種分類分區、原廠型號分組，逐車色列出本店現有台數（使用者 2026-11-03 簡報第 7 頁）。

口徑（2026-11-03 方案 A）：與車輛庫存頁「現有庫存」分頁相同，可銷售＋已預留（已配車）＋車況異常；
已交車、已售出、已調出、停用不算。「數量」含放在車行的車，「車行」是其中 current_dealer 有值的台數。
0 台的車色照列；車色停用或該型號所有版本停用標「不生產」。停用且沒有車的型號不列。
庫位（T-115，使用者 2026-11-06）：每列寫出車實際放在哪裡、各幾台；current_dealer 空白寫實際存放門市（location_store）名稱，
有值寫車行名稱。門市依門市主檔順序排前面，車行接在後面、台數多的在前。
每台車明細（T-115，使用者 2026-11-06「庫位要細到每台車」）：引擎號碼（電動車為車身號碼）＋位置，已配車附訂單號、車況異常另標。
所有能看庫存的人都看得到，只放車的資料與訂單號，不放客戶個資。
"""
from dataclasses import dataclass, field

from django.db.models import Count, F, Q

from sales.models import Store, VehicleBrand, VehicleColor, VehicleInventory, VehicleModel
from sales.reporting.classification import classification_expression, published_snapshot

# 必須與 views.inventory_list 的 current_statuses 一致；test_stock_count 以庫存頁篩選結果鎖住。
CURRENT_STATUSES = (
    VehicleInventory.Status.AVAILABLE,
    VehicleInventory.Status.RESERVED,
    VehicleInventory.Status.CONDITION_ISSUE,
)


def _key(value):
    return (value or "").strip().casefold()


@dataclass
class StockVehicle:
    """明細一台車；位置規則同庫位摘要。"""
    pk: int
    engine_number: str
    frame_number: str
    place: str
    at_dealer: bool
    status: str
    order_number: str = ""
    registered: bool = False
    sort_key: tuple = ()

    @property
    def identifier(self):
        return self.engine_number or self.frame_number

    @property
    def is_reserved(self):
        return self.status == VehicleInventory.Status.RESERVED

    @property
    def is_issue(self):
        return self.status == VehicleInventory.Status.CONDITION_ISSUE

    @property
    def status_label(self):
        if self.is_reserved:
            return "已配車"
        return "車況異常" if self.is_issue else "可銷售"


@dataclass
class ColorRow:
    name: str
    total: int = 0
    dealer: int = 0
    reserved: int = 0
    issue: int = 0
    active: bool = False
    store_counts: dict = field(default_factory=dict)
    dealer_counts: dict = field(default_factory=dict)
    vehicles: list = field(default_factory=list)

    @property
    def store(self):
        return self.total - self.dealer

    @property
    def locations(self):
        """[(位置, 台數, 是否車行)]：門市依主檔順序在前，車行依台數多到少、同台數依名稱；0 台時為空。"""
        stores = sorted(self.store_counts.items(), key=lambda item: item[0][0])
        places = [(name, count, False) for (_, name), count in stores]
        dealers = sorted(self.dealer_counts.items(), key=lambda item: (-item[1], item[0]))
        return places + [(place, count, True) for place, count in dealers]

    @property
    def location_text(self):
        return "、".join(f"{place} {count}" for place, count, _ in self.locations)


@dataclass
class ModelGroup:
    code: str
    names: list = field(default_factory=list)
    family_ids: set = field(default_factory=set)
    brand: str = ""
    category: str = ""
    active: bool = False
    version_ids: set = field(default_factory=set)
    colors: dict = field(default_factory=dict)

    @property
    def rows(self):
        return list(self.colors.values())

    @property
    def total(self):
        return sum(row.total for row in self.colors.values())

    @property
    def dealer(self):
        return sum(row.dealer for row in self.colors.values())

    @property
    def subtitle(self):
        names = [name for name in self.names if _key(name) != _key(self.code)]
        return "／".join(names)


@dataclass
class Block:
    brand: str
    category: str
    order: tuple
    color: str = ""
    groups: list = field(default_factory=list)

    @property
    def title(self):
        return f"{self.brand} {self.category}"

    @property
    def total(self):
        return sum(group.total for group in self.groups)

    @property
    def dealer(self):
        return sum(group.dealer for group in self.groups)

    @property
    def color_count(self):
        return sum(len(group.colors) for group in self.groups)


def current_vehicles():
    return VehicleInventory.objects.filter(status__in=CURRENT_STATUSES)


def build_stock_count(brand=""):
    """回傳 {"blocks", "brands", "totals", "selected_brand"}；brand 為空或對不到時列出全部品牌。"""
    snapshot = published_snapshot()[0]
    category_order = {item["name"]: item["order"] for item in snapshot["categories"]}
    category_color = {item["name"]: item["color"] for item in snapshot["categories"]}
    brand_order = {_key(row.name): row.display_order for row in VehicleBrand.objects.only("name", "display_order")}

    counts = {}
    for row in (
        current_vehicles()
        .values("vehicle_model_id", "color_id")
        .annotate(
            total=Count("id"),
            dealer=Count("id", filter=Q(current_dealer__isnull=False)),
            reserved=Count("id", filter=Q(status=VehicleInventory.Status.RESERVED)),
            issue=Count("id", filter=Q(status=VehicleInventory.Status.CONDITION_ISSUE)),
        )
    ):
        counts[row["color_id"]] = row
    # 門市主檔順序（Store.Meta.ordering）；鍵帶順序值，同名不同門市不會合併。
    store_order = {pk: index for index, pk in enumerate(Store.objects.values_list("pk", flat=True))}
    store_counts = {}
    for row in (
        current_vehicles().filter(current_dealer__isnull=True)
        .values("color_id", "location_store_id", "location_store__name").annotate(total=Count("id"))
    ):
        key = ((store_order.get(row["location_store_id"], len(store_order)), row["location_store_id"]), row["location_store__name"].strip())
        store_counts.setdefault(row["color_id"], {})[key] = row["total"]
    vehicles = {}
    for item in (
        current_vehicles()
        .values(
            "pk", "color_id", "engine_number", "frame_number", "status", "registered_plate_number",
            "location_store_id", "location_store__name", "current_dealer_id", "current_dealer__name", "active_order__number",
        )
    ):
        at_dealer = item["current_dealer_id"] is not None
        vehicles.setdefault(item["color_id"], []).append(StockVehicle(
            pk=item["pk"], engine_number=item["engine_number"] or "", frame_number=item["frame_number"] or "",
            place=(item["current_dealer__name"] if at_dealer else item["location_store__name"]).strip(),
            at_dealer=at_dealer, status=item["status"], order_number=item["active_order__number"] or "",
            registered=bool(item["registered_plate_number"]),
            sort_key=(at_dealer, 0 if at_dealer else store_order.get(item["location_store_id"], len(store_order)),
                      (item["current_dealer__name"] or "") if at_dealer else "", item["engine_number"] or item["frame_number"] or ""),
        ))
    dealer_counts = {}
    for row in (
        current_vehicles().filter(current_dealer__isnull=False)
        .values("color_id", "current_dealer__name").annotate(total=Count("id"))
    ):
        place = row["current_dealer__name"].strip()
        dealer_counts.setdefault(row["color_id"], {}).setdefault(place, 0)
        dealer_counts[row["color_id"]][place] += row["total"]

    models = (
        VehicleModel.objects.annotate(report_source_model=F("model_number"))
        .annotate(report_category=classification_expression(snapshot))
        .order_by("brand", "model_number", "name", "id")
    )
    groups = {}
    for model in models:
        code = (model.model_number or "").strip() or model.name
        key = (_key(model.brand), _key(code))
        group = groups.get(key)
        if group is None:
            group = groups[key] = ModelGroup(code=code, brand=model.brand.strip(), category=model.report_category)
        if model.name not in group.names:
            group.names.append(model.name)
        if model.family_id:
            group.family_ids.add(model.family_id)
        group.active = group.active or model.active
        group.version_ids.add(model.pk)

    colors = VehicleColor.objects.filter(vehicle_model__in=[m.pk for m in models]).select_related("vehicle_model").order_by("id")
    model_group = {pk: group for group in groups.values() for pk in group.version_ids}
    for color in colors:
        group = model_group[color.vehicle_model_id]
        row = group.colors.get(_key(color.name))
        if row is None:
            row = group.colors[_key(color.name)] = ColorRow(name=color.name.strip())
        row.active = row.active or (color.active and color.vehicle_model.active)
        count = counts.get(color.pk)
        if count:
            row.total += count["total"]
            row.dealer += count["dealer"]
            row.reserved += count["reserved"]
            row.issue += count["issue"]
            row.vehicles = sorted(row.vehicles + vehicles.get(color.pk, []), key=lambda vehicle: vehicle.sort_key)
            for key, total in store_counts.get(color.pk, {}).items():
                row.store_counts[key] = row.store_counts.get(key, 0) + total
            for place, total in dealer_counts.get(color.pk, {}).items():
                row.dealer_counts[place] = row.dealer_counts.get(place, 0) + total

    brands = {}
    blocks = {}
    for group in groups.values():
        if not group.colors or not (group.active or group.total):
            continue
        brands.setdefault(_key(group.brand), {"value": group.brand, "total": 0})["total"] += group.total
        block_key = (_key(group.brand), group.category)
        block = blocks.get(block_key)
        if block is None:
            block = blocks[block_key] = Block(
                brand=group.brand, category=group.category, color=category_color.get(group.category, ""),
                order=(brand_order.get(_key(group.brand), 999), _key(group.brand), category_order.get(group.category, 999)),
            )
        block.groups.append(group)

    for block in blocks.values():
        block.groups.sort(key=lambda g: _key(g.code))
        for group in block.groups:
            # 車色依主檔建立順序（與機種頁一致），每次看位置都一樣；不生產且 0 台的放最後。
            group.colors = dict(sorted(group.colors.items(), key=lambda item: not item[1].active and not item[1].total))
    # 品牌對不到（例如網址打錯）時視同全部品牌，不顯示空白表。
    selected = brands.get(_key(brand), {}).get("value", "")
    ordered = sorted((b for b in blocks.values() if not selected or _key(b.brand) == _key(selected)), key=lambda b: b.order)
    totals = {
        "total": sum(b.total for b in ordered),
        "dealer": sum(b.dealer for b in ordered),
        "reserved": sum(row.reserved for b in ordered for g in b.groups for row in g.rows),
        "issue": sum(row.issue for b in ordered for g in b.groups for row in g.rows),
    }
    totals["store"] = totals["total"] - totals["dealer"]
    brand_choices = sorted(brands.values(), key=lambda item: (brand_order.get(_key(item["value"]), 999), _key(item["value"])))
    return {"blocks": ordered, "brands": brand_choices, "totals": totals, "selected_brand": selected}
