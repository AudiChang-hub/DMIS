"""匯入銷貨列的新車／中古車判斷。

2026-10-20 起訂單不再存「車輛類別」，中古車只看交易類型＝中古車交易。匯入的重複
判斷鍵與配車占用仍需要 new／used，沿用原本的字串，已匯入列的 natural_key 不變。
"""

from sales.models import SalesOrder

NEW, USED = "new", "used"


def sales_row_category(data):
    """交易類型缺漏的舊預覽批次才看舊的 vehicle_category。"""
    transaction_type = data.get("transaction_type")
    if transaction_type:
        return USED if transaction_type == SalesOrder.TransactionType.USED else NEW
    return USED if data.get("vehicle_category") == USED else NEW


def is_new_sales_row(data):
    return sales_row_category(data) == NEW
