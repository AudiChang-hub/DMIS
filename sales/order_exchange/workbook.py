"""產生訂單匯出 xlsx（T-232）。

版面固定，之後的回匯依此讀取：
- 工作表「訂單」：第 1 列（隱藏）是欄位代碼，對應以代碼為準；第 2 列是中文表頭；第 3 列起是資料。
- A 欄「系統編號（請勿修改）」：用來對應每一張訂單。
- 表頭文字與舊「匯出營運資料」相同；只能看的欄位表頭灰底、整欄灰底並在表頭註解寫明，可回匯修改的欄位白底。
- 有選項的可修改欄位加下拉清單（選項放在隱藏的「_選項」頁）。
- 隱藏頁「_dmis」放匯出代碼的簽章，回匯時用來找回匯出紀錄、擋下別的檔或被改過代碼的檔。
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from django.core import signing
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from sales.services.excel_export import sanitize_excel_value

from .columns import BOOL, DATE, MONEY, NUMBER, display_text

SHEET_TITLE = "訂單"
META_SHEET = "_dmis"
LIST_SHEET = "_選項"
ID_KEY = "id"
ID_LABEL = "系統編號（請勿修改）"
SIGNING_SALT = "sales.order_exchange.export"
READONLY_NOTE = "只能看：改了也不會匯回。"
ORDER_PAGE_NOTE = "不可用匯回修改，請在訂單頁修改。"

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_EDITABLE_FILL = PatternFill("solid", fgColor="174C3C")
_READONLY_HEADER_FILL = PatternFill("solid", fgColor="6B7280")
_READONLY_FILL = PatternFill("solid", fgColor="F1F2F4")


def sign_token(token):
    return signing.dumps(str(token), salt=SIGNING_SALT)


def unsign_token(value):
    """回匯時用：簽章不符丟出 `signing.BadSignature`。"""
    return signing.loads(value, salt=SIGNING_SALT)


def _cell_value(value, kind):
    if value is None or value == "":
        return None
    if kind == BOOL:
        return "是" if value else "否"
    if kind == DATE and isinstance(value, (date, datetime)):
        return value
    if kind in (MONEY, NUMBER) and isinstance(value, (Decimal, int, float)):
        return int(value) if Decimal(value) == Decimal(value).to_integral_value() else float(value)
    return sanitize_excel_value(display_text(value, kind) if not isinstance(value, str) else value)


def build_workbook(token, columns, rows):
    """rows：[(訂單 pk, [欄位值…])]，欄位值來自 `columns.row_values`（與預覽同一個函式）。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE

    sheet.append([ID_KEY, *[column.key for column in columns]])
    sheet.append([ID_LABEL, *[column.label for column in columns]])
    sheet.row_dimensions[1].hidden = True
    for index, column in enumerate([None, *columns], start=1):
        header = sheet.cell(row=2, column=index)
        header.font = _HEADER_FONT
        header.fill = _EDITABLE_FILL if column is not None and column.editable else _READONLY_HEADER_FILL
        header.alignment = Alignment(vertical="center", wrap_text=True)
        if column is None or not column.editable:
            header.comment = Comment(ORDER_PAGE_NOTE if column is not None and column.order_page_only else READONLY_NOTE, "DMIS")

    for pk, values in rows:
        sheet.append([pk, *[_cell_value(value, column.kind) for value, column in zip(values, columns)]])

    last_row = sheet.max_row
    for index, column in enumerate([None, *columns], start=1):
        letter = get_column_letter(index)
        kind = column.kind if column else NUMBER
        if column is None or not column.editable:
            for (cell,) in sheet.iter_rows(min_row=3, max_row=last_row, min_col=index, max_col=index):
                cell.fill = _READONLY_FILL
        if kind == DATE:
            for (cell,) in sheet.iter_rows(min_row=3, max_row=last_row, min_col=index, max_col=index):
                cell.number_format = "yyyy-mm-dd"
        elif kind == MONEY:
            for (cell,) in sheet.iter_rows(min_row=3, max_row=last_row, min_col=index, max_col=index):
                cell.number_format = "#,##0"
        label = ID_LABEL if column is None else sheet.cell(row=2, column=index).value
        values = [sheet.cell(row=row, column=index).value for row in range(3, min(last_row, 202) + 1)]
        width = max([len(str(label))] + [len(display_text(value, kind)) for value in values if value is not None])
        sheet.column_dimensions[letter].width = min(max(width + 2, 8), 40)

    sheet.freeze_panes = "B3"
    if last_row >= 2:
        sheet.auto_filter.ref = f"A2:{get_column_letter(len(columns) + 1)}{max(last_row, 2)}"

    choice_columns = [(index, column) for index, column in enumerate(columns, start=2) if column.editable and column.choices]
    if choice_columns and last_row >= 3:
        lists = workbook.create_sheet(LIST_SHEET)
        lists.sheet_state = "hidden"
        for list_index, (index, column) in enumerate(choice_columns, start=1):
            letter = get_column_letter(list_index)
            lists.cell(row=1, column=list_index, value=column.label)
            for offset, choice in enumerate(column.choices, start=2):
                lists.cell(row=offset, column=list_index, value=choice)
            source = f"'{LIST_SHEET}'!${letter}$2:${letter}${len(column.choices) + 1}"
            validation = DataValidation(type="list", formula1=source, allow_blank=True, showErrorMessage=True,
                                        errorTitle="請從清單選擇", error=f"「{column.label}」請從下拉清單選擇。")
            sheet.add_data_validation(validation)
            target = get_column_letter(index)
            validation.add(f"{target}3:{target}{last_row}")

    meta = workbook.create_sheet(META_SHEET)
    meta.sheet_state = "veryHidden"
    meta["A1"] = "DMIS 訂單匯出"
    meta["A2"] = sign_token(token)
    meta["A3"] = "請勿修改此頁；回匯時用來核對匯出紀錄。"

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
