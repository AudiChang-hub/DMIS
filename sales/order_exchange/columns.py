"""訂單匯出的欄位宣告（T-232 方案 A）。

每一欄只在這裡宣告一次：代碼、名稱、群組、取值、格式，以及之後的回匯能不能修改（`editable`）。

- 前 92 欄依序就是舊「匯出營運資料（目前篩選）」的欄位（Q9）：表頭名稱、順序、取值與舊匯出相同，
  預設全勾，不改勾選直接匯出時欄位內容跟舊的一樣（例外：「確認收款」「分期公司確認匯款」對 Excel 匯入的歷史單
  一律輸出「是」，T-276）；其後是舊匯出沒有的欄位，預設不勾。
- `editable`（使用者 2026-11-18 Q2／Q4）：訂單頁人工可以改的欄位都可回匯——車主資料、交車與選號、備註、
  舊車牌與舊車主、舊車與報廢、車控電池帳號，以及成交車價、牌險、付款與分期、來源與歸屬車行、收支頁人工金額。
  系統算出來的、同步帶入的、已停用的欄位與狀態只能看；個別訂單已鎖定（例如已入帳的撥款）由回匯逐張判斷。
- 車主證件號碼（Q5）可以匯出，但只能在訂單頁修改，回匯時改了列為「不可修改，已忽略」（`order_page_only`）。
- 車控與電池密碼不在任何群組裡，永遠不會被匯出。
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from django.utils import timezone

from sales.models import OrderOperationsProfile, SalesOrder
from sales.templatetags.sales_format import signed_money

TEXT, DATE, MONEY, NUMBER, BOOL = "text", "date", "money", "number", "bool"
# 匯出／預覽上限（方案 Q8）。
EXPORT_LIMIT = 5000
PREVIEW_ROWS = 50
# 匯出紀錄裡供回匯比對的基準值保存天數（Q7），到期清掉、留摘要，那份檔案就不能再回匯。
BASELINE_DAYS = 30


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    group: str
    getter: Callable[[SalesOrder], Any]
    kind: str = TEXT
    editable: bool = False
    choices: tuple = ()
    permission: str = ""  # 欄位層級另需的授權（見 permissions_for）
    order_page_only: bool = False  # 可以匯出、不能回匯，只能在訂單頁改（Q5）


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    hint: str
    sensitive: str = ""  # pii／finance／profit：畫面加標籤，預覽提醒檔案含敏感資料
    permission: str = ""


GROUPS = (
    Group("order", "訂單基本", "編號、日期、車輛、狀態與來源"),
    Group("owner", "車主", "姓名、聯絡方式與地址"),
    Group("pii", "個資", "證件號碼、生日、舊車主證號、補助撥款帳戶", sensitive="pii"),
    Group("delivery", "交車與選號", "交車方式、選號與訂單備註"),
    Group("pricing", "金額與付款", "成交車價、牌險、付款方式與分期、尾款與配件"),
    Group("subsidy", "補助", "補助方案、金額與各單位進度"),
    Group("trade_in", "汰舊舊車主", "舊車牌與舊車主"),
    Group("old_vehicle", "舊車與報廢", "舊車引擎號碼、廠牌、報廢與回收日期"),
    Group("fulfillment", "車控與電池", "帳號與合約（不含密碼）"),
    Group("finance", "收支", "實際車價收入、成本與各項收入支出", sensitive="finance", permission="finance"),
    Group("profit", "淨利", "單筆淨利", sensitive="profit", permission="profit"),
    Group("history", "停用欄位", "畫面已不編輯、資料保留的舊欄位"),
)
GROUP_BY_KEY = {group.key: group for group in GROUPS}


def _profile(order):
    try:
        return order.operations
    except OrderOperationsProfile.DoesNotExist:
        return None


def _op(name, default=None):
    """收支資料的欄位；還沒有收支資料時用舊匯出的預設值（金額 0、文字空白）。"""
    def getter(order):
        profile = _profile(order)
        return getattr(profile, name, default) if profile else default
    return getter


def _attr(name):
    return lambda order: getattr(order, name)


def _display(name):
    return lambda order: getattr(order, f"get_{name}_display")() if getattr(order, name) else ""


def _local_date(value):
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def _year_month(value):
    # 舊車出廠年月與畫面輸入一致用 6 碼 YYYYMM（T-93）。
    return f"{value.year:04d}{value.month:02d}" if value else ""


def _roc_birth(order):
    value = order.owner_birth_date
    return f"{value.year - 1911}/{value.month:02d}/{value.day:02d}" if value else ""


def _agency(index):
    def getter(order):
        rows = order.subsidy_agency_summary
        return rows[index]["text"] if len(rows) > index else ""
    return getter


def _flag(name):
    return lambda order: bool(_op(name, False)(order))


def _settled_flag(name):
    """Excel 匯入的歷史單＝已人工處理完，「確認收款」「分期公司確認匯款」一律輸出「是」；系統單照存檔值（T-276）。
    判斷與 payment_summary 的 settled 同一口徑（is_settled_history）。"""
    from sales.services.payment_summary import is_settled_history
    stored = _flag(name)
    return lambda order: is_settled_history(order) or stored(order)


def _accessory_text(line):
    if line.is_credit:
        # 配件金（T-305）：面額與實際折抵（最多折到配件小計 0 元）；負號在金額符號前「−$1,000」（T-313，同 signed_money）。
        # 這欄回匯只能看、不解析（editable=False），格式改了也不影響回匯。
        return f"{line.name}（配件金）{signed_money(line.amount)}，實際折抵 {signed_money(line.effective_total)}"
    return f"{line.name}×{line.quantity} {line.amount:,.0f}" if line.quantity != 1 else f"{line.name} {line.amount:,.0f}"


def _accessories(order):
    return "；".join(_accessory_text(line) for line in order.accessory_lines)


def _other_fees(order):
    return "；".join(f"{line.name} {line.amount:,.0f}" for line in order.other_fees.all())


def _payment_splits(order):
    return "＋".join(f"{row['label']} ${int(row['amount']):,}" for row in order.payment_split_rows)


def _registration_state(order):
    if not order.registration_date:
        return ""
    return "已確認" if order.registration_completed_at else "預計"


def _net_profit(order):
    if order.is_cancelled_sale:
        return None
    profile = _profile(order)
    return profile.net_profit if profile else 0


def _choices(field_name, model=SalesOrder):
    return tuple(label for _value, label in model._meta.get_field(field_name).choices)


def _verbose(name):
    return str(OrderOperationsProfile._meta.get_field(name).verbose_name)


def _money(name, label=None, *, group="finance"):
    """收支頁的金額：表單上人工可以改的才可回匯；同步帶入的（刷卡手續費等）只能看。"""
    return Column(name, label or _verbose(name), group, _op(name, 0), MONEY, editable=name not in SYNCED_FINANCE)


# 收支頁表單停用、由訂單或收款同步帶入的欄位（`OrderOperationsForm` 的 synced_fields）。
SYNCED_FINANCE = frozenset({
    "dealer_name", "installment_fee_income", "installment_info", "payment_confirmed",
    "installment_transfer_confirmed", "card_fee_income", "card_fee_expense",
})
# 舊匯出最後 11 欄（Excel 匯入帶進來的原始財務欄位），依舊匯出順序。
IMPORTED_FINANCE = (
    "legacy_card_fee_expense", "installment_fee_expense", "used_vehicle_expense", "gift_shipping_expense",
    "friendly_dealer_bonus_expense", "first_sale_bonus_expense", "volume_bonus_expense",
    "used_vehicle_income", "card_installment_fee_income", "yamaha_bonus_income", "friendly_dealer_bonus_income",
)

# ---- 舊「匯出營運資料」的 92 欄，順序與表頭照舊（sales/views.py 2.22.3 版 operations_report_export） ----
LEGACY_EXPORT = (
    Column("number", "訂單編號", "order", _attr("number")),
    Column("order_date", "訂單日期", "order", _attr("order_date"), DATE),
    Column("vehicle_model", "車種", "order", lambda o: o.vehicle_model.name),
    Column("model_number", "型號", "order", lambda o: o.vehicle_model.model_number),
    Column("model_code", "型式", "order",
           lambda o: o.vehicle_model.get_model_code_display() if o.vehicle_model.model_code else ""),
    Column("color", "顏色", "order", lambda o: o.color.label),
    Column("vehicle_identifier", "引擎／車身號碼", "order",
           lambda o: o.allocated_vehicle.identifier if o.allocated_vehicle else ""),
    Column("owner_name", "車主名稱", "owner", _attr("owner_name"), editable=True),
    Column("final_plate_number", "車牌號碼", "order", _attr("final_plate_number")),
    Column("vehicle_price", "車款售價", "pricing", _attr("vehicle_price"), MONEY, editable=True),
    Column("actual_disbursement", "實際撥款", "finance", _op("actual_disbursement", 0), MONEY, editable=True),
    Column("vehicle_cost", "成本", "finance", _op("vehicle_cost", 0), MONEY, editable=True),
    Column("total_received", "總收款金額", "finance", lambda o: _profile(o).total_received if _profile(o) else 0, MONEY),
    Column("payment_confirmed", "確認收款", "pricing", _settled_flag("payment_confirmed"), BOOL),
    Column("installment_company", "分期公司", "pricing", _attr("installment_company"), editable=True),
    Column("installment_periods", "期數", "pricing", _attr("installment_periods"), NUMBER, editable=True),
    Column("installment_monthly", "每期金額", "pricing", _attr("installment_monthly"), MONEY, editable=True),
    Column("installment_transfer_confirmed", "分期公司確認匯款", "pricing", _settled_flag("installment_transfer_confirmed"), BOOL),
    Column("owner_id_number", "身分證字號", "pii", _attr("owner_id_number"), order_page_only=True),
    Column("owner_birth_date", "西元生日", "pii", _attr("owner_birth_date"), DATE, editable=True),
    Column("owner_birth_roc", "民國生日", "pii", _roc_birth),
    Column("owner_address", "戶籍地址", "owner", _attr("owner_address"), editable=True),
    Column("owner_phone", "手機", "owner", _attr("owner_phone"), editable=True),
    Column("owner_email", "Email", "owner", _attr("owner_email"), editable=True),
    Column("delivery_destination", "自送托運地點", "delivery", _attr("delivery_destination"), editable=True),
    Column("invoice_date", "發票日期", "history", _op("invoice_date", ""), DATE),
    Column("balance_invoice_number", "尾款發票號碼", "history", _op("balance_invoice_number", "")),
    Column("subsidy_type", "補助方案", "subsidy", _attr("subsidy_type")),
    Column("subsidy_amount", "補助金額", "subsidy", _op("subsidy_amount", 0), MONEY),
    Column("bank_name", "銀行", "pii", _op("bank_name", ""), permission="payout_account"),
    Column("remittance_account", "匯款帳戶", "pii", _op("remittance_account", ""), permission="payout_account"),
    Column("subsidy_applied_on", "申請日", "subsidy", _op("subsidy_applied_on", ""), DATE),
    Column("industry_bureau_progress", "工業局補助進度", "subsidy", _agency(0)),
    Column("environment_ministry_progress", "環境部補助進度", "subsidy", _agency(1)),
    Column("local_government_progress", "地方政府補助進度", "subsidy", _agency(2)),
    Column("old_owner_name", "舊車車主", "trade_in", _attr("old_owner_name"), editable=True),
    Column("old_owner_id_number", "舊車車主身分證", "pii", _attr("old_owner_id_number"), editable=True),
    Column("trade_in_plate", "舊車牌照號碼", "trade_in", _attr("trade_in_plate"), editable=True),
    Column("old_vehicle_engine_number", "舊車引擎號碼", "old_vehicle", _op("old_vehicle_engine_number", ""), editable=True),
    Column("old_vehicle_brand", "舊車廠牌", "old_vehicle", _op("old_vehicle_brand", ""), editable=True),
    Column("old_vehicle_displacement_cc", "排氣量", "old_vehicle", _op("old_vehicle_displacement_cc", ""), NUMBER, editable=True),
    Column("old_vehicle_manufactured_on", "出廠日期", "old_vehicle",
           lambda o: _year_month(_op("old_vehicle_manufactured_on")(o)), editable=True),
    Column("scrapped_on", "報廢日期", "old_vehicle", _op("scrapped_on", ""), DATE, editable=True),
    Column("recycled_on", "回收日期", "old_vehicle", _op("recycled_on", ""), DATE, editable=True),
    _money("registration_tax_expense", "領牌稅金支出"),
    _money("compulsory_insurance_expense", "強制險支出"),
    _money("plate_selection_expense", "選號支出"),
    _money("gift_expense", "贈品支出"),
    _money("shipping_expense", "運費支出"),
    _money("dealer_commission_expense", "車行傭金支出"),
    _money("card_fee_expense", "銀行刷卡手續費支出"),
    _money("registration_tax_income", "領牌稅金收入"),
    _money("compulsory_insurance_income", "強制險收入"),
    _money("agency_fee_income", "代辦費收入"),
    _money("plate_selection_income", "選號收入"),
    _money("installment_fee_income", "分期手續費收入"),
    _money("card_fee_income", "刷卡手續費收入"),
    _money("other_income", "其他收入"),
    _money("scrap_agency_income", "報廢代辦收入"),
    _money("scrap_vehicle_income", "報廢車收入"),
    _money("sales_bonus", "實銷獎勵金"),
    _money("promotion_subsidy", "促銷補助金"),
    _money("installment_interest_subsidy", "分期補貼息"),
    _money("insurance_commission", "強制險傭金"),
    _money("credit_card_commission", "信用卡傭金"),
    Column("vehicle_control_account", "車控帳號", "fulfillment", _op("vehicle_control_account", ""), editable=True),
    Column("battery_plan", "電池合約方案", "fulfillment", _op("battery_plan", ""), editable=True),
    Column("battery_activated_on", "電池合約啟用日期", "fulfillment", _op("battery_activated_on", ""), DATE, editable=True),
    Column("battery_account", "電池合約帳號", "fulfillment", _op("battery_account", ""), editable=True),
    Column("helmet", "安全帽", "history", _op("helmet", "")),
    Column("company_gift_or_remittance", "公司禮券、匯款", "history", _op("company_gift_or_remittance", "")),
    Column("other_fulfillment", "其他", "history", _op("other_fulfillment", "")),
    Column("platform_gift", "平台贈品", "history", _op("platform_gift", "")),
    Column("customer_service_phone", "客服電話", "history", _op("customer_service_phone", "")),
    Column("installment_info", "分期資訊", "pricing", _op("installment_info", "")),
    Column("dealer_name", "車行", "order", _op("dealer_name", "")),
    Column("total_income", "總收入", "finance", lambda o: _profile(o).total_income if _profile(o) else 0, MONEY),
    Column("total_expense", "總支出", "finance", lambda o: _profile(o).total_expense if _profile(o) else 0, MONEY),
    Column("net_profit", "單筆淨利", "profit", _net_profit, MONEY),
    Column("commission_recipient", "台數與傭金歸屬車行", "order", lambda o: str(o.effective_commission_recipient or "")),
    Column("established_on", "訂單成立日期", "order", _attr("established_on"), DATE),
    *[_money(name) for name in IMPORTED_FINANCE],
)

# ---- 舊匯出沒有的欄位（預設不勾） ----
EXTRA = (
    Column("status", "訂單狀態", "order", _display("status")),
    Column("registration_date", "領牌日", "order", _attr("registration_date"), DATE),
    Column("registration_state", "領牌日狀態", "order", _registration_state),
    Column("delivered_at", "交車日", "order", lambda o: _local_date(o.delivered_at), DATE),
    Column("closed_at", "結案日", "order", lambda o: _local_date(o.closed_at), DATE),
    Column("source_type", "訂單來源類型", "order", _display("source_type"), editable=True, choices=_choices("source_type")),
    Column("source", "訂單來源", "order", lambda o: o.source.name if o.source_id else "", editable=True),
    Column("assigned_commission_recipient", "指定歸屬車行", "order",
           lambda o: o.commission_recipient.name if o.commission_recipient_id else "", editable=True),
    Column("owner_type", "車主類型", "owner", _display("owner_type"), editable=True, choices=_choices("owner_type")),
    Column("owner_name_en", "英文姓名", "owner", _attr("owner_name_en"), editable=True),
    Column("owner_nationality", "國籍", "owner", _attr("owner_nationality"), editable=True),
    Column("residence_expiry", "居留期限", "owner", _attr("residence_expiry"), DATE, editable=True),
    Column("delivery_method", "交車方式", "delivery", _display("delivery_method"), editable=True, choices=_choices("delivery_method")),
    Column("plate_choice", "選號方式", "delivery", _display("plate_choice"), editable=True, choices=_choices("plate_choice")),
    Column("watched_numbers", "指定號碼與志願序", "delivery", _attr("watched_numbers"), editable=True),
    Column("plate_preference_note", "領牌偏好備註", "delivery", _attr("plate_preference_note"), editable=True),
    Column("note", "訂單備註", "delivery", _attr("note"), editable=True),
    Column("trade_in_intent", "是否有汰舊", "delivery", _display("trade_in_intent"), editable=True, choices=_choices("trade_in_intent")),
    Column("payment_type", "付款方式", "pricing", _display("payment_type"), editable=True, choices=_choices("payment_type")),
    Column("payment_splits", "付款方式明細", "pricing", _payment_splits),
    Column("installment_opening_fee", "分期開辦費", "pricing", _attr("installment_opening_fee"), MONEY, editable=True),
    Column("plate_insurance_fee", "牌險費", "pricing", _attr("plate_insurance_fee"), MONEY, editable=True),
    Column("plate_selection_fee", "選號費", "pricing", _attr("plate_selection_fee"), MONEY, editable=True),
    Column("approved_discount_amount", "總價優惠", "pricing", _attr("approved_discount_amount"), MONEY),
    Column("discounted_total", "優惠後總價", "pricing", lambda o: o.discounted_total, MONEY),
    Column("deposit_amount", "訂金", "pricing", _attr("deposit_amount"), MONEY),
    Column("actual_balance", "尾款", "pricing", _attr("actual_balance"), MONEY),
    Column("accessories", "配件", "pricing", _accessories),
    Column("other_fees", "其他費用", "pricing", _other_fees),
    Column("old_owner_phone", "舊車主電話", "trade_in", _attr("old_owner_phone"), editable=True),
    Column("old_owner_same_as_owner", "舊車主同新車主", "trade_in", _attr("old_owner_same_as_owner"), BOOL,
           editable=True, choices=("是", "否")),
    Column("battery_rate_plan", "車控與電池備註", "fulfillment", _op("battery_rate_plan", ""), editable=True),
    Column("vehicle_control_confirmed", "車控與電池已確認", "fulfillment", lambda o: bool(_op("vehicle_control_confirmed_at")(o)), BOOL),
)

COLUMNS = LEGACY_EXPORT + EXTRA
COLUMN_BY_KEY = {column.key: column for column in COLUMNS}
assert len(COLUMN_BY_KEY) == len(COLUMNS), "欄位代碼重複"
assert len(LEGACY_EXPORT) == 92, "舊營運匯出是 92 欄"
# 訂單編號一定帶出，方便人看；系統編號另放 A 欄。
REQUIRED = ("number",)
# 不能匯出的欄位（防止日後誤加到上面的清單）。
NEVER_EXPORTED = frozenset({
    "vehicle_control_password", "battery_password",
    "vehicle_control_password_encrypted", "battery_password_encrypted",
})
assert not NEVER_EXPORTED & set(COLUMN_BY_KEY), "車控／電池密碼不能匯出"
# 預設勾選＝舊「匯出營運資料（目前篩選）」那組欄位（Q9）；沒有授權的群組自動略過。
DEFAULT_COLUMNS = tuple(column.key for column in LEGACY_EXPORT)


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


def column_hint(column):
    if column.key in REQUIRED:
        return "一定匯出"
    if column.order_page_only:
        return "只能在訂單頁改"
    return "可改完匯回" if column.editable else "只能看"


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
                         "required": column.key in REQUIRED, "hint": column_hint(column)} for column in columns],
            "editable_count": sum(1 for column in allowed if column.editable),
        })
    return rows


def default_selection(granted):
    return [key for key in DEFAULT_COLUMNS if column_allowed(COLUMN_BY_KEY[key], granted)]


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
