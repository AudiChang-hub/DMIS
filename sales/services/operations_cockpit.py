"""營運總表駕駛艙（T-167，使用者 2026-11-13 選 A 案）：公司現在好不好、為什麼、哪裡要處理。

- 只彙總既有服務的結果，不新增金額或狀態規則；顯示門檻見 BUSINESS_RULES「營運總表顯示門檻」。
- 比較基準：上月同期與去年同期並列、份量相同；走勢是近 12 個月今年 vs 去年。
- 先算出全部指標（純資料，可快取），再依檢視者權限遮蔽；權限見 `for_viewer`。
- 快取鍵含版號、日期、期間與資料指紋（各表筆數＋最後更新時間）：部署新版或資料一改就重算；
  不在指紋內的異動（例如只改車型、車行資料）最晚 CACHE_SECONDS 後反映。`refresh=True` 略過快取。
"""
from collections import Counter, OrderedDict
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.core.cache import cache
from django.db.models import Count, Max
from django.urls import reverse
from django.utils import timezone

from config.release_notes import CURRENT_VERSION
from sales.models import (
    DealerVolumeBonusRule,
    IncentiveCampaign,
    OrderDraft,
    OrderOperationsProfile,
    OrderVolumeBonus,
    PaymentRecord,
    SalesOrder,
    registration_confirmed_q,
    SalesSource,
    VehicleInventory,
    VehicleModel,
)
from sales.reporting.payout_models import DealerPayoutEntry
from sales.services.dashboard_metrics import (
    ON_HAND_STATUSES,
    _last_year,
    _month_bounds,
    _percent_change,
    _previous_month,
    _sales_snapshot,
    build_dashboard_metrics,
)
from sales.services.order_filters import new_orders_between
from sales.services.order_next_actions import STALE_ALLOCATION_DAYS
from sales.services.business_days import DEALER_BALANCE_DAYS, DEALER_DOCUMENT_DAYS
from sales.services.sales_metrics import (CANCELLED_STATUSES, DELIVERED_STATUSES, PAYMENT_CATEGORIES, money_bucket,
                                          payment_category, payout_due)

ZERO = Decimal("0")
CACHE_VERSION = 2       # T-284 拆列多了撥款／客人兩部分
CACHE_SECONDS = 600

# ── 顯示門檻（使用者 2026-11-13 選定；文字說明只寫在 BUSINESS_RULES「營運總表顯示門檻」）──
# 各關停留超過幾天算卡關；已配車待領牌沿用配車保留逾期的天數。
STAGE_LIMITS = OrderedDict((
    ("allocation_pending", 3),
    ("allocated", STALE_ALLOCATION_DAYS),
    ("delivery_pending", 7),
    ("delivered_docs_pending", 14),
))
STOCK_AGE_ALERT_DAYS = 90       # 庫齡達 90 天標紅
VELOCITY_DAYS = 90              # 可銷天數用近 90 天領牌台數算日均
SLOW_COVER_DAYS = 90            # 可銷天數超過 90 天，或 90 天內 0 台＝滯銷
SHORTAGE_MIN_SOLD = 3           # 近 90 天賣 3 台以上
SHORTAGE_COVER_DAYS = 14        # 且可銷天數不到 14 天＝缺貨風險
RECEIVABLE_AGE_BUCKETS = ((0, 7, "0–7 天"), (8, 30, "8–30 天"), (31, None, "30 天以上"))
CAMPAIGN_ENDING_DAYS = 30       # 原廠獎勵 30 天內結束要提醒

PERIODS = OrderedDict((("month", "本月"), ("last_month", "上月"), ("ytd", "今年至今")))
STAGE_LABELS = {
    "allocation_pending": "待配車", "allocated": "待領牌", "delivery_pending": "待交付",
    "delivered_docs_pending": "交車待文件",
}
STAGE_FILTERS = {
    "allocation_pending": "allocation_pending", "allocated": "registration_pending",
    "delivery_pending": "delivery_pending", "delivered_docs_pending": "delivered_docs_pending",
}
SOURCE_MIX = (("store", "本店"), ("dealer", "車行"), ("platform", "網路平台"))
ENERGY_MIX = (("gas", "油車"), ("electric", "電動（含輕型、微型）"))
PAYMENT_MIX = (("cash", "現金／刷卡"), ("installment", "分期"))
# 「錢」依付款方式拆列（T-275 第 9 項）：每一格點進全部訂單 risk＋pay，張數和卡片相同。
MONEY_SPLIT_RISK = OrderedDict((("unsettled", "unsettled_delivered"), ("before_delivery", "before_delivery"),
                                ("awaiting_payout", "awaiting_payout")))
UNSETTLED_LABELS = {"cash": "現金", "card": "刷卡", "installment": "分期，客人自付部分", "platform": "平台，客人自付部分"}
RECONCILIATION_CHANNELS = (("installment", "分期撥款待入帳"), ("platform", "平台撥款待入帳"))
# 車行尾款／領牌到期的依據（T-280）；工作日從交車日的下一天算，跳過週末與營業日設定的假日。
DEALER_DUE_RULE = (f"交車後第 {DEALER_BALANCE_DAYS} 個工作天起尾款未收清、"
                   f"第 {DEALER_DOCUMENT_DAYS} 個工作天起領牌未完成")
# 油電領牌（T-263）：未領牌＝訂單流程的待配車＋待領牌兩站。
ENERGY_REGISTRATION = (("gas", "油車"), ("electric", "電車"))
PENDING_REGISTRATION = ("allocation_pending", "allocated")


def _url(name, params=None, *args):
    url = reverse(name, args=args)
    return f"{url}?{urlencode(params)}" if params else url


def _fingerprint():
    """各來源表的筆數與最後更新時間；任一筆新增、刪除或儲存都會改變。"""
    parts = []
    for model in (SalesOrder, PaymentRecord, OrderOperationsProfile, VehicleInventory, OrderDraft,
                  IncentiveCampaign, OrderVolumeBonus, DealerPayoutEntry):
        manager = getattr(model, "all_objects", model.objects)
        row = manager.aggregate(total=Count("pk"), latest=Max("updated_at"))
        parts.append(f"{row['total']}:{row['latest'].timestamp() if row['latest'] else 0}")
    return "|".join(parts)


