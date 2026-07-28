from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/contract/", views.contract_print, name="contract_print"),
    path(
        "orders/<int:pk>/contract/upload/",
        views.contract_upload,
        name="contract_upload",
    ),
    path(
        "orders/<int:pk>/allocate/",
        views.allocate_vehicle,
        name="allocate_vehicle",
    ),
    path("inventory/", views.inventory_list, name="inventory_list"),
    path("inventory/new/", views.inventory_create, name="inventory_create"),
    path("api/colors/", views.vehicle_colors, name="vehicle_colors"),
    path("api/sources/", views.sales_sources, name="sales_sources"),
    path("api/id-card-ocr/", views.id_card_ocr, name="id_card_ocr"),
    path(
        "files/<str:model_name>/<int:pk>/<str:field_name>/",
        views.protected_media,
        name="protected_media",
    ),
]
