from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from .auth_views import ThrottledAdminLoginView, ThrottledLoginView

handler400 = "sales.views.bad_request"
handler403 = "sales.views.permission_denied"
handler404 = "sales.views.page_not_found"
handler500 = "sales.views.server_error"

urlpatterns = [
    path(
        "admin/login/",
        ThrottledAdminLoginView.as_view(template_name="registration/login.html"),
        name="throttled_admin_login",
    ),
    path("admin/", admin.site.urls),
    path(
        "login/",
        ThrottledLoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("sales.urls")),
]

