from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from sales.access.models import UserAccessState
from sales.models import OrderAccountProfile, SalesSource, VehicleBrand, VehicleModel


@override_settings(SUZUKI_PARTS_MANUAL_URL="https://parts.example.test/")
class SuzukiPartsManualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user("parts-staff")
        cls.dealer = User.objects.create_user("parts-dealer")
        source = SalesSource.objects.create(name="QA零件車行", source_type="dealer")
        OrderAccountProfile.objects.create(user=cls.dealer, kind="dealer", source=source)
        UserAccessState.objects.create(user=cls.dealer, configured=True)

    def render_lookup(self, user, brand, number="F4A1-123456"):
        request = RequestFactory().get("/")
        request.user = user
        model = VehicleModel(brand=brand, name="測試車")
        template = Template("{% load suzuki_parts %}{% suzuki_parts_lookup model number %}")
        return template.render(Context({"request": request, "model": model, "number": number}))

    def test_staff_is_sent_to_official_manual_and_nav_opens_new_tab(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("suzuki_parts_manual"))
        self.assertRedirects(response, "https://parts.example.test/", fetch_redirect_response=False)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, f'href="{reverse("suzuki_parts_manual")}" target="_blank" rel="noopener"', count=2)

    def test_anonymous_and_dealer_cannot_open_manual(self):
        response = self.client.get(reverse("suzuki_parts_manual"))
        self.assertTrue(response["Location"].startswith(reverse("login")))
        self.client.force_login(self.dealer)
        response = self.client.get(reverse("suzuki_parts_manual"))
        self.assertNotEqual(response.get("Location"), "https://parts.example.test/")

    def test_lookup_button_only_for_suzuki_brand_and_aliases(self):
        VehicleBrand.objects.update_or_create(name="SUZUKI", defaults={"aliases": "台鈴"})
        html = self.render_lookup(self.staff, "SUZUKI")
        self.assertIn('data-parts-lookup="F4A1-123456"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn("data-parts-lookup", self.render_lookup(self.staff, "台鈴"))
        self.assertNotIn("data-parts-lookup", self.render_lookup(self.staff, "SYM"))
        self.assertNotIn("data-parts-lookup", self.render_lookup(self.staff, "SUZUKI", number=""))
        self.assertNotIn("data-parts-lookup", self.render_lookup(self.dealer, "SUZUKI"))
