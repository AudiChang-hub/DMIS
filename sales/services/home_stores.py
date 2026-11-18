"""本店（馭盛、永湛）在車行選單／篩選器的固定選項（T-230，使用者 2026-11-18）。

兩間都是本店，不放進車行名單：選單最上面固定一組「本店」，和車行分開。
辨識依 `SalesSource.StaffStore`（所在店），不另建欄位、不寫死名稱。
選到本店只記錄對象名稱，不連到車行主檔，所以不會產生車行傭金、車行獎勵、掛帳或台數獎金。
"""
from sales.models import SalesSource

VALUE_PREFIX = "store:"
# 畫面順序：馭盛在前。
ORDER = (SalesSource.StaffStore.YUSHENG, SalesSource.StaffStore.YONGZHAN)


def home_store_choices():
    """[(值, 名稱)]，值形如 store:yusheng。"""
    labels = dict(SalesSource.StaffStore.choices)
    return [(f"{VALUE_PREFIX}{key}", labels[key]) for key in ORDER]


def home_store_labels():
    return [label for _, label in home_store_choices()]


def home_store_label(value):
    """選項值換成本店名稱；不是本店選項回傳空字串。"""
    return dict(home_store_choices()).get(str(value or ""), "")


def home_store_value_for_label(label):
    """已存的對象名稱若是本店，回傳對應選項值（重新開啟表單時保留選取）。"""
    return next((value for value, text in home_store_choices() if text == (label or "").strip()), "")
