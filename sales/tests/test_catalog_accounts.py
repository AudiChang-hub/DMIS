import io
import tempfile
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
from sales.access.models import ScreenAccessGrant, UserAccessState


class CatalogAccountTests(TestCase):
    def test_csrf_protects_account_and_catalog_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.root)
        for url in [
            reverse("user_account_reset_password", args=[self.clerk.pk]),
            reverse("catalog_edit", args=[self.model.pk]),
        ]:
            self.assertEqual(client.post(url, {}).status_code, 403)

    def test_password_reset_keeps_binding_and_requires_change(self):
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("user_account_reset_password", args=[self.clerk.pk]),
            {
                "password1": "Reset-test-8032!",
                "password2": "Reset-test-8032!",
                "must_change_password": "on",
            },
        )
        self.assertRedirects(
            response, reverse("user_management"), fetch_redirect_response=False
        )
        self.clerk.refresh_from_db()
        self.assertTrue(self.clerk.check_password("Reset-test-8032!"))
        self.assertTrue(self.clerk.security_profile.must_change_password)
        self.assertEqual(self.clerk.order_account.source, self.store)
        self.assertEqual(self.clerk.order_account.order_scope, "own")
        self.assertTrue(
            UserAccountAuditLog.objects.filter(target=self.clerk, action="reset_password").exists()
        )

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        User = get_user_model()
        self.root = User.objects.create_superuser("admin", password="Test-admin-925!")
        self.internal = User.objects.create_user("staff", password="Test-staff-925!")
        # 只能建立與查本人訂單的店內人員；source＝預設店別。
        self.store = SalesSource.objects.create(name="本店", source_type="store")
        self.clerk = User.objects.create_user("clerk", password="Test-clerk-925!")
        self.profile = OrderAccountProfile.objects.create(
            user=self.clerk, order_scope="own", source=self.store
        )
        UserAccessState.objects.create(user=self.clerk, configured=True)
        for screen_key in ("orders", "order_intake"):
            ScreenAccessGrant.objects.create(user=self.clerk, screen_key=screen_key, view=True, operate=True)
        self.model = VehicleModel.objects.create(
            brand="TEST", name="展示用車款", energy_type="gas", displacement_cc=125
        )
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="白色")
        self.entry = VehicleCatalogEntry.objects.update_or_create(vehicle_model=self.model, defaults=dict(published=True, description="測試車款介紹"))[0]

    def image(self):
        data = io.BytesIO()
        Image.new("RGB", (24, 24), "teal").save(data, format="PNG")
        return SimpleUploadedFile(
            "photo.png", data.getvalue(), content_type="image/png"
        )

    def test_public_listing_hides_unpublished_and_inactive(self):
        self.assertContains(self.client.get(reverse("catalog")), self.model.name)
        # 未登入只能瀏覽列表；點進車款明細須先登入。
        detail_url = reverse("catalog_detail", args=[self.model.pk])
        self.assertRedirects(self.client.get(detail_url), f"{reverse('login')}?next={detail_url}", fetch_redirect_response=False)
        listing = self.client.get(reverse("catalog")).content.decode()
        self.assertIn("登入後接單", listing)
        self.assertIn(f"?next={reverse('order_start')}%3Fmodel%3D{self.model.pk}%26color%3D", listing)
        self.client.force_login(self.internal)
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

    def test_card_button_starts_intake_with_model_and_color(self):
        # 使用者 2026-10-15：選車卡片的按鈕直接接單，不再經過車款明細頁。
        self.client.force_login(self.root)
        listing = self.client.get(reverse("catalog")).content.decode()
        self.assertIn(f'href="{reverse("order_start")}?model={self.model.pk}&amp;color={self.color.pk}">選這台接單</a>', listing)
        self.assertNotIn("查看車款與分期", listing)

    def test_public_cards_show_cash_and_suggested_price(self):
        VehiclePriceVersion.objects.create(vehicle_model=self.model, cash_price=72000, suggested_price=75000,
                                           effective_from=timezone.localdate())
        listing = self.client.get(reverse("catalog")).content.decode()
        self.assertIn("<dt>現金價</dt><dd>NT$ 72,000</dd>", listing)
        self.assertIn("<dt>分期總價</dt><dd>NT$ 75,000</dd>", listing)

    def test_prices_and_plans_exclude_internal_fields_and_expired(self):
        self.client.force_login(self.internal)
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
        self.client.force_login(self.clerk)
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

    def test_staff_without_admin_rights_cannot_manage_user_accounts(self):
        for actor in [self.internal, self.clerk]:
            self.client.force_login(actor)
            for name, args in [
                ("user_account_edit", [self.clerk.pk]),
                ("user_account_status", [self.clerk.pk]),
                ("user_account_reset_password", [self.clerk.pk]),
            ]:
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code,
                    403,
                    (actor.username, name),
                )
