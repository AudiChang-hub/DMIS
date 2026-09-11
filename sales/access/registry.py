"""明列路由，不以 URL 前綴或命名猜測授權；新增端點必須更新覆蓋測試。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Screen:
    key: str
    label: str
    route: str
    operate: bool = True
    export: bool = False
    ceiling: str = ""


SCREENS = (
    Screen("dashboard", "戰情首頁（含全公司統計）", "dashboard", False),
    Screen("orders", "訂單、草稿與文件", "order_list", True, True),
    Screen("work", "訂單作業、配車、領牌、交付與收退款", "order_list", True, True),
    Screen("operations", "營運總表", "operations_report", False, True),
    Screen("reconciliation", "對帳作業", "reconciliation_list"),
    Screen("inventory", "車輛庫存與歷程", "inventory_list"),
    Screen("brands", "車輛品牌", "vehicle_brand_list"),
    Screen("models", "機種、售價與分期方案", "vehicle_model_list"),
    Screen("accessories", "配件與工資", "accessory_product_list"),
    Screen("rewards", "車行獎勵品項", "dealer_reward_catalog_list"),
    Screen("customers", "客戶查詢（含聯絡與歷史摘要）", "customer_list", False),
    Screen("sources", "通路與人員（合作車行、平台、本店人員、類別、節禮）", "sales_source_list"),
    Screen("distribution", "價格表分發", "price_list_distribution"),
    Screen("costs", "車輛結算成本", "settlement_cost_rule_list"),
    Screen("incentives", "原廠獎勵與補助", "incentive_rule_list"),
    Screen("commissions", "車行傭金與銷售獎勵", "dealer_sales_program_list"),
    Screen("bonuses", "車行台數獎金與結算", "dealer_volume_bonus_list"),
    Screen("installments", "分期公司", "installment_company_list"),
    Screen("fees", "領牌與強制險規則", "brand_registration_fee_rule_list"),
    Screen("holidays", "工作日與假日設定", "business_holiday_list"),
    Screen("imports", "舊資料匯入與歷史修正", "legacy_import_list"),
    Screen("templates", "列印範本設定", "positioned_template_list", True, True),
    Screen("diagnostics", "系統狀態檢查", "system_diagnostics", False),
    Screen("integrity", "系統完整性報告", "system_integrity_report", False, ceiling="superuser"),
    Screen("accounts", "帳號管理（不含畫面授權）", "user_management", ceiling="superuser"),
)
BY_KEY = {screen.key: screen for screen in SCREENS}
# 一般端點：安全方法查看，其餘方法操作；混合列表 POST 亦受控。
ROUTES = {}


def register(key, names, action="auto"):
    for name in names.split():
        if name in ROUTES:
            raise RuntimeError(f"重複權限路由：{name}")
        ROUTES[name] = (key, action)


register("dashboard", "dashboard")
register("orders", "order_list order_detail")
register("orders", "order_create order_edit draft_save draft_presence draft_delete order_edit_presence contract_upload privacy_consent_upload id_card_ocr id_card_ocr_status id_card_ocr_invalidate", "operate")
register("orders", "contract_print privacy_consent_print order_documents_print identity_documents_print", "export")
register("work", "order_operations registration_document_file subsidy_document_file")
register("work", "registration_fee_variance_confirm order_commission_attribution_update order_discount_request order_discount_decide order_secret_reveal allocate_vehicle reallocate_vehicle registration_save registration_document_upload registration_document_delete registration_complete delivery_complete delivery_payment_update cancellation_request refund_complete subsidy_toggle subsidy_document_upload subsidy_data_update subsidy_ocr_decision subsidy_document_delete", "operate")
register("work", "positioned_template_order_print", "export")
register("operations", "operations_report")
register("operations", "operations_report_export", "export")
register("reconciliation", "reconciliation_list reconciliation_update")
register("inventory", "inventory_list")
register("inventory", "inventory_create inventory_quick_create inventory_edit", "operate")
register("brands", "vehicle_brand_list")
register("models", "vehicle_model_list vehicle_model_price_versions vehicle_installment_plan_list")
register("models", "vehicle_model_create vehicle_model_edit", "operate")
register("commissions", "dealer_sales_program_list vehicle_model_commission")
register("accessories", "accessory_product_list")
register("accessories", "accessory_product_create accessory_product_edit", "operate")
register("rewards", "dealer_reward_catalog_list")
register("rewards", "dealer_reward_catalog_create dealer_reward_catalog_edit", "operate")
register("customers", "customer_list customer_detail")
register("sources", "sales_source_list sales_source_staff_list sales_source_platform_list sales_source_category_list sales_source_holiday_gift_manage")
register("sources", "sales_source_create sales_source_edit sales_source_delete sales_source_set_active sales_source_set_holiday_gift", "operate")
register("distribution", "price_list_distribution price_list_distribution_item_update price_list_distribution_assignments price_list_distribution_sync")
register("costs", "settlement_cost_rule_list")
register("costs", "settlement_cost_rule_create settlement_cost_rule_edit settlement_cost_rule_delete", "operate")
register("incentives", "incentive_rule_list")
register("incentives", "incentive_rule_create incentive_rule_edit incentive_rule_delete", "operate")
register("bonuses", "dealer_volume_bonus_list")
register("bonuses", "dealer_volume_bonus_create dealer_volume_bonus_edit dealer_volume_bonus_delete dealer_volume_bonus_settle dealer_volume_bonus_revise", "operate")
register("installments", "installment_company_list installment_company_quick_create")
register("fees", "brand_registration_fee_rule_list brand_registration_fee_rule_delete")
register("holidays", "business_holiday_list business_holiday_delete")
register("imports", "legacy_import_list legacy_import_detail legacy_import_status")
register("imports", "legacy_import_confirm legacy_import_delete legacy_import_archive legacy_import_restore legacy_import_row_decide legacy_import_master_resolve historical_buyer_replacement historical_date_change", "operate")
register("templates", "positioned_template_list")
register("templates", "positioned_template_create positioned_template_edit positioned_template_delete", "operate")
register("templates", "positioned_template_preview", "export")
register("diagnostics", "system_diagnostics")
register("integrity", "system_integrity_report")
register("accounts", "user_management")
register("accounts", "user_account_create user_account_edit user_account_status user_account_reset_password", "operate")

PERSONAL = set("system_health app_version appearance_theme_update mobile_quick_links_update user_guide password_change_required access_home login logout throttled_admin_login".split())
ROOT_ONLY = set("access_overview access_edit report_manage report_classification report_create report_edit report_draft_preview report_lifecycle".split())
REPORT_ROUTES = {"report_display": "view", "report_detail": "view", "report_records_export": "export", "report_export": "export"}
LOOKUPS = {
    "vehicle_colors": ("orders", "inventory", "models"),
    "sales_sources": ("orders", "sources", "distribution", "bonuses"),
    "installment_plan_options": ("orders", "models"),
    "vehicle_price_options": ("orders", "models"),
}
TOGGLE_RESOURCES = {
    "accessory-product": "accessories", "dealer-reward-catalog-item": "rewards",
    "brand-registration-fee-rule": "fees", "business-holiday": "holidays",
    "dealer-volume-bonus": "bonuses", "incentive-rule": "incentives",
    "installment-company": "installments", "installment-plan": "models",
    "positioned-print-template": "templates", "sales-source": "sources",
    "sales-source-category": "sources", "settlement-cost-rule": "costs",
    "vehicle-brand": "brands", "vehicle-model": "models", "vehicle-price-version": "models",
}
MEDIA_SCREENS = {"order": "orders", "draft": "orders", "vehicle": "inventory", "vehicle_history": "inventory", "payment": "work", "delivery": "work"}
SPECIAL = {"report_center", "data_maintenance", "master_record_set_active", "protected_media"}