def load(period="month", today=None, refresh=False):
    period = period if period in PERIODS else "month"
    today = today or timezone.localdate()
    # 版號放進鍵：部署新版後不沿用舊版算的結果（T-170）。
    key = f"ops-cockpit:{CURRENT_VERSION}:v{CACHE_VERSION}:{today.isoformat()}:{period}:{_fingerprint()}"
    data = None if refresh else cache.get(key)
    if data is None:
        data = build(period, today)
        cache.set(key, data, CACHE_SECONDS)
    return data


# ── 計算 ─────────────────────────────────────────────────────────────────


def _windows(period, today):
    month_start, _month_end = _month_bounds(today)
    if period == "last_month":
        start, end = _month_bounds(_previous_month(today))
        previous = _month_bounds(_previous_month(start))
        last_year = (start.replace(year=start.year - 1), _month_bounds(start.replace(year=start.year - 1))[1])
        label = f"{start.year} 年 {start.month} 月"
    elif period == "ytd":
        start, end = today.replace(month=1, day=1), today
        previous = None
        last_year = (start.replace(year=start.year - 1), _last_year(today))
        label = f"{start.year} 年 1 月 1 日–{today.month} 月 {today.day} 日"
    else:
        start, end = month_start, today
        previous_start, previous_end = _month_bounds(_previous_month(today))
        comparison_end = previous_end if today == _month_bounds(today)[1] else previous_start.replace(
            day=min(today.day, previous_end.day))
        previous = (previous_start, comparison_end)
        last_year = (start.replace(year=start.year - 1), _last_year(today))
        label = f"{start.year} 年 {start.month} 月 1–{today.day} 日"
    return {"current": (start, end), "previous": previous, "last_year": last_year, "label": label}


def _compare(current, previous, last_year):
    return {
        "value": current, "previous": previous, "last_year": last_year,
        "vs_previous": _percent_change(current, previous) if previous is not None else None,
        "vs_last_year": _percent_change(current, last_year) if last_year is not None else None,
    }


def _new_orders(start, end):
    # 補登單算到領牌那個月（T-271）；和全部訂單 date_basis=new_order 共用 new_orders_between。
    return new_orders_between(SalesOrder.objects.all(), start, end).count()


def _pulse(windows, source):
    current = _sales_snapshot(*windows["current"], source)
    previous = _sales_snapshot(*windows["previous"], source) if windows["previous"] else None
    last_year = _sales_snapshot(*windows["last_year"], source)

    def pick(snapshot, key):
        return snapshot[key] if snapshot else None

    profit = _compare(current["profit_total"], pick(previous, "profit_total"), last_year["profit_total"])
    profit.update({"ready": current["profit_ready"], "count": current["count"], "pending": current["profit_pending"],
                   "average": current["average_profit"]})
    return {
        "count": _compare(current["count"], pick(previous, "count"), last_year["count"]),
        "sales": _compare(current["sales_total"], pick(previous, "sales_total"), last_year["sales_total"]),
        "profit": profit,
        "new_orders": _compare(
            _new_orders(*windows["current"]),
            _new_orders(*windows["previous"]) if windows["previous"] else None,
            _new_orders(*windows["last_year"])) | {"url": _url("order_list", {
                "date_basis": "new_order", "date_from": windows["current"][0].isoformat(),
                "date_to": windows["current"][1].isoformat(), "business_only": "1"})},
        "received": current["actual_received"],
    }


def _spark(this_year, last_year, width=240, height=56, pad=6):
    """今年實線、去年虛線；共用同一條縱軸，0 以下照實畫。None 代表該月淨利還不能計入，線段斷開。"""
    values = [value for value in this_year + last_year if value is not None] + [0]
    low, high = min(values), max(values)
    scale = (high - low) or 1
    step = width / (len(this_year) - 1 or 1)

    def y(value):
        return round(pad + (height - 2 * pad) * (1 - (float(value) - float(low)) / float(scale)), 2)

    def segments(series):
        result, current = [], []
        for index, value in enumerate(series):
            if value is None:
                if current:
                    result.append(" ".join(current))
                current = []
                continue
            current.append(f"{round(index * step, 2)},{y(value)}")
        if current:
            result.append(" ".join(current))
        return result

    last_point = next(((round(index * step, 2), y(value)) for index, value in reversed(list(enumerate(this_year)))
                       if value is not None), None)
    return {"this": segments(this_year), "last": segments(last_year), "zero": y(0), "now": last_point,
            "width": width, "height": height, "step": round(step, 2)}


def _trend(metrics):
    rows, last_rows = metrics["trend"], metrics["trend_last_year"]
    series = OrderedDict()
    for key, label, unit in (("count", "領牌台數", "台"), ("sales_total", "車款成交額", "元"),
                             ("profit_total", "訂單淨利", "元")):
        def value(row):
            return None if key == "profit_total" and not row["profit_ready"] else row[key]
        this_year, last_year = [value(row) for row in rows], [value(row) for row in last_rows]
        spark = _spark(this_year, last_year)
        series[key] = {"label": label, "unit": unit, "spark": spark,
                       "points": [{"label": row["label"], "this": this_value, "last": last_value,
                                   "last_label": last_row["label"], "x": round(index * spark["step"] - spark["step"] / 2, 2)}
                                  for index, (row, last_row, this_value, last_value)
                                  in enumerate(zip(rows, last_rows, this_year, last_year))]}
    negative = [row["label"] for row in rows if row["profit_ready"] and row["average_profit"] is not None
                and row["average_profit"] < 0]
    return {"series": series, "negative_profit_months": negative,
            "first": rows[0]["label"], "last": rows[-1]["label"]}


def _orders_between(source, start, end):
    return [order for order in source if order.confirmed_registration_date and start <= order.registration_date <= end
            and not order.is_cancelled_sale]


def _mix(windows, source, trend_start, today):
    groups = (("本期", windows["current"]), ("去年同期", windows["last_year"]), ("近 12 個月", (trend_start, today)))
    rows = {key: [] for key in ("source", "energy", "payment")}
    for label, (start, end) in groups:
        orders = _orders_between(source, start, end)
        source_counts = Counter(order.source_type for order in orders)
        energy_counts = Counter("gas" if order.vehicle_model.energy_type == VehicleModel.EnergyType.GAS else "electric"
                                for order in orders)
        payment_counts = Counter("installment" if order.payment_type == SalesOrder.PaymentType.INSTALLMENT else "cash"
                                 for order in orders)
        for key, counts, keys in (("source", source_counts, SOURCE_MIX), ("energy", energy_counts, ENERGY_MIX),
                                  ("payment", payment_counts, PAYMENT_MIX)):
            total = sum(counts[item] for item, _ in keys)
            rows[key].append({"label": label, "total": total, "parts": [
                {"key": item, "label": name, "count": counts[item],
                 "share": round(counts[item] * 100 / total) if total else 0} for item, name in keys]})
    return {
        "source": {"label": "通路", "keys": SOURCE_MIX, "rows": rows["source"]},
        "energy": {"label": "能源", "keys": ENERGY_MIX, "rows": rows["energy"]},
        "payment": {"label": "付款", "keys": PAYMENT_MIX, "rows": rows["payment"]},
    }


