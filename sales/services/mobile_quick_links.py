from django.urls import reverse


MAX_MOBILE_QUICK_LINKS = 6

MOBILE_QUICK_LINK_DEFINITIONS = (
    {
        "key": "price-list-distribution",
        "label": "價格表分發",
        "icon": "表",
        "route": "price_list_distribution",
    },
    {
        "key": "sales-sources",
        "label": "合作車行",
        "icon": "行",
        "route": "sales_source_list",
    },
    {"key": "inventory", "label": "車輛庫存", "icon": "庫", "route": "inventory_list"},
    {
        "key": "vehicle-models",
        "label": "機種與售價",
        "icon": "型",
        "route": "vehicle_model_list",
    },
    {"key": "customers", "label": "客戶查詢", "icon": "人", "route": "customer_list"},
    {
        "key": "network-platforms",
        "label": "網路平台",
        "icon": "網",
        "route": "sales_source_platform_list",
    },
    {
        "key": "vehicle-brands",
        "label": "車輛品牌",
        "icon": "牌",
        "route": "vehicle_brand_list",
    },
    {
        "key": "accessories",
        "label": "配件與工資",
        "icon": "配",
        "route": "accessory_product_list",
    },
    {
        "key": "dealer-reward-items",
        "label": "車行獎勵品項",
        "icon": "禮",
        "route": "dealer_reward_catalog_list",
    },
    {
        "key": "staff",
        "label": "本店人員",
        "icon": "員",
        "route": "sales_source_staff_list",
    },
    {
        "key": "source-categories",
        "label": "通路類別",
        "icon": "類",
        "route": "sales_source_category_list",
    },
    {
        "key": "installment-companies",
        "label": "分期公司與方案",
        "icon": "期",
        "route": "installment_company_list",
    },
    {
        "key": "settlement-costs",
        "label": "車輛結算成本",
        "icon": "本",
        "route": "settlement_cost_rule_list",
    },
    {
        "key": "incentives",
        "label": "原廠獎勵與補助",
        "icon": "獎",
        "route": "incentive_rule_list",
    },
    {
        "key": "dealer-bonuses",
        "label": "車行台數獎金",
        "icon": "台",
        "route": "dealer_volume_bonus_list",
    },
    {
        "key": "dealer-sales-programs",
        "label": "車行傭金與銷售獎勵",
        "icon": "佣",
        "route": "dealer_sales_program_list",
    },
    {
        "key": "registration-fees",
        "label": "領牌與強制險",
        "icon": "險",
        "route": "brand_registration_fee_rule_list",
    },
    {
        "key": "business-holidays",
        "label": "工作日與假日設定",
        "icon": "曆",
        "route": "business_holiday_list",
    },
    {
        "key": "print-templates",
        "label": "列印範本設定",
        "icon": "印",
        "route": "positioned_template_list",
    },
    {
        "key": "user-management",
        "label": "帳號與權限",
        "icon": "帳",
        "route": "user_management",
        "superuser_only": True,
    },
)

DEFAULT_MOBILE_QUICK_LINK_KEYS = (
    "price-list-distribution",
    "sales-sources",
    "inventory",
    "vehicle-models",
    "customers",
    "network-platforms",
)


def available_mobile_quick_links(user):
    return [
        {**item, "url": reverse(item["route"])}
        for item in MOBILE_QUICK_LINK_DEFINITIONS
        if not item.get("superuser_only") or user.is_superuser
    ]


def normalize_mobile_quick_link_keys(user, values, *, use_default=True):
    allowed_keys = {item["key"] for item in available_mobile_quick_links(user)}
    normalized = []
    for value in values or ():
        if value in allowed_keys and value not in normalized:
            normalized.append(value)
        if len(normalized) == MAX_MOBILE_QUICK_LINKS:
            break
    if normalized or not use_default:
        return normalized
    return [key for key in DEFAULT_MOBILE_QUICK_LINK_KEYS if key in allowed_keys]


def build_mobile_quick_link_context(user, saved_values):
    options = available_mobile_quick_links(user)
    selected_keys = normalize_mobile_quick_link_keys(user, saved_values)
    by_key = {item["key"]: item for item in options}
    selected = [by_key[key] for key in selected_keys]
    slots = [
        {
            "number": number + 1,
            "value": selected_keys[number] if number < len(selected_keys) else "",
        }
        for number in range(MAX_MOBILE_QUICK_LINKS)
    ]
    return {
        "mobile_quick_links": selected,
        "mobile_quick_link_options": options,
        "mobile_quick_link_slots": slots,
    }
