"""現有台數表與 Excel 匯出（使用者 2026-11-03 簡報第 7 頁，口徑方案 A，見 services/stock_count.py）。"""
from io import BytesIO
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from sales.services.excel_export import sanitize_excel_row
from sales.services.stock_count import build_stock_count


def _options(request):
    brand = request.GET.get("brand", "").strip()
    only_stock = request.GET.get("show") == "stock"
    return brand, only_stock


def _inventory_url(group, row):
    """數量連到車輛庫存「現有庫存」同條件的篩選結果，方便逐台核對。"""
    params = [("brand", group.brand), *[("vehicle_family", pk) for pk in sorted(group.family_ids)], ("color", row.name)]
    return f"{reverse('inventory_list')}?{urlencode(params)}"


@login_required
def inventory_stock_count(request):
    brand, only_stock = _options(request)
    data = build_stock_count(brand)
    selected_brand = data["selected_brand"]
    for block in data["blocks"]:
        for group in block.groups:
            for row in group.rows:
                row.inventory_url = _inventory_url(group, row) if row.total else ""
            group.visible_rows = [row for row in group.rows if row.total] if only_stock else group.rows
        block.visible_groups = [group for group in block.groups if group.visible_rows]

    def link(brand_value, stock):
        query = {key: value for key, value in (("brand", brand_value), ("show", "stock" if stock else "")) if value}
        return f"?{urlencode(query)}" if query else "?"

    brand_links = [{"label": "全部品牌", "total": sum(item["total"] for item in data["brands"]),
                    "url": link("", only_stock), "active": not selected_brand}]
    brand_links += [{"label": item["value"], "total": item["total"], "url": link(item["value"], only_stock),
                     "active": item["value"] == selected_brand} for item in data["brands"]]
    return render(request, "sales/stock_count.html", {
        **data,
        "only_stock": only_stock,
        "brand_links": brand_links,
        "show_links": [{"label": "全部車色", "url": link(selected_brand, False), "active": not only_stock},
                       {"label": "只看有車", "url": link(selected_brand, True), "active": only_stock}],
        "export_query": link(selected_brand, only_stock).lstrip("?"),
    })


@login_required
def inventory_stock_count_export(request):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    brand, only_stock = _options(request)
    data = build_stock_count(brand)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "現有台數"
    bold = Font(bold=True)
    stock_fill = PatternFill("solid", fgColor="C6EFCE")
    dealer_fill = PatternFill("solid", fgColor="FFEB9C")
    head_fill = PatternFill("solid", fgColor="DDE4F0")
    thin = Side(style="thin", color="B7B7B7")
    top = Border(top=thin)

    stamp = timezone.localtime().strftime("%Y/%m/%d %H:%M")
    sheet.append(sanitize_excel_row([f"現有台數表（{data['selected_brand'] or '全部品牌'}）", "", "", "", "", f"匯出時間 {stamp}"]))
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append(["口徑：可銷售＋已預留（已配車）＋車況異常；數量含放在車行的車，車行為其中放在車行的台數。"])
    sheet.append([])
    for block in data["blocks"]:
        sheet.append(sanitize_excel_row([block.title, "", "", "", "", ""]))
        sheet.cell(sheet.max_row, 1).font = Font(bold=True, size=12)
        sheet.append(["車種型號", "車名", "顏色", "數量", "車行", "備註"])
        for cell in sheet[sheet.max_row]:
            cell.font, cell.fill = bold, head_fill
        for group in block.groups:
            rows = [row for row in group.rows if row.total] if only_stock else group.rows
            for index, row in enumerate(rows):
                notes = [text for flag, text in ((not row.active, "不生產"), (row.reserved, f"已配車 {row.reserved}"), (row.issue, f"車況異常 {row.issue}")) if flag]
                sheet.append(sanitize_excel_row([
                    group.code if index == 0 else "", group.subtitle if index == 0 else "", row.name,
                    row.total, row.dealer, "、".join(notes),
                ]))
                line = sheet.max_row
                if index == 0:
                    sheet.cell(line, 1).font = bold
                    for column in range(1, 7):
                        sheet.cell(line, column).border = top
                if row.total:
                    sheet.cell(line, 4).fill = stock_fill
                if row.dealer:
                    sheet.cell(line, 5).fill = dealer_fill
        sheet.append(sanitize_excel_row(["合計", "", "", block.total, block.dealer, ""]))
        for cell in sheet[sheet.max_row]:
            cell.font, cell.border = bold, top
        sheet.append([])
    sheet.append(sanitize_excel_row(["總計", "", "", data["totals"]["total"], data["totals"]["dealer"],
                                     f"本店 {data['totals']['store']}、已配車 {data['totals']['reserved']}、車況異常 {data['totals']['issue']}"]))
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True, size=12)
    for letter, width in zip("ABCDEF", (18, 20, 14, 8, 8, 30)):
        sheet.column_dimensions[letter].width = width
    for row in sheet.iter_rows(min_row=4):
        for cell in row[3:5]:
            cell.alignment = Alignment(horizontal="right")

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="stock-count-{timezone.localdate():%Y%m%d}.xlsx"'
    return response
