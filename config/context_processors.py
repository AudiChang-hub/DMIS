from django.urls import reverse

from .app_version import get_app_version


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
}


def app_version(request):
    route_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    topic = HELP_TOPIC_BY_ROUTE.get(route_name, "quick-start")
    return {
        "app_version": get_app_version(),
        "context_help_url": f"{reverse('user_guide')}#{topic}",
        "request_id": getattr(request, "request_id", ""),
    }
