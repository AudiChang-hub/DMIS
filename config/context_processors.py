from django.urls import reverse

from .app_version import get_app_version
from .release_notes import CURRENT_VERSION
from sales.models import UserAppearancePreference
from sales.services.mobile_quick_links import build_mobile_quick_link_context
from sales.services.order_intake import order_scope_label
from sales.themes import DEFAULT_THEME, THEME_DEFINITIONS, THEME_META_COLORS, THEME_VALUES


DATA_MAINTENANCE_ROUTES = {
    "permission_workspace",
    "gift_distribution", "gift_distribution_detail", "site_copy_manage", "announcement_action",
    "announcement_manage", "announcement_edit",
    "report_manage", "report_create", "report_edit",
    "data_maintenance",
    "system_diagnostics",
    "customer_list",
    "customer_detail",
    "inventory_list",
    "inventory_create",
    "inventory_quick_create",
    "inventory_edit",
    "inventory_allocation_priority",
    "vehicle_model_list",
    "vehicle_model_create",
    "vehicle_model_edit",
    "dealer_sales_program_list",
    "vehicle_model_commission",
    "accessory_product_list",
    "accessory_product_create",
    "accessory_product_edit",
    "accessory_category_list",
    "dealer_reward_catalog_list",
    "dealer_reward_catalog_create",
    "dealer_reward_catalog_edit",
    "settlement_cost_rule_list",
    "settlement_cost_rule_create",
    "settlement_cost_rule_edit",
    "incentive_rule_list",
    "incentive_rule_create",
    "incentive_rule_edit",
    "incentive_campaign_create",
    "incentive_campaign_edit",
    "dealer_reward_campaign_list",
    "dealer_reward_campaign_create",
    "dealer_reward_campaign_edit",
    "sales_source_list",
    "sales_source_staff_list",
    "sales_source_platform_list",
    "sales_source_holiday_gift_manage",
    "sales_source_create",
    "sales_source_edit",
    "price_list_distribution",
    "price_list_distribution_assignments",
    "installment_company_list",
    "vehicle_installment_plan_list",
    "subsidy_program_list",
    "dealer_volume_bonus_list",
    "dealer_volume_bonus_create",
    "dealer_volume_bonus_edit",
    "dealer_volume_bonus_delete",
    "dealer_volume_bonus_detail",
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
    "system_integrity_report",
}


def app_version(request):
    from sales.services.profit_access import profit_context
    from sales.access.services import is_root, policy_for
    from sales.access.registry import ROUTES
    access_policy = policy_for(request)
    route_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    screen_key = ROUTES.get(route_name, (None,))[0]
    # T-206：姓名選單與手機「更多」的「使用說明」一律開說明首頁（使用者：「每次點進去都不一樣，很怪」）。
    # 「這頁怎麼用」改由各頁頁首提示（help_page_tip）連到對應文章。
    context_help_url = reverse("user_guide")
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
            policy=access_policy,
        )
    return {
        **profit_context(request),
        "order_entry_url": reverse("catalog") if access_policy.route("catalog") else reverse("order_start"),
        "order_entry_visible": access_policy.route("catalog") or access_policy.route("order_start"),
        "orders_group_visible": access_policy.route("order_list"),
        "orders_group_url": reverse("order_list"),
        "orders_group_label": order_scope_label(request.user),
        "reception_mode": request.resolver_match and request.resolver_match.url_name in {"catalog", "catalog_detail", "order_start", "order_submitted"},
        "data_vehicle_visible": any(access_policy.route(name) for name in ("vehicle_brand_list", "vehicle_model_list", "settlement_cost_rule_list", "inventory_list", "accessory_product_list", "catalog_manage")),
        "data_people_visible": any(access_policy.route(name) for name in ("customer_list", "sales_source_list", "price_list_distribution", "gift_distribution")),
        "data_rules_visible": any(access_policy.route(name) for name in ("incentive_rule_list", "dealer_sales_program_list", "dealer_reward_catalog_list", "dealer_volume_bonus_list", "installment_company_list", "subsidy_program_list", "brand_registration_fee_rule_list", "business_holiday_list")),
        "data_tools_visible": any(access_policy.route(name) for name in ("positioned_template_list", "system_diagnostics")),
        "app_version": get_app_version(),
        "intake_can_submit": access_policy.route("order_start"),
        "intake_finance_editable": access_policy.screen("order_finance", "operate"),
        "release_version": CURRENT_VERSION,
        "can_manage_screen_access": is_root(request.user),
        "show_management_tools": bool(is_root(request.user) or access_policy.screen("accounts") or access_policy.screen("integrity")),
        "access_routes": {name: access_policy.route(name) for name in ROUTES},
        "screen_read_only": bool(screen_key and access_policy.configured and not access_policy.root and (not access_policy.screen(screen_key, "operate") or (route_name in {"order_edit", "order_operations"} and not access_policy.screen("order_finance", "operate")))),
        "context_help_url": context_help_url,
        "is_data_maintenance_section": route_name in DATA_MAINTENANCE_ROUTES,
        "request_id": getattr(request, "request_id", ""),
        "ui_theme": ui_theme,
        "ui_theme_options": THEME_DEFINITIONS,
        "ui_theme_meta_color": THEME_META_COLORS[ui_theme],
        **mobile_quick_link_context,
    }
