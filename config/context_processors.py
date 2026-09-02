from django.urls import reverse

from .app_version import get_app_version
from sales.models import UserAppearancePreference
from sales.services.mobile_quick_links import build_mobile_quick_link_context
from sales.themes import DEFAULT_THEME, THEME_DEFINITIONS, THEME_META_COLORS, THEME_VALUES


HELP_TOPIC_BY_ROUTE = {
    "dashboard": "dashboard",
    "order_list": "search-orders",
    "order_create": "create-order",
    "order_edit": "create-order",
    "order_detail": "order-work",
    "allocate_vehicle": "allocation",
    "reallocate_vehicle": "allocation",
    "order_operations": "operations",
    "operations_report": "operations",
    "reconciliation_list": "reconciliation",
    "inventory_list": "inventory",
    "inventory_create": "inventory",
    "inventory_quick_create": "inventory",
    "inventory_edit": "inventory",
    "customer_list": "master-data",
    "customer_detail": "master-data",
    "vehicle_model_list": "master-data",
    "vehicle_model_create": "master-data",
    "vehicle_model_edit": "master-data",
    "accessory_product_list": "master-data",
    "accessory_product_create": "master-data",
    "accessory_product_edit": "master-data",
    "data_maintenance": "master-data",
    "legacy_import_list": "import-data",
    "legacy_import_detail": "import-data",
    "positioned_template_list": "print-templates",
    "positioned_template_create": "print-templates",
    "positioned_template_edit": "print-templates",
    "sales_source_list": "sales-sources",
    "sales_source_staff_list": "sales-sources",
    "sales_source_platform_list": "sales-sources",
    "sales_source_category_list": "sales-sources",
    "sales_source_holiday_gift_manage": "sales-sources",
    "sales_source_create": "sales-sources",
    "sales_source_edit": "sales-sources",
    "price_list_distribution": "price-list-distribution",
    "price_list_distribution_assignments": "price-list-distribution",
    "installment_company_list": "master-data",
    "vehicle_installment_plan_list": "master-data",
    "dealer_volume_bonus_list": "master-data",
    "dealer_volume_bonus_create": "master-data",
    "dealer_volume_bonus_edit": "master-data",
    "dealer_volume_bonus_settle": "master-data",
    "dealer_volume_bonus_revise": "master-data",
    "business_holiday_list": "master-data",
    "brand_registration_fee_rule_list": "master-data",
    "settlement_cost_rule_list": "master-data",
    "settlement_cost_rule_create": "master-data",
    "settlement_cost_rule_edit": "master-data",
    "incentive_rule_list": "master-data",
    "incentive_rule_create": "master-data",
    "incentive_rule_edit": "master-data",
    "user_management": "account-management",
    "user_account_create": "account-management",
    "user_account_edit": "account-management",
    "user_account_reset_password": "account-management",
    "password_change_required": "account-management",
}


DATA_MAINTENANCE_ROUTES = {
    "data_maintenance",
    "customer_list",
    "customer_detail",
    "inventory_list",
    "inventory_create",
    "inventory_quick_create",
    "inventory_edit",
    "vehicle_model_list",
    "vehicle_model_create",
    "vehicle_model_edit",
    "accessory_product_list",
    "accessory_product_create",
    "accessory_product_edit",
    "settlement_cost_rule_list",
    "settlement_cost_rule_create",
    "settlement_cost_rule_edit",
    "incentive_rule_list",
    "incentive_rule_create",
    "incentive_rule_edit",
    "sales_source_list",
    "sales_source_staff_list",
    "sales_source_platform_list",
    "sales_source_category_list",
    "sales_source_holiday_gift_manage",
    "sales_source_create",
    "sales_source_edit",
    "price_list_distribution",
    "price_list_distribution_assignments",
    "installment_company_list",
    "vehicle_installment_plan_list",
    "dealer_volume_bonus_list",
    "dealer_volume_bonus_create",
    "dealer_volume_bonus_edit",
    "dealer_volume_bonus_settle",
    "dealer_volume_bonus_revise",
    "business_holiday_list",
    "brand_registration_fee_rule_list",
    "legacy_import_list",
    "legacy_import_detail",
    "positioned_template_list",
    "positioned_template_create",
    "positioned_template_edit",
    "positioned_template_preview",
    "positioned_template_order_print",
    "user_management",
    "user_account_create",
    "user_account_edit",
    "user_account_reset_password",
}


def app_version(request):
    route_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    topic = HELP_TOPIC_BY_ROUTE.get(route_name, "quick-start")
    ui_theme = DEFAULT_THEME
    mobile_quick_link_context = {
        "mobile_quick_links": [],
        "mobile_quick_link_options": [],
        "mobile_quick_link_slots": [],
    }
    if request.user.is_authenticated:
        saved_preference = (
            UserAppearancePreference.objects.filter(user_id=request.user.pk)
            .values("theme", "mobile_quick_links")
            .first()
        )
        saved_theme = saved_preference["theme"] if saved_preference else None
        if saved_theme in THEME_VALUES:
            ui_theme = saved_theme
        mobile_quick_link_context = build_mobile_quick_link_context(
            request.user,
            saved_preference["mobile_quick_links"] if saved_preference else [],
        )
    return {
        "app_version": get_app_version(),
        "context_help_url": f"{reverse('user_guide')}#{topic}",
        "is_data_maintenance_section": route_name in DATA_MAINTENANCE_ROUTES,
        "request_id": getattr(request, "request_id", ""),
        "ui_theme": ui_theme,
        "ui_theme_options": THEME_DEFINITIONS,
        "ui_theme_meta_color": THEME_META_COLORS[ui_theme],
        **mobile_quick_link_context,
    }