def _energy_key(order):
    # 與 `_mix` 同一寫法：油車以外（電動、輕型、微型）都算電車。訂單車型是必填外鍵，不會沒有車型。
    return "gas" if order.vehicle_model.energy_type == VehicleModel.EnergyType.GAS else "electric"


def _energy_registration(windows, source, active):
    """油電領牌（T-263，使用者 2026-11-21 選 A）：口徑只寫在 BUSINESS_RULES「營運總表顯示門檻」。

    已領牌＝本期領牌台數依能源拆開（油＋電＝領牌台數）；未領牌＝目前在手的待配車＋待領牌，不隨期間切換。
    """
    start, end = windows["current"]
    registered = Counter(_energy_key(order) for order in _orders_between(source, start, end))
    pending = Counter((_energy_key(order), order.status) for order in active if order.status in PENDING_REGISTRATION)
    rows = []
    for key, label in ENERGY_REGISTRATION:
        stages = [{"key": status, "label": STAGE_LABELS[status], "count": pending[(key, status)],
                   # 全部訂單的能源別篩選一次只能選一種，電車（含輕型、微型）沒有現成篩選，不給連結。
                   "url": _url("order_list", {"status": STAGE_FILTERS[status], "energy_type": key})
                   if key == "gas" else ""} for status in PENDING_REGISTRATION]
        rows.append({"key": key, "label": label, "registered": registered[key],
                     "registered_url": _url("order_list", {
                         "energy_type": key, "date_from": start.isoformat(), "date_to": end.isoformat(),
                         "business_only": "1"}) if key == "gas" else "",
                     "pending": sum(stage["count"] for stage in stages), "stages": stages})
    return {"rows": rows, "registered": sum(row["registered"] for row in rows),
            "pending": sum(row["pending"] for row in rows)}


def _movers(windows, source, limit=5):
    current = Counter(order.vehicle_model.name for order in _orders_between(source, *windows["current"]))
    last_year = Counter(order.vehicle_model.name for order in _orders_between(source, *windows["last_year"]))
    names = sorted(set(current) | set(last_year), key=lambda name: (-max(current[name], last_year[name]),
                                                                    -current[name], name))
    rows = []
    for name in names[:limit]:
        delta = current[name] - last_year[name]
        rows.append({"name": name, "current": current[name], "last_year": last_year[name], "delta": delta,
                     "delta_text": f"+{delta}" if delta > 0 else f"−{-delta}" if delta < 0 else "0"})
    return rows


def _age_days(today, value):
    if value is None:
        return None
    day = timezone.localtime(value).date() if hasattr(value, "tzinfo") else value
    return (today - day).days


def dealer_credit_rows():
    """有未付的車行（現金新版應收的已交車單，依車行加總）；營運總表與「車行未付」清單共用（T-275；額度 T-288 移除）。"""
    from sales.services.dealer_credit import ON_ACCOUNT_STATUSES, on_account_orders

    dealer_ids = SalesOrder.objects.filter(
        source_type=SalesOrder.SourceType.DEALER, status__in=ON_ACCOUNT_STATUSES, cash_receivable_v2=True,
        source__isnull=False).values_list("source_id", flat=True).distinct()
    rows = []
    for dealer in SalesSource.objects.filter(pk__in=list(dealer_ids)):
        orders = on_account_orders(dealer.pk)
        amount = sum((due for _order, due in orders), ZERO)
        if amount > 0:
            rows.append({"dealer": dealer, "amount": amount, "orders": orders})
    rows.sort(key=lambda row: -row["amount"])
    return rows


def _money(metrics, today):
    outstanding_total, unsettled, unsettled_payout = ZERO, [], ZERO
    # 含平台預估的金額要標「預估」（T-278 QA 疑慮 a）：交車後未結清那幾張只看撥款部分是否含預估。
    unsettled_payout_estimated = False
    counts, amounts = Counter(), {bucket: ZERO for bucket in MONEY_SPLIT_RISK}
    # payout／customer：這一格的金額裡撥款和客人應收各多少；payout_count＝其中有撥款待入帳的張數（T-284，
    # 撥款待入帳兩列用它對回三格）。交車後未結清那格的金額只算客人，撥款部分記在 payout，不加進 amount。
    split = {bucket: OrderedDict((key, {"count": 0, "amount": ZERO, "ages": [], "estimated": False, "payout": ZERO,
                                        "payout_count": 0, "payout_estimated": False, "customer": ZERO})
                                 for key, _label in PAYMENT_CATEGORIES) for bucket in MONEY_SPLIT_RISK}
    for order, summary in metrics["outstanding_summaries"]:
        summary = {**summary, "platform_due": metrics["platform_due"].get(order.pk)}
        customer, payout = max(summary["customer_due"], ZERO), payout_due(summary)
        outstanding_total += customer + payout
        # 三格和全部訂單 risk 共用 money_bucket；交車後未結清和「款項未結清」紅標同一口徑（order_list_unsettled）。
        # 已交車待撥款：客戶已收清，只剩分期／平台撥款（事後對帳）；平台是收支的預估車價收入（T-278 B1-A）。
        bucket = money_bucket(order, summary)
        # 三格金額（T-278 D1-A）：交車後未結清只算客人應收（同紅標），那幾張的撥款部分另列，合計才對得上。
        amount = customer if bucket == "unsettled" else customer + payout
        if bucket == "unsettled":
            delivered = order.delivered_at or order.registration_completed_at
            unsettled.append((customer, _age_days(today, delivered)))
            unsettled_payout += payout
            unsettled_payout_estimated = unsettled_payout_estimated or summary.get("platform_due") is not None
        counts[bucket] += 1
        amounts[bucket] += amount
        cell = split[bucket][payment_category(order)]
        cell["count"] += 1
        cell["amount"] += amount
        cell["estimated"] = cell["estimated"] or (bucket != "unsettled" and summary.get("platform_due") is not None)
        cell["customer"] += customer
        if payout > 0 or summary.get("platform_due") is not None:
            cell["payout"] += payout
            cell["payout_count"] += 1
            cell["payout_estimated"] = cell["payout_estimated"] or summary.get("platform_due") is not None
        if bucket == "unsettled":
            cell["ages"].append(unsettled[-1][1])
    buckets = []
    for low, high, label in RECEIVABLE_AGE_BUCKETS:
        rows = [row for row in unsettled if row[1] is not None and row[1] >= low and (high is None or row[1] <= high)]
        buckets.append({"label": label, "count": len(rows), "amount": sum((row[0] for row in rows), ZERO),
                        "late": low > 30})
    ages = [row[1] for row in unsettled if row[1] is not None]
    dealers = [{"name": row["dealer"].name, "amount": row["amount"], "orders": len(row["orders"])} for row in dealer_credit_rows()]
    return {
        "outstanding_count": metrics["risk"]["outstanding"],
        "outstanding_amount": outstanding_total,
        "unsettled_count": len(unsettled),
        "unsettled_amount": sum((row[0] for row in unsettled), ZERO),
        "unsettled_oldest": max(ages) if ages else None,
        "unsettled_payout_amount": unsettled_payout,
        "unsettled_payout_estimated": unsettled_payout_estimated,
        "before_delivery_count": counts["before_delivery"],
        "before_delivery_amount": amounts["before_delivery"],
        "before_delivery_estimated": any(cell["estimated"] for cell in split["before_delivery"].values()),
        "awaiting_payout_count": counts["awaiting_payout"],
        "awaiting_payout_amount": amounts["awaiting_payout"],
        "awaiting_payout_estimated": any(cell["estimated"] for cell in split["awaiting_payout"].values()),
        "outstanding_estimated": unsettled_payout_estimated or any(
            cell["estimated"] for bucket in ("before_delivery", "awaiting_payout") for cell in split[bucket].values()),
        "aging": buckets,
        "unconfirmed": metrics["risk"]["unconfirmed"],
        "refund": metrics["risk"]["refund"],
        "overpaid": metrics["risk"]["overpaid"],
        "dealer_credit": dealers,
        "dealer_credit_total": sum((row["amount"] for row in dealers), ZERO),
        "dealer_credit_orders": sum(row["orders"] for row in dealers),
        "split": _money_split(split),
    }


