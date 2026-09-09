"""雙分類、多指標彙總表；獎金讀取已保存分配，不重算業務規則。"""
import json

from django.db.models import Count, F, Sum
from .financial_query import with_saved_bonus


def summary_result(config, card, filters):
    from .engine import (AGGREGATES, DIMENSIONS, METRICS, MAX_GROUPS, base_query,
                         dimension_query, dimension_labels, dimension_label, encode_key,
                         format_value, scope_labels)

    metrics = [card["metric"], *card.get("additional_metrics", [])]
    dimensions = [card["dimension"]] + ([card["series"]] if card.get("series") else [])
    queryset = base_query(config, filters, card)
    aggregates = dict(AGGREGATES)
    financial = bool({"dealer_commission", "dealer_bonus"}.intersection(metrics))
    if financial:
        aggregates["financial_count"] = Count("operations__pk")
        aggregates["dealer_commission"] = Sum("operations__dealer_commission_expense")
    if "dealer_bonus" in metrics:
        # 先按訂單彙總，避免一張訂單多筆分配 JOIN 後把台數與車價倍增。
        queryset = with_saved_bonus(queryset)
        aggregates["dealer_bonus"] = Sum("report_saved_bonus")

    totals = queryset.aggregate(**aggregates)
    fields = ["report_key", "report_series"][:len(dimensions)]
    for dimension, field in zip(dimensions, fields):
        queryset = dimension_query(queryset, dimension, config["date_basis"], field)
    grouped = queryset.values(*fields).annotate(**aggregates)
    ordering = [F(fields[0]).desc(nulls_last=True)] if card["sort"] == "key_desc" else [fields[0]]
    if card["sort"] == "value":
        ordering = [F(card["metric"]).desc(nulls_last=True), fields[0]]
    elif card['sort'] == 'value_asc':
        ordering = [F(card['metric']).asc(nulls_first=True), fields[0]]
    rows = list(grouped.order_by(*ordering, *fields[1:])[:min(card["limit"], MAX_GROUPS) + 1])
    truncated = len(rows) > card["limit"]
    rows = rows[:card["limit"]]
    labels = [dimension_labels(dimension, [row[field] for row in rows if row[field] is not None])
              for dimension, field in zip(dimensions, fields)]

    def cell(row, metric):
        missing = metric in ("dealer_commission", "dealer_bonus") and row["financial_count"] != row["count"]
        value = None if missing else row[metric] or 0
        return {"value": str(value) if value is not None else None,
                "display": "待補收支資料" if missing else format_value(value)}

    values = []
    for row in rows:
        names = [dimension_label(dimension, row[field], mapping)
                 for dimension, field, mapping in zip(dimensions, fields, labels)]
        keys = [encode_key(row[field]) for field in fields]
        key = "c:" + json.dumps(keys, separators=(",", ":")) if len(keys) == 2 else keys[0]
        cells = [cell(row, metric) for metric in metrics]
        values.append({"key": key, "label": " · ".join(names), "dimension_cells": names,
                       "metric_cells": cells, "count": row["count"], **cells[0]})
    total = cell(totals, metrics[0])
    note = ""
    if financial:
        note = ("金額讀取 DMIS 保存紀錄，不重算原報表獎金公式。車行傭金支出可能已含台數獎金，"
                "兩欄不可再相加；人工總額不推測基礎傭金拆分。已分配台數獎金不含未結算試算，零值不代表沒有應付獎金；以上均不代表已付款。")
        if totals["count"] != totals["financial_count"]:
            note += " 範圍內有訂單缺少收支資料，受影響群組與總額暫不顯示。"
    return {"card": card, "rows": values, "total": total["display"], "raw_total": total["value"],
            "count": totals["count"], "truncated": truncated, "summary_table": True,
            "table_dimension_labels": [DIMENSIONS[key] for key in dimensions],
            "table_metric_labels": [METRICS[key] for key in metrics],
            "table_total_cells": [cell(totals, metric) for metric in metrics],
            "table_colspan": len(dimensions) + len(metrics),
            "dimension_label": "／".join(DIMENSIONS[key] for key in dimensions),
            "metric_label": METRICS[card["metric"]], "financial_note": note,
            "compatibility_note": "按原銷售車行彙總；實際台數／傭金歸屬請看來源明細，本表不取代 DMIS 結算。" if 'legacy_dealer' in dimensions and financial else ("原報表分類只供比對，不修改 DMIS 主檔或財務歸屬。" if any(key.startswith("legacy_") for key in dimensions) else ""),
            "scope_labels": scope_labels(card.get("fixed_filters", {})), "series_truncated": False}
