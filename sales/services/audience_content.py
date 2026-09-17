"""內容受眾與功能共用權限；未標記的發布項目僅 admin 可見。"""
from config.release_notes import RELEASES, LEGACY_UPDATES

# (版本, 更新分類) 的順序與已發布內容一一對照；不覆寫歷史發布文字。
# 每個 tuple 內全部權限皆需成立；空 tuple 表示所有已登入人員。
RELEASE_RULES = {
    ("1.10.0", "新增"): [("root",), ("screen:order_pricing",), ("root",), ("gift_distribution",)],
    ("1.10.0", "改善"): [(), ("order_start",), ("screen:profit",), ("reconciliation_list",), ("root",)],
    ("1.9.0", "新增"): [(), ("root",), ("gift_distribution",), ("root",), ("screen:order_finance",)],
    ("1.9.0", "改善"): [("order_start",), ("order_list", "internal"), ("screen:order_finance",), ("identity_documents_print",), ()],
    ("1.8.1", "修正"): [()],
    ("1.8.0", "新增"): [("catalog",), ("catalog",)],
    ("1.8.0", "改善"): [("catalog",), ("order_start",)],
    ("1.7.0", "新增"): [("order_start",), ("order_start",), ("order_recycle_bin",)],
    ("1.7.0", "改善"): [("order_start",), ("root",), ("legacy_import_list",)],
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
    from sales.models import ReleasePublication
    publications = dict(ReleasePublication.objects.values_list("version", "published_at"))
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
            history.append({**entry, "published_at": publications.get(entry["version"]), "title": entry["title"] if policy.root else "與你可用功能相關的更新", "changes": changes})
    legacy = []
    for index, entry in enumerate(LEGACY_UPDATES):
        rules = LEGACY_RULES[index] if index < len(LEGACY_RULES) else []
        items = [item for i, item in enumerate(entry["items"]) if permitted(policy, rules[i] if i < len(rules) else ("root",))]
        if items:
            legacy.append({**entry, "title": entry["title"] if policy.root else "功能改善紀錄", "items": items})
    return {"release_history": history, "legacy_updates": legacy}


# 給受限帳號的說明逐項拆開，避免共用長篇章節混入管理或財務內容。
HELP_ITEMS = (
    ("order-pricing", "下單金額調整與其他分期", ("screen:order_pricing",), (
        "admin 於帳號與權限的建立訂單分類勾選下單金額調整；車行則在合作車行的登入帳號設定同名權限。",
        "車價與配件預帶設定值，調整時請填原因。贈送的配件售價及安裝工資為零；單件合計與含數量總額自動計算。",
        "分期公司選其他／自訂分期，自填公司、期數、每期金額、開辦費；不套用車型方案的撥款或獎金，預計撥款由具對帳權限者另行核對。")),
    ("reconciliation-entry", "如何填撥款與入帳", ("reconciliation_list",), (
        "選分期公司、平台或合作車行，核對預計金額，再填實際金額、入帳日期及收款帳戶，確認後儲存。",
        "預計金額不符時展開本單特殊撥款，輸入調整值及原因。差額是實際減預計，不是淨利或全單未收餘額；未確認的零差額不代表已收款。")),
    ("news", "公告與版本歷程", (), (
        "首頁消息中心可切換公告與版本歷程，首頁只列最近兩版；點查看完整版本歷程可分頁查詢。",
        "公告依帳號對象顯示，到期後自動隱藏；點閱讀全文查看內容、圖片及連結。發布時間以台北時間呈現，未記錄的舊時間不另推估。")),
    ("announcement-admin", "發布圖文公告", ("announcement_manage",), (
        "admin 可指定公告對象為特定合作車行，搜尋車行名稱、編號、地區或分類後勾選。",
        "支援 JPEG、PNG、WebP 圖片，選檔後先預覽，儲存後才會發布；每張最多 8 MB，每則最多 8 張、單次上傳合計 24 MB。圖片沿用公告的觀看權限。")),
    ("gift-distribution", "年節送禮", ("gift_distribution",), (
        "資料維護區 → 年節送禮，先手動建立活動，再勾選車行或輸入其他對象，不會自動沿用每月價格表名單。",
        "建立時可勾選帶入預設年節送禮車行；未勾選即建立空白清單。完成後可取消完成或移除名單，所有動作留下紀錄；封存後只供查閱。",
        "開錯活動可在名單下方展開刪除，勾選確認後移除活動；保留稽核，不刪除合作車行。")),
    ("site-copy", "說明文字管理", ("root",), (
        "資料維護區 → 說明文字管理，可依頁面分類與關鍵字查找，修改頁面提示、欄位說明及訂購合約確認事項。",
        "僅接受純文字，儲存即生效並保留異動紀錄；可還原預設。列印文字有字數限制，修改後請先預覽紙本；文字不會改變權限或計算規則。")),
    ("custom-discount", "實際費用與總價折扣", ("screen:order_finance",), (
        "配件售價、工資與牌險明細可註明原因調整；系統試算值保留比對。",
        "訂單作業 → 內部折扣核准，可輸入任意折數（例如 9.25）或總價減少金額；核准後取代原優惠，不重複累加。",
        "折扣以未扣訂金及舊車折抵的總價計算，不改分期公司撥款、佣金與成本；申請後若總價改變，必須重新申請。")),
    ("order-recycle-bin", "已刪除訂單與還原", ("order_recycle_bin",), (
        "一般人員的刪除申請由 admin 核准後，訂單才移至已刪除訂單；審核前仍保留原交易。",
        "已刪除訂單不納入一般列表與統計，但原狀態、金額、附件及歷史保留；從全部訂單上方的已刪除訂單／還原入口查詢並還原。",
        "有配車或獎金等關聯的刪除與還原限 admin 確認；車輛已另行配車或異動時不直接還原，不覆蓋後續交易。")),
    ("vehicle-colors", "機種與各年式的啟用顏色", ("vehicle_model_list",), (
        "機種與售價的啟用顏色欄直接列出色名；展開年式資料可查看各年式自己的啟用顏色，不混用不同年份。",
        "沒有照片的啟用車色仍會出現在選車入口；停用色不展示。沒有啟用色時會明確提示。")),
    ("catalog-manage", "車款上架與車色圖片", ("catalog_manage",), (
        "各車色與進階主圖選檔後立即預覽，標示尚未儲存；按取消此次圖片變更可恢復原圖。預覽不會上傳，按儲存展示設定才正式送出。格式、大小或圖片損壞會提示，請重選或取消。",
        "資料維護區 → 選車展示管理，只列啟用車款（含未上架）；依品牌 → 車型 → 型號 → 能源別下拉選擇，按套用篩選。可搭配關鍵字，換頁保留條件，清除篩選回全部啟用車款。",
        "只列該機種的啟用車色，每色集中預覽、上傳與移除，可上傳 JPEG、PNG 或 WebP 圖片，每張最多 8 MB；停用色既有圖片保留。未上架圖片僅 admin 可預覽。",
        "舊主圖位於「車款主圖與既有圖片對應（進階）」，確認實際顏色後用「將既有主圖對應至車色」指定，不會自動套用至其他車色。若儲存時車款或車色已停用，須重新整理後再操作。",
        "缺少圖片仍會顯示顏色名稱與圖片待補。停用顏色或下架車款後不再公開；移除圖片保留備份檔。")),
    ("personal", "首頁與個人設定", (), (
        "首頁顯示目前帳號可用的功能與相關版本更新；未授權功能不會出現在目錄。",
        "右上角顯示目前登入姓名與帳號。請使用自己的帳號，離開共用電腦前按登出系統。",
        "忘記密碼請聯繫馭盛 admin 重設；不要與他人共用密碼。")),
    ("catalog-accounts", "選車下單", ("catalog",), (
        "從建立訂單入口開始選車，以品牌、車型、型號與能源別下拉選單縮小範圍。",
        "列表的每個啟用色各一張卡，摘要為年式／型號／型式／顏色。桌面四欄、窄版兩欄；圖片待補仍可選色。點卡片進入詳細頁時會預選該色。",
        "入口依品牌、車型、型號、能源別篩選。點車色直接顯示已選色；需要時才展開更換車色。",
        "詳細頁選現金或分期公司／期數後，在頁面最下方按確認選擇，接續填單。登入、填單與本人草稿保留選擇；只有瀏覽權限者不顯示下單按鈕。",
        "填單頁先顯示已選摘要；需要修改時按更換車款／付款方案，不清空車主資料。售價或分期變更時需重新確認，不會自動改成其他方案。")),
    ("create-order", "建立訂單與草稿", ("order_start",), (
        "主選單首頁後方的建立訂單，直接選車、選色與填資料；不必先打開全部訂單。沒有選車權限時直接填單。",
        "上架車款以外可按直接填寫訂單。正式送出前確認機種、車色、分期與附件；送出後等待馭盛接單。",
        "接待頁保留帳號已授權的主選單；按首頁或左上系統名稱可回首頁。填單內容不顯示其他訂單或內部財務，可選擇加購配件；送出只顯示本筆成立結果，可按再建立一筆或回首頁。",
        "我的接待草稿只顯示本人的資料，可加入首頁常用功能。草稿不是正式訂單；建立與查詢由 admin 分開授權。")),
    ("order-deletion", "刪除申請與審核", ("order_recycle_bin",), (
        "全部訂單點刪除訂單並說明原因；一般人員送出的是申請，狀態顯示刪除確認中，原交易與統計在核准前不變。申請人可取消尚未處理的申請。",
        "只有 admin 可以確認刪除（包括已完成訂單）或駁回申請。請先檢查配車、領牌、收款與獎金結算的影響；有關聯時須明確勾選作廢確認。",
        "刪除後退出查詢、統計與收款待辦，不移轉到新單、不代表實際退款或退車。歷史留存於回收區，含關聯的還原由 admin 核對衝突後執行。")),
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