def _money_split(split):
    labels = dict(PAYMENT_CATEGORIES)
    result = OrderedDict()
    # 三格都固定列「現金→刷卡→分期→平台」四列（T-284 追加，使用者 2026-11-23），0 張也列，同一種付款方式三格同一列。
    for bucket, risk in MONEY_SPLIT_RISK.items():
        rows = []
        for key, cell in split[bucket].items():
            ages = [age for age in cell["ages"] if age is not None]
            rows.append({"key": key, "label": labels[key], "count": cell["count"], "amount": cell["amount"],
                         "estimated": cell["estimated"], "oldest": max(ages) if ages else None,
                         "payout": cell["payout"], "payout_count": cell["payout_count"],
                         "payout_estimated": cell["payout_estimated"], "customer": cell["customer"],
                         "params": {"risk": risk, "pay": key}})
        result[bucket] = rows
    return result


def _reconciliation(queryset):
    # 待入帳算訂單張數（使用者 2026-11-21，和「已交車待撥款」同單位）；分期預計金額照舊把每筆撥款加總。
    rows = list(queryset.filter(confirmed=False).values_list(
        "expected_amount", "order_id", "order__source_type", "order__status", "order__operations__actual_disbursement"))
    channels = []
    # 依撥款來源拆列（T-275 第 9 項）：平台單算平台撥款，其餘是分期公司撥款，和對帳頁 channel 同一判斷。
    for key, label in RECONCILIATION_CHANNELS:
        part = [row for row in rows if (row[2] == SalesOrder.SourceType.PLATFORM) == (key == "platform")]
        if key == "platform":
            # 平台撥款沒有預計金額（T-96），改列收支的預估車價收入，一張單算一次（T-278 D3-A）。
            expected = sum({row[1]: max(row[4] or ZERO, ZERO) for row in part}.values(), ZERO)
        else:
            expected = sum((row[0] or ZERO for row in part), ZERO)
        channel = {"key": key, "label": label, "pending": len({row[1] for row in part}), "expected": expected,
                   "estimated": key == "platform"}
        # 分期撥款待入帳拆已交車／交車前（T-278 D2-A）；已交車那部分就是「已交車待撥款・分期」的撥款。
        for side, delivered in (("delivered", True), ("before", False)):
            side_rows = [row for row in part if (row[3] in DELIVERED_STATUSES) == delivered]
            channel[side] = {"count": len({row[1] for row in side_rows}),
                             "expected": sum((row[0] or ZERO for row in side_rows), ZERO)}
        channels.append(channel)
    return {"pending": len({row[1] for row in rows}), "expected": sum((row[0] or ZERO for row in rows), ZERO),
            "channels": channels}


def _payouts():
    from sales.reporting.payouts import collect_items, totals
    result = totals(collect_items())
    return {"unpaid_amount": result["unpaid_amount"], "unpaid_count": result["unpaid_count"],
            "changed_count": result["changed_count"]}


def _active_orders():
    """訂單流程四站的在手訂單；「油電領牌」的未領牌共用這一次查詢（T-263），所以一併帶車型能源別。"""
    return list(SalesOrder.objects.filter(status__in=list(STAGE_LIMITS)).select_related("vehicle_model").only(
        "status", "established_on", "allocated_at", "registration_completed_at", "registration_date", "delivered_at",
        "vehicle_model__energy_type"))


def stage_age(order, today):
    """訂單在目前這一站停留的天數（各站起算日見 BUSINESS_RULES「營運總表顯示門檻」）；沒有起算日回傳 None。"""
    start = {
        "allocation_pending": order.established_on,
        "allocated": order.allocated_at,
        "delivery_pending": order.registration_completed_at or order.registration_date,
        "delivered_docs_pending": order.delivered_at,
    }[order.status]
    return _age_days(today, start)


def is_stuck(order, today):
    """流程卡關：停留超過該站門檻（STAGE_LIMITS）；營運總表與全部訂單 attention=stuck 共用（T-275）。"""
    age = stage_age(order, today)
    return age is not None and age > STAGE_LIMITS[order.status]


def stuck_order_ids(today=None):
    today = today or timezone.localdate()
    return [order.pk for order in _active_orders() if is_stuck(order, today)]


