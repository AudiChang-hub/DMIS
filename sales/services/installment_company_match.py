"""分期公司文字對應主檔（T-266 信封客服電話、T-269 報表分期公司共用）。

自訂分期存檔後沒有分期公司主檔，只留分期公司文字。對應規則：
名稱完全相同優先；沒有時取名稱互相包含的主檔（例如「和潤」對「和潤企業」、「遠信國際股份有限公司」對「遠信國際」）。
少於 2 個字不對應。候選主檔（例如只取啟用中、只取有電話的）由呼叫端決定。
"""


def matching_installment_companies(name, companies):
    """回傳符合的主檔清單（可能 0、1 或多家）；多家時由呼叫端決定如何處理，不在這裡猜。"""
    name = (name or "").strip()
    if len(name) < 2:
        return []
    companies = list(companies)
    exact = [company for company in companies if company.name == name]
    return exact or [company for company in companies if company.name in name or name in company.name]
