"""現有台數表：依品牌＋車種分類分區、原廠型號分組，逐車色列出本店現有台數（使用者 2026-11-03 簡報第 7 頁）。

口徑（2026-11-03 方案 A）：與車輛庫存頁「現有庫存」分頁相同，可銷售＋已預留（已配車）＋車況異常；
已交車、已售出、已調出、停用不算。「數量」含放在車行的車，「車行」是其中 current_dealer 有值的台數。
0 台的車色照列；車色停用或該型號所有版本停用標「不生產」。停用且沒有車的型號不列。
"""
from dataclasses import dataclass, field

from django.db.models import Count, F, Q

from sales.models import VehicleBrand, VehicleColor, VehicleInventory, VehicleModel
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
class ColorRow:
    name: str
    total: int = 0
    dealer: int = 0
    reserved: int = 0
    issue: int = 0
    active: bool = False

    @property
    def store(self):
        return self.total - self.dealer


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
            # 車色順序固定（依名稱），每次看位置都一樣；不生產且 0 台的放最後。
            group.colors = dict(sorted(group.colors.items(), key=lambda item: (not item[1].active and not item[1].total, item[1].name)))
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