def _flow(metrics, today, active=None):
    active = _active_orders() if active is None else active
    ages = {key: [] for key in STAGE_LIMITS}
    counts, stuck_counts = Counter(), Counter()
    for order in active:
        counts[order.status] += 1
        age = stage_age(order, today)
        if age is not None:
            ages[order.status].append(age)
        if is_stuck(order, today):
            stuck_counts[order.status] += 1
    stages = []
    for key, limit in STAGE_LIMITS.items():
        oldest = max(ages[key]) if ages[key] else None
        stages.append({"key": key, "label": STAGE_LABELS[key], "count": counts[key], "oldest": oldest,
                       "limit": limit, "stuck": stuck_counts[key],
                       "url": _url("order_list", {"status": STAGE_FILTERS[key]})})
    return {
        "stages": stages,
        "stuck": sum(stage["stuck"] for stage in stages),
        "dealer_due": len({item["order"].pk for item in metrics["dealer_reminders"]}),
        "dealer_due_balance": len({item["order"].pk for item in metrics["dealer_reminders"]
                                   if item["kind"] == "dealer_balance"}),
        "dealer_due_documents": len({item["order"].pk for item in metrics["dealer_reminders"]
                                     if item["kind"] == "registration_documents"}),
        "dealer_due_rule": DEALER_DUE_RULE,
        "drafts": metrics["workload"]["drafts"],
    }


def aged_stock_cutoff(today, days=STOCK_AGE_ALERT_DAYS):
    """進車日在這天（含）以前＝庫齡達 days 天；營運總表與車輛庫存 age_min 共用（T-275）。"""
    return today - timedelta(days=days)


def _on_hand():
    return list(VehicleInventory.objects.filter(status__in=ON_HAND_STATUSES).select_related("vehicle_model")
                .only("status", "received_on", "vehicle_model__name", "vehicle_model__family_id"))


def model_velocity(today, live=None):
    """各車型在庫、近 90 天領牌、可銷天數與缺貨／滯銷判斷；營運總表與「缺貨風險車型」清單共用（T-275）。"""
    live = _on_hand() if live is None else live
    since = today - timedelta(days=VELOCITY_DAYS)
    sold = Counter(SalesOrder.objects.exclude(status__in=CANCELLED_STATUSES)
                   .filter(registration_confirmed_q(), registration_date__gt=since, registration_date__lte=today)
                   .values_list("vehicle_model_id", flat=True))
    stock = Counter(vehicle.vehicle_model_id for vehicle in live)
    names = dict(VehicleModel.objects.filter(pk__in=set(stock) | set(sold)).values_list("pk", "name"))
    families = dict(VehicleModel.objects.filter(pk__in=set(stock) | set(sold)).values_list("pk", "family_id"))
    rows = []
    for model_id in set(stock) | set(sold):
        on_hand, recent = stock[model_id], sold[model_id]
        cover = round(on_hand * VELOCITY_DAYS / recent) if recent else None
        shortage = recent >= SHORTAGE_MIN_SOLD and (cover or 0) < SHORTAGE_COVER_DAYS
        slow = on_hand > 0 and (recent == 0 or (cover is not None and cover > SLOW_COVER_DAYS))
        if not on_hand and not shortage:
            continue
        family = families.get(model_id)
        rows.append({"model_id": model_id, "name": names.get(model_id, "—"), "on_hand": on_hand, "sold": recent, "cover": cover,
                     "shortage": shortage, "slow": slow,
                     "url": _url("inventory_list", {"vehicle_family": family} if family else {"q": names.get(model_id, "")})})
    rows.sort(key=lambda row: (not row["shortage"], not row["slow"], -row["on_hand"], row["name"]))
    return rows


def _stock(today):
    live = _on_hand()
    status_counts = Counter(vehicle.status for vehicle in live)
    ages = [(today - vehicle.received_on).days for vehicle in live if vehicle.received_on]
    age_buckets = []
    for low, high, label in ((0, 29, "未滿 30 天"), (30, 59, "30–59 天"), (60, 89, "60–89 天"), (90, None, "90 天以上")):
        age_buckets.append({"label": label, "count": sum(1 for age in ages if age >= low and (high is None or age <= high)),
                            "alert": low >= STOCK_AGE_ALERT_DAYS})
    rows = model_velocity(today, live)
    cutoff = aged_stock_cutoff(today)
    return {
        "on_hand": len(live),
        "available": status_counts[VehicleInventory.Status.AVAILABLE],
        "reserved": status_counts[VehicleInventory.Status.RESERVED],
        "issues": status_counts[VehicleInventory.Status.CONDITION_ISSUE],
        "aging": age_buckets,
        "aged": sum(1 for vehicle in live if vehicle.received_on and vehicle.received_on <= cutoff),
        "oldest": max(ages) if ages else None,
        "models": rows[:6],
        "model_count": len(rows),
        "shortage": [row["name"] for row in rows if row["shortage"]],
        "slow": [row["name"] for row in rows if row["slow"]],
    }


def _volume_bonus(today):
    from sales.models import DealerVolumeBonusPeriod
    from sales.services.volume_bonus import group_preview, scope_dealers
    from django.db.models import Q

    periods = DealerVolumeBonusPeriod.objects.filter(
        starts_on__lte=today, ends_on__gte=today, rule__active=True,
    ).filter(Q(rule__dealer__source_type=SalesSource.SourceType.DEALER) | Q(rule__dealer__isnull=True)).select_related(
        "rule").prefetch_related("rule__tiers")
    rows = []
    for period in periods:
        for dealer in scope_dealers(period.rule, period):
            group = group_preview(period.rule, period, dealer)
            if not group["quantity"]:
                continue
            rows.append({"dealer": dealer.name, "rule": period.rule.display_name, "quantity": group["quantity"],
                         "tier": group["tier"].minimum_quantity if group["tier"] else None,
                         "next": group["next_tier"].minimum_quantity if group["next_tier"] else None,
                         "shortfall": group["shortfall"], "per_vehicle": group["bonus_per_vehicle"],
                         "ends_on": period.ends_on, "days_left": (period.ends_on - today).days})
    rows.sort(key=lambda row: (row["next"] is None, row["shortfall"], row["days_left"], row["dealer"]))
    return rows


def campaign_is_ending(campaign, today, days=CAMPAIGN_ENDING_DAYS):
    """啟用中、已開始、結束日在今天起 days 天內（含今天）；營運總表與原廠獎勵 ending_within 共用（T-275）。"""
    return (campaign.active and campaign.effective_from <= today and campaign.effective_to is not None
            and today <= campaign.effective_to <= today + timedelta(days=days))


