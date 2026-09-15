"""內容受眾與功能共用權限；未標記的發布項目僅 admin 可見。"""
from config.release_notes import RELEASES, LEGACY_UPDATES

# (版本, 更新分類) 的順序與已發布內容一一對照；不覆寫歷史發布文字。
# 每個 tuple 內全部權限皆需成立；空 tuple 表示所有已登入人員。
RELEASE_RULES = {
    ("1.6.1", "修正"): [("catalog_manage",), ("catalog_manage",)],
    ("1.6.0", "新增"): [("catalog_manage",)],
    ("1.6.0", "改善"): [("catalog_manage",), ("catalog_manage",)],
    ("1.5.0", "修正"): [("catalog",), ("vehicle_model_list",), ("catalog_manage",)],
    ("1.5.0", "新增"): [("order_recycle_bin",)],
    ("1.4.0", "新增"): [("screen:profit",), ("root",), ("catalog",), ("catalog_manage",)],
    ("1.4.0", "改善"): [("order_list", "internal"), ("root",), (), ("order_create",), ()],
    ("1.3.0", "新增"): [("catalog",), ("root",), ("root",)],
    ("1.3.0", "改善"): [("dealer",), ("root",), ("screen:order_finance",)],
    ("1.2.0", "新增"): [("order_create",), ("order_list",), ("root",), ("order_create",)],
    ("1.2.0", "改善"): [("order_receive",), ("order_create",), ("screen:order_finance",)],
    ("1.1.1", "修正"): [(), ()],
    ("1.1.0", "新增"): [("home_favorites",), ("home_favorites",), ("home_favorites",)],
    ("1.1.0", "改善"): [("home_favorites",), ("root",)],
    ("1.0.0", "新增"): [(), ()],
    ("1.0.0", "改善"): [(), ("root",)],
}
LEGACY_RULES = [
    [("operations_report",), ("root",), ("operations_report",)],
    [("legacy_import_list",), ("order_list", "internal"), ("operations_report",)],
    [("root",), ("root",), ("order_edit",)],
]


def permitted(policy, rules):
    return policy.active and all(policy.root if rule == "root" else
        policy.dealer if rule == "dealer" else
        not policy.dealer if rule == "internal" else
        policy.screen(rule[7:]) if rule.startswith("screen:") else policy.route(rule)
        for rule in rules)


def release_context(policy):
    history = []
    for entry in RELEASES:
        changes = []
        for group in entry["changes"]:
            rules = RELEASE_RULES.get((entry["version"], group["kind"]), [])
            items = [item for index, item in enumerate(group["items"])
                     if permitted(policy, rules[index] if index < len(rules) else ("root",))]
            if items:
                changes.append({"kind": group["kind"], "items": items})
        if changes:
            # 混合權限標題不能把隱藏項目的名稱洩漏給讀者。
            history.append({**entry, "title": entry["title"] if policy.root else "與你可用功能相關的更新", "changes": changes})
    legacy = []
    for index, entry in enumerate(LEGACY_UPDATES):
        rules = LEGACY_RULES[index] if index < len(LEGACY_RULES) else []
        items = [item for i, item in enumerate(entry["items"]) if permitted(policy, rules[i] if i < len(rules) else ("root",))]
        if items:
            legacy.append({**entry, "title": entry["title"] if policy.root else "功能改善紀錄", "items": items})
    return {"release_history": history, "legacy_updates": legacy}


