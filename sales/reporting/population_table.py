"""人口附表：資料庫完整分組後分頁，證號只用於內部分組、不傳入畫面。"""
from django.core.paginator import Paginator
from django.db.models import Count

from .demographics import demographic_query

HEADERS = ["車色", "車主姓名", "性別（修正分類）", "證號（遮罩）", "台數"]
NOTE = ("依車色、車主、修正性別及原證號分組；不同證號即使遮罩相同也不合併。"
        "公司或其他獨立列示，未填證號不推定為同一人；本表統計訂單台數，不代表不重複客戶人數。"
        "完整證號不出現在報表、網址或 CSV。")


def population_queryset(config, filters):
    from .engine import base_query
    return (demographic_query(base_query(config, filters), "sex", "population_sex")
            .values("color__name", "owner_name", "population_sex", "owner_id_number")
            .annotate(count=Count("pk"))
            .order_by("-count", "color__name", "owner_name", "population_sex", "owner_id_number"))


def population_cells(row):
    identity = (row["owner_id_number"] or "").strip()
    masked = (identity[:1] + "＊＊＊＊＊＊" + identity[-2:]) if len(identity) >= 4 else "已遮罩" if identity else "未填寫"
    return [row["color__name"] or "未填寫", row["owner_name"] or "未填寫", row["population_sex"], masked, row["count"]]


def population_context(config, filters, page_number):
    page = Paginator(population_queryset(config, filters), config.get("records_page_size", 100)).get_page(page_number)
    # 不讓含原證號的 ORM row 留在 template context。
    page.object_list = [{"cells": [{"label": label, "value": value} for label, value in zip(HEADERS, population_cells(row))]}
                        for row in page.object_list]
    return {"records_page": page, "records_headers": HEADERS, "records_rows": page.object_list,
            "records_note": NOTE, "records_grouped": True}