def _campaigns(today):
    rows = []
    for campaign in IncentiveCampaign.objects.filter(active=True, effective_from__lte=today).exclude(
            effective_to__lt=today).order_by("effective_to", "name"):
        days_left = (campaign.effective_to - today).days if campaign.effective_to else None
        rows.append({"name": campaign.name, "kind": campaign.get_kind_display(), "ends_on": campaign.effective_to,
                     "days_left": days_left, "ending": campaign_is_ending(campaign, today)})
    rows.sort(key=lambda row: (row["days_left"] is None, row["days_left"] or 0, row["name"]))
    return rows


def build(period, today):
    """全部指標，不分權限；回傳純資料（可快取）。"""
    from sales.views import _reconciliation_queryset

    metrics = build_dashboard_metrics(today)
    windows = _windows(period, today)
    source = {order.pk: order for row in metrics["trend"] + metrics["trend_last_year"] for order in row["orders"]}
    source = list(source.values())
    trend_start = date.fromisoformat(metrics["trend"][0]["start"])
    active = _active_orders()

    class _Request:
        GET = {}

    return {
        "generated_at": timezone.localtime(),
        "period": period,
        "windows": windows,
        "pulse": _pulse(windows, source),
        "trend": _trend(metrics),
        "mix": _mix(windows, source, trend_start, today),
        "movers": _movers(windows, source),
        "money": _money(metrics, today),
        "reconciliation": _reconciliation(_reconciliation_queryset(_Request())),
        "payouts": _payouts(),
        "flow": _flow(metrics, today, active),
        "energy": _energy_registration(windows, source, active),
        "stock": _stock(today),
        "fee_variances": metrics["registration_fee_variances"].count(),
        "volume_bonus": _volume_bonus(today),
        "campaigns": _campaigns(today),
    }


# ── 顯示文字（比較膠囊、一句話摘要）────────────────────────────────────────


def _amount_text(value, unit):
    if value is None:
        return "—"
    return f"${value:,.0f}" if unit == "元" else f"{value:,.0f} {unit}"


def _chips(metric, unit, has_previous):
    chips = []
    for key, pct_key, label in (("previous", "vs_previous", "上月同期"), ("last_year", "vs_last_year", "去年同期")):
        if key == "previous" and not has_previous:
            continue
        base, pct = metric[key], metric[pct_key]
        if pct is None:
            tone, change = "flat", "無比較基準" if not base else ""
        else:
            tone = "up" if pct > 0 else "down" if pct < 0 else "flat"
            change = "持平" if pct == 0 else f"{pct:+.0f}%".replace("-", "−")
        chips.append({"label": label, "base": _amount_text(base, unit), "change": change, "tone": tone})
    return chips


def _headline(view, has_previous, attention_count):
    count = view["pulse"]["count"]
    period_word = {"month": "本月至今", "last_month": "上月", "ytd": "今年至今"}[view["period"]]
    parts = [{"text": f"{period_word} "}, {"text": f"{count['value']:,}", "tone": "num"}, {"text": " 台"}]
    comparisons = []
    for pct_key, label in (("vs_previous", "上月同期"), ("vs_last_year", "去年同期")):
        if pct_key == "vs_previous" and not has_previous:
            continue
        pct = count[pct_key]
        if pct is None:
            continue
        word = "持平" if pct == 0 else f"{'多' if pct > 0 else '少'} {abs(pct):.0f}%"
        comparisons.append((f"比{label}", word, "up" if pct > 0 else "down" if pct < 0 else "flat"))
    for index, (prefix, word, tone) in enumerate(comparisons):
        parts.append({"text": ("，" if index == 0 else "、") + prefix})
        parts.append({"text": word, "tone": tone})
    parts.append({"text": "；成交額 "})
    parts.append({"text": _amount_text(view["pulse"]["sales"]["value"], "元"), "tone": "num"})
    parts.append({"text": "。"})
    if attention_count:
        parts += [{"text": "有 "}, {"text": str(attention_count), "tone": "alert"}, {"text": " 件需要處理。"}]
    else:
        parts.append({"text": "目前沒有需要處理的事。"})
    return parts


# ── 依權限遮蔽 ───────────────────────────────────────────────────────────


def viewer_flags(policy, profit):
    return {
        "dashboard": policy.screen("dashboard"),
        "operations": policy.screen("operations"),
        "profit": bool(profit),
        "reconciliation": policy.screen("reconciliation"),
        "dealer_payouts": policy.screen("dealer_payouts"),
        "incentives": policy.screen("incentives"),
        "links": {name: policy.route(name) for name in (
            "order_list", "inventory_list", "reconciliation_list", "dealer_payout_list", "report_center",
            "dealer_volume_bonus_list", "incentive_rule_list", "operations_report_export", "inventory_shortage",
            "operations_dealer_credit")},
    }


