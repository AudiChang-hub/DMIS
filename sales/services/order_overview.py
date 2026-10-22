"""訂單總覽：把一張訂單的全部資料整理成唯讀清單，方便人員查看與複製。

只讀取既有欄位與顯示用屬性，不計算新金額；空白欄位以「—」顯示且不提供複製。
"""
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist

from sales.services.registration_fee import registration_rate_label

EMPTY = "—"


def _text(value):
    return str(value or "").strip()


def _date(value):
    return value.strftime("%Y/%m/%d") if value else ""


def _datetime(value):
    if not value:
        return ""
    from django.utils import timezone
    return timezone.localtime(value).strftime("%Y/%m/%d %H:%M")


def _roc(value):
    if not value:
        return ""
    year = value.year - 1911
    return f"民國 {year} 年 {value.month} 月 {value.day} 日" if year > 0 else _date(value)


def _money(value):
    """畫面顯示 $12,345；複製時給純數字 12345，貼到其他表單不必再刪符號。"""
    if value in (None, ""):
        return "", ""
    number = Decimal(str(value))
    return f"${number:,.0f}", f"{number:.0f}"


def _row(label, value, *, copy=None, wide=False, mono=False):
    value = _text(value)
    return {
        "label": label,
        "value": value or EMPTY,
        "copy": (_text(copy) if copy is not None else value) if value else "",
        "wide": wide,
        "mono": mono,
    }


def _money_row(label, value, *, skip_zero=False):
    if skip_zero and not value:
        return None
    shown, raw = _money(value)
    return _row(label, shown, copy=raw, mono=True)


def _display(order, field):
    if not getattr(order, field, None):
        return ""
    getter = getattr(order, f"get_{field}_display", None)
    return getter() if getter else getattr(order, field)


def _section(key, title, rows):
    rows = [row for row in rows if row]
    return {"key": key, "title": title, "rows": rows}


def _join(*items, sep="／"):
    return sep.join(_text(item) for item in items if _text(item))


