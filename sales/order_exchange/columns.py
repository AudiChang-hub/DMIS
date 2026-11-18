"""訂單匯出的欄位宣告（T-232 方案 A）。

每一欄只在這裡宣告一次：代碼、名稱、群組、取值、格式，以及之後的回匯能不能修改（`editable`）。
`editable` 只列第一批可回匯欄位（方案第四節第 1 點），都是訂單頁自動儲存表單能改、而且不連動金額的欄位；
金額、狀態、算出來的值、已鎖定的財務、領牌日與車牌、車型車色、子表一律只能看。
車控與電池密碼不在任何群組裡，永遠不會被匯出。
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from django.utils import timezone

from sales.models import OrderOperationsProfile, SalesOrder

TEXT, DATE, MONEY, NUMBER, BOOL = "text", "date", "money", "number", "bool"
# 匯出／預覽上限（方案 Q8）。
EXPORT_LIMIT = 5000
PREVIEW_ROWS = 50


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    group: str
    getter: Callable[[SalesOrder], Any]
    kind: str = TEXT
    editable: bool = False
    choices: tuple = ()
    permission: str = ""  # 欄位層級另需的授權（見 GROUP_PERMISSION／COLUMN_PERMISSION）


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    hint: str
    sensitive: str = ""  # pii／finance／profit：預設不勾，勾了顯示提醒
    permission: str = ""


GROUPS = (
    Group("order", "訂單基本", "編號、狀態、日期、來源與車輛"),
    Group("owner", "車主", "姓名、聯絡方式與地址"),
    Group("pii", "個資", "證件號碼、生日、舊車主證號、補助撥款帳戶", sensitive="pii"),
    Group("delivery", "交車與選號", "交車方式、選號與訂單備註"),
    Group("trade_in", "汰舊補助", "舊車牌與舊車主"),
    Group("old_vehicle", "舊車與報廢", "舊車引擎號碼、廠牌、報廢與回收日期"),
    Group("fulfillment", "車控與電池", "帳號與合約（不含密碼）"),
    Group("pricing", "金額與付款", "成交車價、牌險、付款方式、尾款與配件"),
    Group("finance", "收支", "實際車價收入、成本與各項收入支出", sensitive="finance", permission="finance"),
    Group("profit", "淨利", "單筆淨利", sensitive="profit", permission="profit"),
)
GROUP_BY_KEY = {group.key: group for group in GROUPS}


def _profile(order):
    try:
        return order.operations
    except OrderOperationsProfile.DoesNotExist:
        return None


def _op(name):
    def getter(order):
        profile = _profile(order)
        return getattr(profile, name, None) if profile else None
    return getter


def _attr(name):
    return lambda order: getattr(order, name)


def _display(name):
    return lambda order: getattr(order, f"get_{name}_display")() if getattr(order, name) else ""


def _local_date(value):
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def _accessories(order):
    return "；".join(
        f"{line.name}×{line.quantity} {line.amount:,.0f}" if line.quantity != 1 else f"{line.name} {line.amount:,.0f}"
        for line in order.accessories.all()
    )


def _other_fees(order):
    return "；".join(f"{line.name} {line.amount:,.0f}" for line in order.other_fees.all())


def _registration(order):
    if not order.registration_date:
        return None
    return order.registration_date


def _registration_state(order):
    if not order.registration_date:
        return ""
    return "已確認" if order.registration_completed_at else "預計"


def _net_profit(order):
    profile = _profile(order)
    if order.is_cancelled_sale or profile is None:
        return None
    return profile.net_profit


def _choices(field_name, model=SalesOrder):
    return tuple(label for _value, label in model._meta.get_field(field_name).choices)


def _verbose(name):
    return str(OrderOperationsProfile._meta.get_field(name).verbose_name)


_base = [
    Column("number", "訂單編號", "order", _attr("number")),
    Column("status", "訂單狀態", "order", _display("status")),
    Column("established_on", "訂單成立日", "order", _attr("established_on"), DATE),
    Column("order_date", "訂單日期", "order", _attr("order_date"), DATE),
    Column("source", "訂單來源", "order", lambda o: o.source_display),
    Column("commission_recipient", "台數與傭金歸屬", "order", lambda o: str(o.effective_commission_recipient or "")),
    Column("vehicle_model", "車種", "order", lambda o: o.vehicle_model.name),
    Column("model_number", "型號", "order", lambda o: o.vehicle_model.model_number),
    Column("color", "車色", "order", lambda o: o.color.label if o.color_id else ""),
    Column("vehicle_identifier", "引擎／車身號碼", "order", lambda o: o.allocated_vehicle.identifier if o.allocated_vehicle_id else ""),
    Column("registration_date", "領牌日", "order", _registration, DATE),
    Column("registration_state", "領牌日狀態", "order", _registration_state),
    Column("final_plate_number", "車牌號碼", "order", _attr("final_plate_number")),
    Column("delivered_at", "交車日", "order", lambda o: _local_date(o.delivered_at), DATE),
    Column("closed_at", "結案日", "order", lambda o: _local_date(o.closed_at), DATE),

    Column("owner_type", "車主類型", "owner", _display("owner_type"), editable=True, choices=_choices("owner_type")),
    Column("owner_name", "車主姓名／公司名稱", "owner", _attr("owner_name"), editable=True),
    Column("owner_name_en", "英文姓名", "owner", _attr("owner_name_en"), editable=True),
    Column("owner_phone", "電話", "owner", _attr("owner_phone"), editable=True),
    Column("owner_email", "Email", "owner", _attr("owner_email"), editable=True),
    Column("owner_address", "戶籍／公司地址", "owner", _attr("owner_address"), editable=True),
    Column("owner_nationality", "國籍", "owner", _attr("owner_nationality"), editable=True),
    Column("residence_expiry", "居留期限", "owner", _attr("residence_expiry"), DATE, editable=True),

    Column("owner_id_number", "證件號碼／統一編號", "pii", _attr("owner_id_number"), editable=True),
    Column("owner_birth_date", "生日", "pii", _attr("owner_birth_date"), DATE, editable=True),
    Column("old_owner_id_number", "舊車主身分證號", "pii", _attr("old_owner_id_number"), editable=True),
    Column("bank_name", "補助撥款銀行", "pii", _op("bank_name"), permission="payout_account"),
    Column("remittance_account", "補助匯款帳戶", "pii", _op("remittance_account"), permission="payout_account"),

    Column("delivery_method", "交車方式", "delivery", _display("delivery_method"), editable=True, choices=_choices("delivery_method")),
    Column("delivery_destination", "自送托運地點", "delivery", _attr("delivery_destination"), editable=True),
    Column("plate_choice", "選號方式", "delivery", _display("plate_choice"), editable=True, choices=_choices("plate_choice")),
    Column("watched_numbers", "指定號碼與志願序", "delivery", _attr("watched_numbers"), editable=True),
    Column("plate_preference_note", "領牌偏好備註", "delivery", _attr("plate_preference_note"), editable=True),
    Column("note", "訂單備註", "delivery", _attr("note"), editable=True),
    Column("trade_in_intent", "是否有汰舊", "delivery", _display("trade_in_intent"), editable=True, choices=_choices("trade_in_intent")),

    Column("trade_in_plate", "舊車車牌", "trade_in", _attr("trade_in_plate"), editable=True),
    Column("old_owner_same_as_owner", "舊車主同新車主", "trade_in", _attr("old_owner_same_as_owner"), BOOL, editable=True, choices=("是", "否")),
    Column("old_owner_name", "舊車主姓名", "trade_in", _attr("old_owner_name"), editable=True),
    Column("old_owner_phone", "舊車主電話", "trade_in", _attr("old_owner_phone"), editable=True),

    Column("old_vehicle_engine_number", "舊車引擎號碼", "old_vehicle", _op("old_vehicle_engine_number"), editable=True),
    Column("old_vehicle_brand", "舊車廠牌", "old_vehicle", _op("old_vehicle_brand"), editable=True),
    Column("old_vehicle_displacement_cc", "舊車排氣量", "old_vehicle", _op("old_vehicle_displacement_cc"), NUMBER, editable=True),
    # 出廠年月與畫面輸入一致用 6 碼 YYYYMM（T-93）。
    Column("old_vehicle_manufactured_on", "舊車出廠年月", "old_vehicle",
           lambda o: (lambda v: f"{v.year:04d}{v.month:02d}" if v else "")(_op("old_vehicle_manufactured_on")(o)), editable=True),
    Column("scrapped_on", "報廢日期", "old_vehicle", _op("scrapped_on"), DATE, editable=True),
    Column("recycled_on", "回收日期", "old_vehicle", _op("recycled_on"), DATE, editable=True),

    Column("vehicle_control_account", "車控帳號", "fulfillment", _op("vehicle_control_account"), editable=True),
    Column("battery_plan", "電池合約方案", "fulfillment", _op("battery_plan"), editable=True),
    Column("battery_activated_on", "電池合約啟用日期", "fulfillment", _op("battery_activated_on"), DATE, editable=True),
    Column("battery_account", "電池合約帳號", "fulfillment", _op("battery_account"), editable=True),
    Column("battery_rate_plan", "車控與電池備註", "fulfillment", _op("battery_rate_plan"), editable=True),
    Column("vehicle_control_confirmed", "車控與電池已確認", "fulfillment", lambda o: bool(_op("vehicle_control_confirmed_at")(o)), BOOL),

    Column("vehicle_price", "成交車價", "pricing", _attr("vehicle_price"), MONEY),
    Column("plate_insurance_fee", "牌險費", "pricing", _attr("plate_insurance_fee"), MONEY),
    Column("plate_selection_fee", "選號費", "pricing", _attr("plate_selection_fee"), MONEY),
    Column("approved_discount_amount", "總價優惠", "pricing", _attr("approved_discount_amount"), MONEY),
    Column("discounted_total", "優惠後總價", "pricing", lambda o: o.discounted_total, MONEY),
    Column("deposit_amount", "訂金", "pricing", _attr("deposit_amount"), MONEY),
    Column("actual_balance", "尾款", "pricing", _attr("actual_balance"), MONEY),
    Column("payment_type", "付款方式", "pricing", _display("payment_type")),
    Column("installment_company", "分期公司", "pricing", _attr("installment_company")),
    Column("installment_periods", "分期期數", "pricing", lambda o: o.installment_periods or None, NUMBER),
    Column("installment_monthly", "每期金額", "pricing", lambda o: o.installment_monthly or None, MONEY),
    Column("accessories", "配件", "pricing", _accessories),
    Column("other_fees", "其他費用", "pricing", _other_fees),

    Column("actual_disbursement", "實際車價收入", "finance", _op("actual_disbursement"), MONEY),
    Column("vehicle_cost", "成本", "finance", _op("vehicle_cost"), MONEY),
    Column("total_received", "總收款金額", "finance", lambda o: _profile(o).total_received if _profile(o) else None, MONEY),
    *[Column(name, _verbose(name), "finance", _op(name), MONEY)
      for name in (*OrderOperationsProfile.INCOME_FIELDS, *OrderOperationsProfile.EXPENSE_FIELDS, *OrderOperationsProfile.INCENTIVE_FIELDS)],
    Column("total_income", "總收入", "finance", lambda o: _profile(o).total_income if _profile(o) else None, MONEY),
    Column("total_expense", "總支出", "finance", lambda o: _profile(o).total_expense if _profile(o) else None, MONEY),

    Column("net_profit", "單筆淨利", "profit", _net_profit, MONEY),
]

# 同一個收支欄位可能同時列在多個清單：只保留第一次出現的。
_seen = set()
COLUMNS = tuple(column for column in _base if not (column.key in _seen or _seen.add(column.key)))
del _seen
COLUMN_BY_KEY = {column.key: column for column in COLUMNS}
# 訂單編號一定帶出，方便人看；系統編號另放 A 欄。
REQUIRED = ("number",)
# 不能匯出的欄位（防止日後誤加到上面的清單）。
NEVER_EXPORTED = frozenset({
    "vehicle_control_password", "battery_password",
    "vehicle_control_password_encrypted", "battery_password_encrypted",
})
assert not NEVER_EXPORTED & set(COLUMN_BY_KEY), "車控／電池密碼不能匯出"
# 第一次打開時預先勾的欄位：辨認訂單＋最常批次修改的車主聯絡資料。
DEFAULT_COLUMNS = ("number", "status", "order_date", "vehicle_model", "color", "owner_name", "owner_phone", "owner_email", "owner_address")


def permissions_for(request):
    """回傳這個帳號可用的欄位權限集合。"""
    from sales.access.services import policy_for
    from sales.services.order_workspace import finance_allowed
    from sales.services.profit_access import can_view_profit

    policy = policy_for(request)
    granted = set()
    if finance_allowed(request):
        granted.add("finance")
    if can_view_profit(request) and policy.screen("profit", "export"):
        granted.add("profit")
    # 補助撥款帳戶：財務可編輯，有 work 操作授權者也看得到完整帳號（BUSINESS_RULES）。
    if policy.screen("order_finance") or policy.screen("work", "operate"):
        granted.add("payout_account")
    return granted


def column_allowed(column, granted):
    group = GROUP_BY_KEY[column.group]
    return (not group.permission or group.permission in granted) and (not column.permission or column.permission in granted)


def group_rows(granted, selected):
    """畫面用：每個群組的欄位、是否可用、是否已勾選。"""
    rows = []
    for group in GROUPS:
        columns = [column for column in COLUMNS if column.group == group.key]
        allowed = [column for column in columns if column_allowed(column, granted)]
        rows.append({
            "group": group,
            "allowed": bool(allowed),
            "columns": [{"column": column, "allowed": column_allowed(column, granted),
                         "checked": column.key in selected or column.key in REQUIRED,
                         "required": column.key in REQUIRED} for column in columns],
            "editable_count": sum(1 for column in allowed if column.editable),
        })
    return rows


def default_selection(granted):
    return [column.key for column in COLUMNS if column.key in DEFAULT_COLUMNS and column_allowed(column, granted)]


def resolve(keys, granted):
    """依宣告順序回傳要匯出的欄位；未授權或不存在的代碼一律略過，訂單編號一定在。"""
    wanted = set(keys) | set(REQUIRED)
    return [column for column in COLUMNS if column.key in wanted and column_allowed(column, granted)]


def row_values(order, columns):
    return [column.getter(order) for column in columns]


def display_text(value, kind):
    """預覽與匯出共用的文字格式（xlsx 另保留原生日期與數字）。"""
    if value is None or value == "":
        return ""
    if kind == BOOL:
        return "是" if value else "否"
    if isinstance(value, datetime):
        value = _local_date(value)
    if isinstance(value, date):
        return value.strftime("%Y/%m/%d")
    if kind == MONEY and isinstance(value, (Decimal, int, float)):
        return f"{Decimal(value):,.0f}"
    return str(value)


def baseline_text(value, kind):
    """存進匯出紀錄的基準值：之後回匯比對用，格式固定、不受千分位影響。"""
    if value is None or value == "":
        return ""
    if kind == BOOL:
        return "是" if value else "否"
    if isinstance(value, datetime):
        value = _local_date(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def summary(columns):
    groups = {column.group for column in columns}
    return {
        "count": len(columns),
        "editable": sum(1 for column in columns if column.editable),
        "pii": "pii" in groups,
        "finance": "finance" in groups,
        "profit": "profit" in groups,
    }