def _attention(data, flags):
    """需要處理：只列有事的項目；紅色（錢有風險、庫齡過久）在前，同色依金額與件數排序。"""
    money, stock, flow, links = data["money"], data["stock"], data["flow"], flags["links"]
    order_url = lambda params: _url("order_list", params) if links["order_list"] else ""  # noqa: E731
    # 交車後未結清依付款方式拆成四項（T-275 第 9 項）；點進去是 risk＋pay 同一批單。
    items = [
        {"key": f"unsettled_{row['key']}", "label": f"交車後未結清（{UNSETTLED_LABELS[row['key']]}）",
         "value": row["count"], "unit": "張", "amount": row["amount"] if flags["operations"] else None,
         "detail": f"最久 {row['oldest']} 天" if row["oldest"] is not None else "",
         "severity": "red" if (row["oldest"] or 0) > 30 else "amber", "url": order_url(row["params"])}
        for row in money["split"]["unsettled"]
    ] + [
        {"key": "refund", "label": "取消待退款", "value": money["refund"], "unit": "張", "severity": "red",
         "url": order_url({"risk": "refund"})},
        {"key": "overpaid", "label": "溢收待退", "value": money["overpaid"], "unit": "張", "severity": "red",
         "url": order_url({"risk": "overpaid"})},
        {"key": "unconfirmed", "label": "已收款待確認", "value": money["unconfirmed"], "unit": "張",
         "severity": "amber", "url": order_url({"risk": "unconfirmed"})},
    ]
    if flags["reconciliation"]:
        for row in data["reconciliation"]["channels"]:
            shown = flags["operations"] and row["expected"]
            items.append({"key": f"reconciliation_{row['key']}", "label": row["label"], "value": row["pending"],
                          "unit": "張", "amount": row["expected"] if shown else None,
                          "detail": ("預估金額" if row["estimated"] else "預計金額") if shown else "",
                          "severity": "amber",
                          "url": _url("reconciliation_list", {"status": "pending", "by_order": 1, "channel": row["key"]})
                          if links["reconciliation_list"] else ""})
    if flags["dealer_payouts"]:
        payouts = data["payouts"]
        items.append({"key": "payouts", "label": "車行傭金／獎金未給付", "value": payouts["unpaid_count"], "unit": "項",
                      "amount": payouts["unpaid_amount"] or None, "severity": "amber",
                      "url": _url("dealer_payout_list", {"status": "unpaid"}) if links["dealer_payout_list"] else ""})
    if flags["dashboard"]:
        stuck = [stage for stage in flow["stages"] if stage["stuck"]]
        items += [
            {"key": "aged", "label": f"庫齡 {STOCK_AGE_ALERT_DAYS} 天以上", "value": stock["aged"], "unit": "台",
             "detail": f"最久 {stock['oldest']} 天" if stock["oldest"] is not None else "", "severity": "red",
             "url": _url("inventory_list", {"age_min": STOCK_AGE_ALERT_DAYS, "sort": "received_asc"})
             if links["inventory_list"] else ""},
            {"key": "shortage", "label": "缺貨風險車型", "value": len(stock["shortage"]), "unit": "款",
             "detail": "、".join(stock["shortage"][:3]), "severity": "amber",
             "url": _url("inventory_shortage") if links.get("inventory_shortage") else ""},
            {"key": "stuck", "label": "流程卡關訂單", "value": flow["stuck"], "unit": "張",
             "detail": "、".join(f"{stage['label']} {stage['stuck']}" for stage in stuck), "severity": "amber",
             "url": order_url({"attention": "stuck"})},
            {"key": "dealer_due", "label": "車行尾款／領牌到期", "value": flow["dealer_due"], "unit": "張",
             "detail": f"交車後第 {DEALER_BALANCE_DAYS} 個工作天起尾款未收清 {flow['dealer_due_balance']} 張、"
                       f"第 {DEALER_DOCUMENT_DAYS} 個工作天起領牌未完成 {flow['dealer_due_documents']} 張",
             "severity": "amber", "url": order_url({"attention": "dealer"})},
        ]
    if flags["incentives"]:
        ending = [row for row in data["campaigns"] if row["ending"]]
        items.append({"key": "campaigns", "label": f"原廠獎勵 {CAMPAIGN_ENDING_DAYS} 天內結束", "value": len(ending),
                      "unit": "項", "detail": "、".join(row["name"] for row in ending[:2]), "severity": "amber",
                      "url": _url("incentive_rule_list", {"ending_within": CAMPAIGN_ENDING_DAYS})
                      if links["incentive_rule_list"] else ""})
    for item in items:
        item.setdefault("amount", None)
        item.setdefault("detail", "")
    active = [item for item in items if item["value"]]
    active.sort(key=lambda item: (item["severity"] != "red", -(item["amount"] or 0), -item["value"]))
    clear = [item["label"] for item in items if not item["value"]]
    return active, clear


def _outstanding_terms(money, show_amounts):
    """待收合計怎麼組成（T-282）：三格（名稱、順序同卡片，T-295 依時間）＋交車後未結清那幾張的撥款；張數、金額加總＝合計。
    交車後未結清那幾張的撥款是同一批單，不另算張數；沒有 operations 權限時不給金額。"""
    terms = [{"label": "未交車・尾款待收", "count": money["before_delivery_count"],
              "amount": money["before_delivery_amount"], "estimated": money["before_delivery_estimated"]},
             {"label": "已交車待撥款", "count": money["awaiting_payout_count"],
              "amount": money["awaiting_payout_amount"], "estimated": money["awaiting_payout_estimated"]},
             {"label": "交車後未結清", "count": money["unsettled_count"], "amount": money["unsettled_amount"],
              "estimated": False}]
    if money["unsettled_payout_amount"]:
        terms.append({"label": "交車後未結清那幾張的撥款", "count": None, "amount": money["unsettled_payout_amount"],
                      "estimated": money["unsettled_payout_estimated"]})
    if not show_amounts:
        terms = [{**term, "amount": None, "estimated": False} for term in terms if term["count"] is not None]
    return terms


# 撥款待入帳對回三格（T-284）：依卡片順序（T-295 依時間）列未交車、已交車待撥款、交車後未結清；
# suffix 表示只算那幾張的撥款部分。
RECONCILIATION_TERMS = (("before_delivery", "未交車", "的撥款"), ("awaiting_payout", "已交車待撥款", ""),
                        ("unsettled", "交車後未結清", "的撥款"))


def _reconciliation_terms(reconciliation, split, show_amounts):
    """撥款待入帳兩列各自對回三格的哪幾格（T-284，使用者 2026-11-23 選 A）。

    兩邊範圍不同：撥款待入帳是統一撥款對帳裡 confirmed=False 的列（含取消單，分期金額是未入帳列的預計金額），
    三格是待收單依 money_bucket 分的格子（不含取消單，撥款金額是 lender_due＝應撥減已入帳，平台是預估）。
    所以逐格列出三格裡的撥款部分，加總和這一列相同才寫「＝」，不同就把差額寫出來（matches=False）。
    沒有 operations 權限時只比張數、不給金額。"""
    labels = dict(PAYMENT_CATEGORIES)
    channels = []
    for row in reconciliation["channels"]:
        keys = ["platform"] if row["key"] == "platform" else [key for key, _ in PAYMENT_CATEGORIES if key != "platform"]
        terms = []
        for bucket, bucket_label, suffix in RECONCILIATION_TERMS:
            for cell in split[bucket]:
                if cell["key"] not in keys or not cell["payout_count"]:
                    continue
                terms.append({"label": f"{bucket_label}・{labels[cell['key']]}", "count": cell["payout_count"],
                              "of": cell["count"] if cell["payout_count"] < cell["count"] else None, "suffix": suffix,
                              "amount": cell["payout"], "estimated": cell["payout_estimated"]})
        count = sum(term["count"] for term in terms)
        amount = sum((term["amount"] for term in terms), ZERO)
        count_gap, amount_gap = row["pending"] - count, row["expected"] - amount
        if not show_amounts:
            amount_gap = ZERO
            terms = [{**term, "amount": None, "estimated": False} for term in terms]
        channels.append({**row, "card_terms": terms, "matches": not count_gap and not amount_gap,
                         "gap": {"count": abs(count_gap), "count_more": count_gap > 0,
                                 "amount": abs(amount_gap), "amount_more": amount_gap > 0}})
    return {**reconciliation, "channels": channels, "matches": all(row["matches"] for row in channels)}