def build_order_overview(order, *, include_finance=True):
    """回傳 {sections, tables, plain_text}；sections 為標籤／值，tables 為明細列。

    include_finance=False 時不列收入與支出明細（沒有訂單作業權限的人在訂單頁也看不到）。
    """
    model = order.vehicle_model
    vehicle = order.allocated_vehicle if order.allocated_vehicle_id else None
    legacy_identifier = ""
    if not vehicle:
        try:
            legacy_identifier = order.legacy_snapshot.vehicle_identifier
        except ObjectDoesNotExist:
            pass

    sections = [
        _section("order", "訂單", [
            _row("訂單編號", order.number, mono=True),
            _row("狀態", order.display_status),
            # 只列訂單日期：系統建單時兩者相同；匯入單的 established_on 是領牌日，已有「實際領牌日期」。
            _row("訂單日期", _date(order.order_date)),
            _row("接單人", order.accepted_name or (order.accepted_by.get_full_name() or order.accepted_by.get_username()
                                                   if order.accepted_by_id else "")),
            _row("訂單來源", order.source_display),
            _row("交易類型", _display(order, "transaction_type")),
            _row("開單公司", (order.print_company_snapshot or {}).get("legal_name", "") or (
                order.print_company.legal_name if order.print_company_id else "")),
        ]),
        _section("owner", "車主", [
            _row("車主類型", _display(order, "owner_type")),
            _row("姓名／公司名稱", order.owner_name),
            _row("英文姓名", order.owner_name_en),
            _row("證件號碼／統一編號", order.owner_id_number, mono=True),
            _row("生日（西元）", _date(order.owner_birth_date), mono=True),
            _row("生日（民國）", _roc(order.owner_birth_date)),
            _row("電話", order.owner_phone, mono=True),
            _row("Email", order.owner_email),
            _row("國籍", order.owner_nationality),
            _row("居留期限", _date(order.residence_expiry), mono=True),
            _row("戶籍／公司地址", order.owner_address, wide=True),
        ]),
        _section("vehicle", "車輛", [
            _row("廠牌", model.brand if model else ""),
            _row("車款", model.name if model else ""),
            _row("車型代碼", (model.get_model_code_display() if model and model.model_code else "")),
            _row("型號", getattr(model, "model_number", "") if model else "", mono=True),
            _row("年式", getattr(model, "model_year", "") if model else ""),
            _row("車色", order.color.name if order.color_id else ""),
            _row("引擎號碼", vehicle.engine_number if vehicle else legacy_identifier, mono=True),
            _row("車身號碼", vehicle.frame_number if vehicle else "", mono=True),
            _row("出廠年月", getattr(vehicle, "manufactured_year_month", "") if vehicle else ""),
            _row("配車時間", _datetime(order.allocated_at)),
        ]),
        _section("registration", "選號與領牌", [
            _row("選號方式", _display(order, "plate_choice")),
            _row("指定號碼與志願序", order.watched_numbers_display, wide=True),
            _row("領牌偏好備註", order.plate_preference_note, wide=True),
            _row("車牌號碼", order.final_plate_number, mono=True),
            _row("實際領牌日期", _date(order.registration_date), mono=True),
            _row("領牌縣市", _display(order, "registration_county")),
            _row("強制險期間", _display(order, "compulsory_insurance_period")),
            _row("費率級距", registration_rate_label(order.registration_rate_class, getattr(model, "displacement_cc", None))
                 if order.registration_rate_class else ""),
            _row("領牌完成", _join(_datetime(order.registration_completed_at), order.registration_completed_by, sep="　")),
        ]),
        _section("price", "金額與付款", [
            _money_row("車價", order.vehicle_price),
            _row("付款方式", "\n".join(order.payment_split_lines), wide=True),
            _money_row("牌險", order.plate_insurance_fee, skip_zero=True),
            _money_row("選號費", order.plate_selection_fee, skip_zero=True),
            _money_row("動保設定費", order.lien_registration_fee, skip_zero=True),
            _money_row("配件合計", order.accessory_total, skip_zero=True),
            _money_row("其他費用合計", order.other_fee_total, skip_zero=True),
            _money_row("已核准折扣", order.approved_discount_amount, skip_zero=True),
            _row("折扣原因", order.discount_reason if order.approved_discount_amount else ""),
            # 分期外應收＝扣訂金前客人自付的部分（使用者 2026-10-20），尾款才扣訂金。
            *([_money_row("分期外應收", order.customer_receivable_total)]
              if order.payment_type == order.PaymentType.INSTALLMENT else []),
            _money_row("訂金", order.deposit_amount),
            _row("訂金收款日", _date(order.deposit_date) if order.deposit_amount else "", mono=True),
            _row("訂金收款方式", _display(order, "deposit_method") if order.deposit_amount else ""),
            _money_row("尾款", order.customer_balance_due),
        ]),
    ]

    if order.installment_company or order.installment_periods:
        sections.append(_section("installment", "分期", [
            _row("分期公司", order.installment_company),
            _money_row("分期金額", order.installment_amount, skip_zero=True),
            _row("期數", f"{order.installment_periods} 期" if order.installment_periods else "",
                 copy=str(order.installment_periods or "")),
            _money_row("每期金額", order.installment_monthly, skip_zero=True),
            _money_row("分期開辦費", order.installment_opening_fee, skip_zero=True),
            _row("申請日期", _date(order.installment_applied_on), mono=True),
            _row("審核狀態", _display(order, "installment_status")),
            _row("核准／拒絕日期", _date(order.installment_decided_on), mono=True),
        ]))

    if order.is_trade_in_subsidy or order.trade_in_plate:
        same = order.old_owner_same_as_owner
        sections.append(_section("trade_in", "汰舊", [
            _row("舊車車牌", order.trade_in_plate, mono=True),
            _row("新舊車主", "同一人" if same else "不同人"),
            _row("舊車主姓名", order.owner_name if same else order.old_owner_name),
            _row("舊車主證件號碼", order.owner_id_number if same else order.old_owner_id_number, mono=True),
            _row("舊車主電話", order.owner_phone if same else order.old_owner_phone, mono=True),
            _row("舊車主戶籍", order.owner_address if same else order.old_owner_household_address, wide=True),
            _money_row("舊車估價", order.old_vehicle_valuation, skip_zero=True),
        ]))

    sections.append(_section("delivery", "交車", [
        _row("交車方式", _display(order, "delivery_method")),
        _row("交車地點", order.delivery_destination, wide=True),
        _row("交車完成", _join(_datetime(order.delivered_at), order.delivered_by, sep="　")),
    ]))

    if order.cancellation_requested_at or order.status == order.Status.CANCELLED:
        sections.append(_section("cancellation", "取消與退款", [
            _row("取消原因", order.cancellation_reason),
            _row("取消說明", order.cancellation_note, wide=True),
            _money_row("退款金額", order.refund_amount, skip_zero=True),
            _row("退款方式", _display(order, "refund_method")),
            _row("退款帳號／交易資訊", order.refund_reference, wide=True),
            _row("退款完成日期", _date(order.refund_completed_on), mono=True),
            _money_row("沒收金額", order.forfeited_amount, skip_zero=True),
        ]))

    sections.append(_section("note", "備註", [_row("備註", order.note, wide=True)]))

    tables = []
    accessories = list(order.accessories.all())
    if accessories:
        tables.append({
            "key": "accessories",
            "title": "加購項目與贈品",
            "columns": ("項目", "類型", "數量", "單價", "工資", "小計", "備註"),
            "numeric": (2, 3, 4, 5),
            "rows": [
                (line.name, line.get_line_type_display(), str(line.quantity), _money(line.amount)[0],
                 _money(line.labor_fee)[0], _money(line.line_total)[0], line.note or EMPTY)
                for line in accessories
            ],
        })
    fees = list(order.other_fees.all())
    if fees:
        tables.append({
            "key": "fees",
            "title": "其他費用",
            "columns": ("項目", "金額"),
            "numeric": (1,),
            "rows": [(fee.name, _money(fee.amount)[0]) for fee in fees],
        })
    subsidies = list(order.subsidy_items.all())
    if subsidies:
        tables.append({
            "key": "subsidies",
            "title": "補助項目",
            "columns": ("類別", "項目", "預計金額", "申請日期", "狀態", "備註"),
            "numeric": (2,),
            "rows": [
                (item.get_category_display(), item.item_name, _money(item.expected_amount)[0],
                 _date(item.applied_on) or EMPTY, item.get_status_display(), item.note or EMPTY)
                for item in subsidies
            ],
        })
    payments = list(order.payment_records.all()) if include_finance else []
    if payments:
        tables.append({
            "key": "payments",
            "title": "收入與支出",
            "columns": ("項目", "應收", "實收", "收款日期", "付款方式", "備註"),
            "numeric": (1, 2),
            "rows": [
                (record.item_name, _money(record.expected_amount)[0], _money(record.received_amount)[0],
                 _date(record.received_on) or EMPTY, record.payment_method or EMPTY, record.note or EMPTY)
                for record in payments
            ],
        })

    for table in tables:
        # 畫面用：每格帶欄名（手機版表格轉卡片時顯示）與是否靠右；複製用：Tab 分隔，可直接貼進試算表。
        table["lines"] = [
            {
                "copy": "	".join(row),
                "cells": [(column, cell, index in table["numeric"]) for index, (column, cell) in enumerate(zip(table["columns"], row))],
            }
            for row in table["rows"]
        ]
    return {"sections": sections, "tables": tables, "plain_text": _plain_text(order, sections, tables)}


def _plain_text(order, sections, tables):
    """「複製全部」用的純文字：一行一欄，空白欄位略過。"""
    lines = [f"{order.owner_name}　{order.number}"]
    for section in sections:
        filled = [row for row in section["rows"] if row["copy"]]
        if not filled:
            continue
        lines.extend(["", f"【{section['title']}】"])
        lines.extend(f"{row['label']}：{row['value'].replace(chr(10), '、')}" for row in filled)
    for table in tables:
        lines.extend(["", f"【{table['title']}】", "\t".join(table["columns"])])
        lines.extend("\t".join(cell for cell in row) for row in table["rows"])
    return "\n".join(lines)
