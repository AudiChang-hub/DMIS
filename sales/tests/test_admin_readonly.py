from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

class ReadOnlyOperationalAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin-safety-test",
            password="safe-test-password",
        )
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.user

    def test_sales_and_account_models_are_viewable_but_not_mutable(self):
        protected_models = {
            model: model_admin
            for model, model_admin in admin.site._registry.items()
            if model._meta.app_label in {"sales", "auth"}
        }
        self.assertTrue(protected_models)

        for model, model_admin in protected_models.items():
            with self.subTest(model=model._meta.label):
                self.assertTrue(model_admin.has_view_permission(self.request))
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(model_admin.has_change_permission(self.request))
                self.assertFalse(model_admin.has_delete_permission(self.request))
                self.assertNotIn("delete_selected", model_admin.get_actions(self.request))

    def test_changelist_remains_available_while_add_view_is_denied(self):
        self.client.force_login(self.user)

        changelist = self.client.get(reverse("admin:sales_deliveryrecord_changelist"))
        add_view = self.client.get(reverse("admin:sales_deliveryrecord_add"))

        self.assertEqual(changelist.status_code, 200)
        self.assertEqual(add_view.status_code, 403)
