import io
import tempfile
import uuid
from datetime import timedelta
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone
from sales.models import (
    VehicleModel,
    VehicleColor,
    VehicleCatalogEntry,
    VehiclePriceVersion,
    SalesSource,
    OrderAccountProfile,
    UserAccountAuditLog,
    InstallmentCompany,
    InstallmentPlanVersion,
    InstallmentPlanOption,
)
from sales.access.models import UserAccessState


class CatalogAccountTests(TestCase):
    def test_csrf_protects_account_and_catalog_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.root)
        for url in [
            reverse("dealer_account_create", args=[self.source.pk]),
            reverse("catalog_edit", args=[self.model.pk]),
        ]:
            self.assertEqual(client.post(url, {}).status_code, 403)

    def test_password_reset_keeps_binding_and_requires_change(self):
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("user_account_reset_password", args=[self.dealer.pk]),
            {
                "password1": "Reset-test-8032!",
                "password2": "Reset-test-8032!",
                "must_change_password": "on",
            },
        )
        self.assertRedirects(
            response, reverse("dealer_accounts", args=[self.source.pk])
        )
        self.dealer.refresh_from_db()
        self.assertTrue(self.dealer.check_password("Reset-test-8032!"))
        self.assertTrue(self.dealer.security_profile.must_change_password)
        self.assertEqual(self.dealer.order_account.source, self.source)

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        User = get_user_model()
        self.root = User.objects.create_superuser("admin", password="Test-admin-925!")
        self.internal = User.objects.create_user("staff", password="Test-staff-925!")
        self.source = SalesSource.objects.create(
            name="甲合作車行", source_type="dealer"
        )
        self.other = SalesSource.objects.create(name="乙合作車行", source_type="dealer")
        self.dealer = User.objects.create_user("dealer", password="Test-dealer-925!")
        self.profile = OrderAccountProfile.objects.create(
            user=self.dealer, kind="dealer", source=self.source
        )
        UserAccessState.objects.create(user=self.dealer, configured=True)
        self.model = VehicleModel.objects.create(
            brand="TEST", name="展示用車款", energy_type="gas", displacement_cc=125
        )
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="白色")
        self.entry = VehicleCatalogEntry.objects.create(
            vehicle_model=self.model, published=True, description="測試車款介紹"
        )

    def image(self):
        data = io.BytesIO()
        Image.new("RGB", (24, 24), "teal").save(data, format="PNG")
        return SimpleUploadedFile(
            "photo.png", data.getvalue(), content_type="image/png"
        )

    def create_payload(self, **changes):
        data = {
            "order_scope": "own", "can_print_documents": "on",
            "display_name": "車行人員",
            "username": "new-dealer",
            "password1": "Strong-test-7302!",
            "password2": "Strong-test-7302!",
            "is_active": "on",
            "can_submit_orders": "on",
            "can_view_orders": "on", "can_browse_catalog": "on",
        }
        data.update(changes)
        return data

    def edit_payload(self, **changes):
        data = {
            "order_scope": "own", "can_print_documents": "on",
            "display_name": "車行人員",
            "username": self.dealer.username,
            "is_active": "on",
            "can_submit_orders": "on",
            "can_view_orders": "on", "can_browse_catalog": "on",
            "expected_revision": "0",
        }
        data.update(changes)
        return data

    def test_public_listing_hides_unpublished_and_inactive(self):
        self.assertContains(self.client.get(reverse("catalog")), self.model.name)
        self.entry.published = False
        self.entry.save()
        self.assertNotContains(self.client.get(reverse("catalog")), self.model.name)
        self.assertEqual(
            self.client.get(
                reverse("catalog_detail", args=[self.model.pk])
            ).status_code,
            404,
        )
        self.entry.published = True
        self.entry.save()
        self.model.active = False
        self.model.save()
        self.assertNotContains(self.client.get(reverse("catalog")), self.model.name)

    def test_catalog_search_filter_and_pagination(self):
        self.assertContains(
            self.client.get(
                reverse("catalog"), {"q": "展示", "brand": "TEST", "energy": "gas"}
            ),
            self.model.name,
        )
        self.assertNotContains(
            self.client.get(reverse("catalog"), {"energy": "electric"}), self.model.name
        )
        self.assertEqual(
            self.client.get(reverse("catalog"), {"page": "bad"}).status_code, 200
        )

    def test_prices_and_plans_exclude_internal_fields_and_expired(self):
        today = timezone.localdate()
        VehiclePriceVersion.objects.create(
            vehicle_model=self.model,
            cash_price=72000,
            suggested_price=75000,
            effective_from=today,
            source_note="INTERNAL-PRICE-NOTE",
        )
        company = InstallmentCompany.objects.create(name="測試分期公司")
        plan = InstallmentPlanVersion.objects.create(
            vehicle_model=self.model, effective_from=today
        )
        InstallmentPlanOption.objects.create(
            version=plan,
            company=company,
            periods=24,
            monthly_amount=3000,
            opening_fee=500,
            expected_disbursement_fixed_amount=65432,
        )
        response = self.client.get(reverse("catalog_detail", args=[self.model.pk]))
        self.assertEqual(response.context["price"], 72000)
        self.assertContains(response, "24 期")
        self.assertNotContains(response, "65432")
        self.assertNotContains(response, "INTERNAL-PRICE-NOTE")
        plan.effective_to = today - timedelta(days=1)
        plan.effective_from = today - timedelta(days=10)
        plan.save()
        self.assertNotContains(
            self.client.get(reverse("catalog_detail", args=[self.model.pk])), "24 期"
        )

    def test_order_prefill_survives_login_redirect(self):
        response = self.client.get(
            reverse("order_create"), {"model": self.model.pk, "color": self.color.pk}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)
        self.client.force_login(self.dealer)
        response = self.client.get(
            reverse("order_create"), {"model": self.model.pk, "color": self.color.pk}
        )
        self.assertEqual(
            str(response.context["form"]["vehicle_model"].value()), str(self.model.pk)
        )
        self.assertEqual(
            str(response.context["form"]["color"].value()), str(self.color.pk)
        )

    def test_catalog_admin_only_and_revision(self):
        self.client.force_login(self.internal)
        self.assertEqual(self.client.get(reverse("catalog_manage")).status_code, 403)
        self.client.force_login(self.root)
        url = reverse("catalog_edit", args=[self.model.pk])
        self.assertEqual(
            self.client.post(
                url,
                {
                    "description": "新介紹",
                    "published": "on",
                    "position": 0,
                    "expected_revision": 0,
                    "image": self.image(),
                },
            ).status_code,
            302,
        )
        self.assertContains(
            self.client.post(
                url, {"description": "過期修改", "position": 0, "expected_revision": 0}
            ),
            "已被其他視窗更新",
        )
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.description, "新介紹")

    def test_image_validation_and_unpublish_revokes_download(self):
        self.client.force_login(self.root)
        url = reverse("catalog_edit", args=[self.model.pk])
        bad = SimpleUploadedFile(
            "attack.svg", b'<svg onload="alert(1)"></svg>', content_type="image/svg+xml"
        )
        self.assertEqual(
            self.client.post(
                url, {"position": 0, "expected_revision": 0, "image": bad}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                url,
                {
                    "position": 0,
                    "expected_revision": 0,
                    "published": "on",
                    "image": self.image(),
                },
            ).status_code,
            302,
        )
        self.client.logout()
        response = self.client.get(reverse("catalog_image", args=[self.model.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content))
        VehicleCatalogEntry.objects.filter(pk=self.entry.pk).update(published=False)
        self.assertEqual(
            self.client.get(reverse("catalog_image", args=[self.model.pk])).status_code,
            404,
        )

    def test_create_account_atomic_binding_no_privilege_escalation(self):
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("dealer_account_create", args=[self.source.pk]),
            self.create_payload(
                is_superuser="on", source=self.other.pk, must_change_password=""
            ),
        )
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="new-dealer")
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual(user.order_account.source, self.source)
        self.assertEqual(user.order_account.kind, "dealer")
        self.assertTrue(user.security_profile.must_change_password)
        self.assertTrue(user.check_password("Strong-test-7302!"))
        self.assertTrue(
            UserAccountAuditLog.objects.filter(target=user, action="create").exists()
        )
        self.assertContains(
            self.client.get(
                reverse("user_management"), {"kind": "dealer", "source": self.source.pk}
            ),
            "new-dealer",
        )
        self.assertNotIn(
            "new-dealer",
            [
                u.username
                for u in self.client.get(
                    reverse("user_management"), {"kind": "internal"}
                ).context["accounts"]
            ],
        )

    def test_bad_password_and_duplicate_create_nothing(self):
        self.client.force_login(self.root)
        before = get_user_model().objects.count()
        for changes in [
            {"password1": "x", "password2": "y"},
            {"username": self.dealer.username},
        ]:
            self.assertEqual(
                self.client.post(
                    reverse("dealer_account_create", args=[self.source.pk]),
                    self.create_payload(**changes),
                ).status_code,
                200,
            )
        self.assertEqual(get_user_model().objects.count(), before)

    def test_only_root_manages_dealer_accounts_in_both_entries(self):
        manager = get_user_model().objects.create_superuser(
            "manager", password="Test-manager-925!"
        )
        for actor in [manager, self.internal, self.dealer]:
            self.client.force_login(actor)
            for name, args in [
                ("dealer_accounts", [self.source.pk]),
                ("dealer_account_create", [self.source.pk]),
                ("dealer_account_edit", [self.dealer.pk]),
                ("user_account_edit", [self.dealer.pk]),
                ("user_account_status", [self.dealer.pk]),
                ("user_account_reset_password", [self.dealer.pk]),
            ]:
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code,
                    403,
                    (actor.username, name),
                )

    def test_readonly_revoke_blocks_post_and_hides_controls(self):
        self.client.force_login(self.root)
        url = reverse("dealer_account_edit", args=[self.dealer.pk])
        self.assertEqual(
            self.client.post(url, self.edit_payload(can_submit_orders="")).status_code,
            302,
        )
        self.client.force_login(self.dealer)
        self.assertContains(self.client.get(reverse("dashboard")), "唯讀進度")
        self.assertNotContains(
            self.client.get(reverse("catalog_detail", args=[self.model.pk])),
            "選這台，開始下單",
        )
        for name in ["order_create", "draft_save", "draft_delete", "id_card_ocr"]:
            args = [uuid.uuid4()] if name == "draft_delete" else []
            self.assertEqual(
                self.client.post(reverse(name, args=args), {}).status_code, 403
            )
        self.assertEqual(self.client.get(reverse("order_list")).status_code, 200)

    def test_edit_conflict_and_source_forgery(self):
        self.client.force_login(self.root)
        url = reverse("dealer_account_edit", args=[self.dealer.pk])
        self.assertEqual(
            self.client.post(
                url, self.edit_payload(source=self.other.pk, is_superuser="on")
            ).status_code,
            302,
        )
        self.assertContains(
            self.client.post(url, self.edit_payload()), "已被其他視窗更新"
        )
        self.profile.refresh_from_db()
        self.dealer.refresh_from_db()
        self.assertEqual(self.profile.source_id, self.source.pk)
        self.assertFalse(self.dealer.is_superuser)

    def test_deactivation_preserves_account(self):
        self.client.force_login(self.root)
        self.assertEqual(
            self.client.post(
                reverse("dealer_account_edit", args=[self.dealer.pk]),
                self.edit_payload(is_active=""),
            ).status_code,
            302,
        )
        self.dealer.refresh_from_db()
        self.assertFalse(self.dealer.is_active)
        self.assertTrue(OrderAccountProfile.objects.filter(user=self.dealer).exists())

    def test_inactive_source_cannot_open_account(self):
        self.source.active = False
        self.source.save()
        self.client.force_login(self.root)
        self.assertContains(
            self.client.post(
                reverse("dealer_account_create", args=[self.source.pk]),
                self.create_payload(),
            ),
            "此車行已停用",
        )
        self.assertFalse(
            get_user_model().objects.filter(username="new-dealer").exists()
        )

    def test_dealer_navigation_excludes_internal_management(self):
        self.client.force_login(self.dealer)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "車行工作台")
        self.assertNotContains(response, "營運總表")
        self.assertNotContains(response, "資料維護區")
        self.assertEqual(
            self.client.get(
                reverse("dealer_accounts", args=[self.other.pk])
            ).status_code,
            403,
        )

    def test_access_editor_redirects_to_effective_dealer_permissions(self):
        self.client.force_login(self.root)
        self.assertRedirects(
            self.client.get(reverse("access_edit", args=[self.dealer.pk])),
            reverse("dealer_account_edit", args=[self.dealer.pk]),
        )
        self.assertRedirects(
            self.client.get(reverse("user_account_edit", args=[self.dealer.pk])),
            reverse("dealer_account_edit", args=[self.dealer.pk]),
        )
