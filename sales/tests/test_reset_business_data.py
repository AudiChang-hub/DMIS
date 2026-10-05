import os
from io import StringIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from sales.access.models import ScreenAccessGrant
from sales.models import (
    BusinessHoliday,
    OrderAccountProfile,
    OrderIntakeAttachment,
    PrintCompany,
    PrintCompanyChange,
    PaymentRecord,
    SalesOrder,
    SalesSource,
    SalesSourceCategory,
    UserAccountAuditLog,
    Store,
    VehicleBrand,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)
from sales.tests import test_state_integrity as integrity


class ResetBusinessDataTests(TestCase):
    setUp = integrity.StateIntegrityTests.setUp
    make_order = integrity.StateIntegrityTests.make_order
    vehicle = integrity.StateIntegrityTests.vehicle

    def run_reset(self, confirm=""):
        out = StringIO()
        call_command("reset_business_data", confirm=confirm, stdout=out)
        return out.getvalue()

    def test_preview_changes_nothing(self):
        self.make_order(dealer=True)
        output = self.run_reset()
        self.assertIn("預覽模式", output)
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_confirm_clears_business_and_master_data_but_keeps_accounts(self):
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True)
        categories = SalesSourceCategory.objects.count()
        holidays = BusinessHoliday.objects.count()
        order, _vehicle = self.make_order(dealer=True)
        self.vehicle("SPARE")
        dealer = get_user_model().objects.create_user("dealer-a", password="Dealer-pass-925!")
        OrderAccountProfile.objects.create(user=dealer, kind="dealer", source=self.source, order_scope="dealer")
        staff = OrderAccountProfile.objects.create(user=self.user, kind="internal", source=self.source, order_scope="dealer")
        own = PrintCompany.objects.create(key="own", legal_name="本店", tax_id="12345678", address="台北", phone="02")
        dealer_company = PrintCompany.objects.create(key="dealer", source=self.source, legal_name="車行",
                                                     tax_id="87654321", address="新北", phone="02")
        PrintCompanyChange.objects.create(company=dealer_company, order=order, actor=self.user)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            attachment = OrderIntakeAttachment(order=order, name="a.jpg", kind="supplement", checksum="x", uploaded_by=self.user)
            attachment.file.save("a.jpg", ContentFile(b"x"), save=True)
            path = attachment.file.path
            output = self.run_reset("清除全部業務資料")
            self.assertFalse(os.path.exists(path))
        self.assertIn("已清除", output)
        for model in (SalesOrder, PaymentRecord, VehicleInventory, VehicleModel, VehicleColor,
                      VehicleBrand, SalesSource, OrderIntakeAttachment, PrintCompanyChange):
            self.assertFalse(model.objects.exists(), model.__name__)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertTrue(ScreenAccessGrant.objects.filter(user=self.user).exists())
        self.assertEqual(SalesSourceCategory.objects.count(), categories)
        self.assertEqual(BusinessHoliday.objects.count(), holidays)
        self.assertTrue(Store.objects.filter(pk=self.store.pk).exists())
        self.assertTrue(PrintCompany.objects.filter(pk=own.pk).exists())
        self.assertFalse(PrintCompany.objects.exclude(source=None).exists())
        dealer.refresh_from_db()
        self.assertFalse(dealer.is_active)
        self.assertEqual(dealer.order_account.source_id, None)
        self.assertTrue(UserAccountAuditLog.objects.filter(target=dealer, action="deactivate").exists())
        staff.refresh_from_db()
        self.assertEqual((staff.source_id, staff.order_scope), (None, "own"))
        self.assertIn("dealer-a", output)
