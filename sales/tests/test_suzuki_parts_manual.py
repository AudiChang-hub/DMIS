from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.access.models import UserAccessState
from sales.models import OrderAccountProfile, SalesSource


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

    def test_staff_sees_embedded_official_manual_and_nav_entry(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("suzuki_parts_manual"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<iframe src="https://parts.example.test/"')
        self.assertContains(page, 'href="https://parts.example.test/" target="_blank" rel="noopener noreferrer"')
        self.assertContains(page, f'href="{reverse("suzuki_parts_manual")}"', count=2)

    def test_anonymous_and_dealer_cannot_open_manual(self):
        page = self.client.get(reverse("suzuki_parts_manual"))
        self.assertEqual(page.status_code, 302)
        self.client.force_login(self.dealer)
        self.assertNotEqual(self.client.get(reverse("suzuki_parts_manual")).status_code, 200)