# 給受限帳號的說明逐項拆開，避免共用長篇章節混入管理或財務內容。
HELP_ITEMS = (
    ("order-recycle-bin", "刪除與還原正式訂單", ("order_recycle_bin",), (
        "在全部訂單或訂單明細按刪除訂單，確認訂單識別、填寫原因並勾選確認後，移至已刪除訂單。操作另需 admin 授權。",
        "已刪除訂單不納入一般列表與統計，但原狀態、金額、附件及歷史保留；從全部訂單上方的已刪除訂單／還原入口查詢並還原。",
        "刪除不是取消交易或退款。有配車、領牌、交付、待退款、實收未退或獎金結算關聯時，須先處理；系統不會自行清除金流或庫存紀錄。")),
    ("vehicle-colors", "機種與各年式的啟用顏色", ("vehicle_model_list",), (
        "機種與售價的啟用顏色欄直接列出色名；展開年式資料可查看各年式自己的啟用顏色，不混用不同年份。",
        "沒有照片的啟用車色仍會出現在選車入口；停用色不展示。沒有啟用色時會明確提示。")),
    ("catalog-manage", "車款上架與車色圖片", ("catalog_manage",), (
        "各車色與進階主圖選檔後立即預覽，標示尚未儲存；按取消此次圖片變更可恢復原圖。預覽不會上傳，按儲存展示設定才正式送出。格式、大小或圖片損壞會提示，請重選或取消。",
        "資料維護區 → 選車展示管理，只列啟用車款（含未上架）；依品牌 → 車型 → 型號下拉選擇，按套用篩選。可搭配關鍵字，換頁保留條件，清除篩選回全部啟用車款。",
        "只列該機種的啟用車色，每色集中預覽、上傳與移除，可上傳 JPEG、PNG 或 WebP 圖片，每張最多 8 MB；停用色既有圖片保留。未上架圖片僅 admin 可預覽。",
        "舊主圖位於「車款主圖與既有圖片對應（進階）」，確認實際顏色後用「將既有主圖對應至車色」指定，不會自動套用至其他車色。若儲存時車款或車色已停用，須重新整理後再操作。",
        "缺少圖片仍會顯示顏色名稱與圖片待補。停用顏色或下架車款後不再公開；移除圖片保留備份檔。")),
    ("personal", "首頁與個人設定", (), (
        "首頁顯示目前帳號可用的功能與相關版本更新；未授權功能不會出現在目錄。",
        "右上角顯示目前登入姓名與帳號。請使用自己的帳號，離開共用電腦前按登出系統。",
        "忘記密碼請聯繫馭盛 admin 重設；不要與他人共用密碼。")),
    ("catalog-accounts", "選車下單", ("catalog",), (
        "從訂單入口開始選車，以車款下拉選單、品牌與能源別縮小範圍。",
        "列表的每個啟用色各一張卡，摘要為年式／型號／型式／顏色。桌面四欄、窄版兩欄；圖片待補仍可選色。點卡片進入詳細頁時會預選該色。",
        "可下單者選定車色後接續共用訂單；只有瀏覽權限者不顯示下單按鈕。")),
    ("create-order", "建立訂單與草稿", ("order_create",), (
        "全部訂單 → 建立訂單，選車後依序填車主、付款與需求；沒有選車權限時直接填單。",
        "上架車款以外可按直接填寫訂單。正式送出前確認機種、車色、分期與附件；送出後等待馭盛接單。",
        "草稿不是正式訂單；正式訂單修改需按儲存並填原因。沒有操作權限者只能查看，不可修改。")),
    ("search-orders", "訂單進度與查詢", ("order_list",), (
        "使用姓名、訂單編號或車型搜尋，選擇狀態縮小清單；車行只查本車行訂單。",
        "訂單接單後顯示接單人與時間；重新整理可取得最新狀態。")),
    ("order-sorting", "訂單列表與排序", ("order_list", "internal"), (
        "欄位依序為成立日、領牌日、車號、姓名、機種、顏色、車行／平台、狀態、備註、淨利。訂單編號放在姓名下方。",
        "直接點欄位追加排序，再點切換方向；可逐項移除與調整順位。領牌日遞減時未領牌排最前、遞增排最後。",
        "窄版機種最多 10 字元、備註 12 字元（含省略號），點文字展開完整內容。取消與退款訂單不計淨利。")),
    ("profit-access", "淨利解鎖", ("screen:profit",), (
        "有查看淨利權限仍預設鎖定。按輸入密碼查看，以目前登入者自己的密碼解鎖 5 分鐘。",
        "有效期限不因翻頁延長；可立即鎖定，改密碼、撤權、登出後需重新驗證。錯誤過多需等待。",
        "未解鎖不顯示淨利、不能依淨利排序，含淨利匯出與原始財務資料也受控；財務編輯權限另計。已下載或截圖的內容無法撤回。")),
    ("operations", "營運總表", ("operations_report",), (
        "營運總表看成交、收款風險與工作量；逐筆訂單在全部訂單，不重複列表。",
        "成交依領牌日期、排除取消／退款；本月只比較同期。淨利須另有權限並重新驗證，不代表扣除公司全部營業費用後的獲利。")),
    ("reports", "報表查詢", ("report_center",), (
        "只顯示已獲授權且發布中的報表。先選期間，再用品牌、能源等條件縮小範圍。",
        "點圖表可查來源明細；清除自己的篩選不會解除管理者設定的固定範圍。含原始財務內容的頁面需另解鎖淨利。")),
    ("account-management", "帳號與分類權限", ("root",), (
        "合作車行 → 登入帳號，可新增人員、啟停帳號、重設密碼，與帳號中心使用同一份資料。",
        "新增帳號可自行輸入，或使用車行編號＋人員序號的建議；仍是一人一帳號，不會更名既有帳號。",
        "選車入口、訂單進度、建立訂單可分別設定。各大項全選／全部取消只影響該分類，包含被搜尋隱藏的項目；內部權限需預覽確認。",
        "查看淨利在全部訂單分類獨立授權。舊帳號不會自動取得，admin 本身也需密碼解鎖。")),
)


def help_context(policy):
    return {"scoped_help": [{"id": key, "title": title, "steps": steps} for key, title, rules, steps in HELP_ITEMS if permitted(policy, rules)]}


LEGACY_HELP_RULES = {
    "mobile-shortcuts": ("internal",),
    "account-management": ("user_account_create", "user_account_edit", "user_account_reset_password"),
    "system-integrity": ("system_integrity_report", "system_diagnostics"),
    "inventory": ("inventory_list", "inventory_create"),
    "master-data": ("vehicle_model_list", "accessory_product_list", "dealer_reward_catalog_list", "installment_company_list", "business_holiday_list", "settlement_cost_rule_list", "incentive_rule_list", "dealer_volume_bonus_list", "positioned_template_list", "legacy_import_list"),
    "dealer-sales-programs": ("dealer_sales_program_list", "dealer_reward_catalog_list"),
    "dealer-volume-bonus": ("dealer_volume_bonus_list", "dealer_volume_bonus_create"),
    "sales-sources": ("sales_source_list", "sales_source_edit"),
    "price-list-distribution": ("price_list_distribution", "price_list_distribution_assignments"),
    "reconciliation": ("reconciliation_list", "reconciliation_update"),
    "ocr": ("order_create",),
    "order-work": ("order_operations", "allocate_vehicle", "delivery_complete"),
    "allocation": ("allocate_vehicle",), "subsidy": ("subsidy_toggle",),
    "registration": ("registration_save", "settlement_cost_rule_list", "incentive_rule_list", "brand_registration_fee_rule_list"),
    "delivery": ("delivery_complete",), "cancel-refund": ("refund_complete",),
    "print-templates": ("positioned_template_list", "positioned_template_create", "contract_print"),
    "import-data": ("legacy_import_list", "screen:profit"),
}