# 待收合計依付款方式拆開（T-296）：列名、順序同卡片內四列；每一列的組成依卡片順序（T-295 依時間）。
PAYMENT_ROW_LABELS = {"cash": "現金未結清", "card": "刷卡未結清", "installment": "分期待撥款", "platform": "平台待撥款"}
CARD_BUCKETS = (("before_delivery", "未交車・尾款待收"), ("awaiting_payout", "已交車待撥款"), ("unsettled", "交車後未結清"))


def _outstanding_by_payment(split, reconciliation, flags):
    """待收合計依付款方式拆成四列（T-296，使用者 2026-11-23）：每張單只有一種付款方式、只落在一格，
    所以同一種付款方式三格相加就是這一列，四列加總＝待收合計（張數、金額）。金額口徑不變：
    每格的客人應收＋撥款（交車後未結清那格的撥款另記在 payout，這裡加回來）。分期、平台列附對帳頁的撥款待入帳。"""
    show = flags["operations"]
    channels = {row["key"]: row for row in (reconciliation or {}).get("channels", [])}
    rows = []
    for key, _label in PAYMENT_CATEGORIES:
        cells = [(bucket, label, next(cell for cell in split[bucket] if cell["key"] == key))
                 for bucket, label in CARD_BUCKETS]
        customer = sum((cell["customer"] for _b, _l, cell in cells), ZERO)
        payout = sum((cell["payout"] for _b, _l, cell in cells), ZERO)
        terms = [{"label": label, "count": cell["count"],
                  "amount": cell["amount"] + (cell["payout"] if bucket == "unsettled" else ZERO),
                  "payout": cell["payout"] if bucket == "unsettled" else ZERO,
                  "payout_estimated": cell["payout_estimated"],
                  "estimated": cell["estimated"] or (bucket == "unsettled" and cell["payout_estimated"])}
                 for bucket, label, cell in cells if cell["count"]]
        row = {"key": key, "label": PAYMENT_ROW_LABELS[key], "count": sum(cell["count"] for _b, _l, cell in cells),
               "amount": customer + payout, "customer": customer, "payout": payout,
               "estimated": any(cell["estimated"] or cell["payout_estimated"] for _b, _l, cell in cells),
               "payout_estimated": any(cell["payout_estimated"] for _b, _l, cell in cells),
               "terms": terms, "recon": channels.get(key),
               "url": _url("order_list", {"risk": "outstanding", "pay": key}) if flags["links"]["order_list"] else ""}
        row["parts"] = bool(row["payout"] and row["customer"])
        if not show:
            row.update({"amount": None, "customer": None, "payout": None, "estimated": False, "parts": False,
                        "terms": [{**term, "amount": None, "payout": None, "estimated": False} for term in terms]})
        rows.append(row)
    return rows


def for_viewer(data, flags):
    """依權限組成畫面用的內容；沒有權限的區塊不放進 context，HTML 也就不會出現。"""
    pulse = dict(data["pulse"])
    trend = dict(data["trend"])
    trend["series"] = OrderedDict(data["trend"]["series"])
    if not flags["profit"]:
        pulse.pop("profit")
        trend["series"].pop("profit_total")
        trend.pop("negative_profit_months")
    if not flags["operations"]:
        pulse.pop("received")
    attention, clear = _attention(data, flags)
    view = {
        "generated_at": data["generated_at"], "period": data["period"], "periods": PERIODS,
        "windows": data["windows"], "pulse": pulse, "trend": trend, "mix": data["mix"], "movers": data["movers"],
        "attention": attention, "attention_clear": clear, "links": flags["links"], "flags": flags,
    }
    money = dict(data["money"])
    money["outstanding_terms"] = _outstanding_terms(money, flags["operations"])
    if not flags["operations"]:
        for key in ("outstanding_amount", "unsettled_amount", "unsettled_payout_amount", "before_delivery_amount",
                    "awaiting_payout_amount", "dealer_credit", "dealer_credit_total", "dealer_credit_orders"):
            money.pop(key)
        money["aging"] = [{**bucket, "amount": None} for bucket in money["aging"]]
    hidden = {} if flags["operations"] else {"amount": None, "payout": None, "customer": None}
    money["split"] = OrderedDict(
        (bucket, [{**row, **hidden, "url": _url("order_list", row["params"]) if flags["links"]["order_list"] else ""}
                  for row in rows])
        for bucket, rows in data["money"]["split"].items())
    view["money"] = money
    if flags["reconciliation"]:
        view["reconciliation"] = _reconciliation_terms(data["reconciliation"], data["money"]["split"],
                                                       flags["operations"])
    money["by_payment"] = _outstanding_by_payment(data["money"]["split"], view.get("reconciliation"), flags)
    if flags["dealer_payouts"]:
        view["payouts"] = data["payouts"]
        view["volume_bonus"] = data["volume_bonus"]
    if flags["dashboard"]:
        view.update({"flow": data["flow"], "stock": data["stock"]})
    # 已領牌和領牌台數一樣人人可看；未領牌與訂單流程同一批單，跟著訂單流程的權限（dashboard）。
    energy = {**data["energy"], "show_pending": flags["dashboard"]}
    if not flags["dashboard"]:
        energy.update({"pending": None, "rows": [{**row, "pending": None, "stages": []} for row in energy["rows"]]})
    view["energy"] = energy
    health = {}
    if flags["dashboard"]:
        health["fee_variances"] = data["fee_variances"]
    if flags["profit"]:
        health["profit_pending"] = data["pulse"]["profit"]["pending"]
    view["health"] = health
    if flags["incentives"]:
        view["campaigns"] = data["campaigns"]
    has_previous = data["windows"]["previous"] is not None
    for key, unit in (("count", "台"), ("sales", "元"), ("profit", "元"), ("new_orders", "張")):
        if key in pulse:
            pulse[key] = {**pulse[key], "chips": _chips(pulse[key], unit, has_previous)}
    if not flags["links"]["order_list"]:
        pulse["new_orders"].pop("url", None)
    view["headline"] = _headline(view, has_previous, len(attention))
    return view
