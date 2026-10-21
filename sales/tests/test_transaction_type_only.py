"""車輛類別併入交易類型（1.86.25，使用者 2026-10-20）：只留交易類型、訂購單改印交易類型、欄位刪除可逆。"""
from io import BytesIO

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, tag
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from sales.forms import SalesOrderForm
from sales.models import SalesOrder
from sales.services.document_signing import contract_terms
from sales.services.order_contract_pdf import build_order_contract_pdf
from sales.tests import test_document_signing as signing
from sales.tests import test_order_flow as flow


def pdf_lines(content):
    return [line.strip() for page in PdfReader(BytesIO(content)).pages for line in page.extract_text().splitlines()]


class TransactionTypeOnlyTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order
    sign = signing.DocumentSigningTests.sign

    def test_model_and_form_no_longer_have_vehicle_category(self):
        self.assertNotIn("vehicle_category", {field.name for field in SalesOrder._meta.get_fields()})
        self.assertFalse(hasattr(SalesOrder, "VehicleCategory"))
        form = SalesOrderForm()
        self.assertNotIn("vehicle_category", form.fields)
        self.assertIn("中古車交易", dict(form.fields["transaction_type"].choices).values())

    def test_create_page_shows_only_transaction_type(self):
        admin = get_user_model().objects.create_superuser("admin", password="test-only")
        self.client.force_login(admin)
        response = self.client.get(reverse("order_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "車輛類別")
        self.assertNotContains(response, 'name="vehicle_category"')
        self.assertContains(response, 'name="transaction_type"')

    def test_used_transaction_is_derived_from_transaction_type(self):
        order = self.make_order()
        self.assertFalse(order.is_used_transaction)
        order.transaction_type = SalesOrder.TransactionType.USED
        order.full_clean()
        order.save()
        self.assertTrue(SalesOrder.objects.get(pk=order.pk).is_used_transaction)

    def test_contract_pdf_prints_transaction_type_in_category_cell(self):
        order = self.make_order()
        for value, label in ((SalesOrder.TransactionType.REGULAR_NEW, "一般新車"),
                             (SalesOrder.TransactionType.TEST_RIDE, "試乘車"),
                             (SalesOrder.TransactionType.USED, "中古車交易")):
            with self.subTest(value=value):
                order.transaction_type = value
                text = "\n".join(pdf_lines(build_order_contract_pdf(order)))
                self.assertIn("交易類型", text)
                self.assertIn(label, text)
                self.assertNotIn("車輛類別", text)

    def test_contract_terms_use_transaction_type(self):
        terms = contract_terms(self.make_order())
        self.assertNotIn("vehicle_category", terms)
        self.assertEqual(terms["transaction_type"], SalesOrder.TransactionType.REGULAR_NEW)

    def test_signed_contract_file_and_fingerprint_untouched_by_transaction_type_change(self):
        order = self.make_order()
        self.client.force_login(self.user)
        self.sign(order)
        order = SalesOrder.objects.get(pk=order.pk)
        fingerprint = order.signed_contract_fingerprint
        with order.signed_contract.open("rb") as handle:
            signed_pdf = handle.read()
        self.assertTrue(fingerprint)

        order.transaction_type = SalesOrder.TransactionType.TEST_RIDE
        order.save()

        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.signed_contract_fingerprint, fingerprint)
        self.assertTrue(order.has_signed_contract)
        with order.signed_contract.open("rb") as handle:
            self.assertEqual(handle.read(), signed_pdf)

    def test_order_pages_show_transaction_type_without_vehicle_category(self):
        order = self.make_order()
        order.transaction_type = SalesOrder.TransactionType.PRIZE
        order.save()
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="test-only"))
        for name in ("order_detail", "order_overview"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=[order.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "交易類型")
                self.assertContains(response, "中獎車")
                self.assertNotContains(response, "車輛類別")


@tag("migration")
class VehicleCategoryRemovalMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0193_plate_insurance_auto")
    migrate_to = ("sales", "0194_remove_salesorder_vehicle_category")

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate([self.migrate_from])
        self.addCleanup(self._restore)

    def _restore(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _apps(self, target):
        return MigrationExecutor(connection).loader.project_state([target]).apps

    def test_forward_aligns_used_and_reverse_backfills_category(self):
        apps = self._apps(self.migrate_from)
        Order = apps.get_model("sales", "SalesOrder")
        apps.get_model("sales", "Store").objects.get_or_create(code="MAIN", defaults={"name": "總店"})
        model = apps.get_model("sales", "VehicleModel").objects.create(
            brand="SUZUKI", name="類別遷移測試", model_number="CAT-TEST", energy_type="gas", displacement_cc=125)
        color = apps.get_model("sales", "VehicleColor").objects.create(vehicle_model_id=model.pk, name="白")

        def order(name, category, transaction_type, **extra):
            return Order.objects.create(number=f"SO-CAT-{name}", owner_name=name, owner_phone="0900", owner_address="地址",
                                        owner_id_number=f"HIST-{name}", vehicle_model_id=model.pk, color_id=color.pk,
                                        vehicle_category=category, transaction_type=transaction_type, **extra)

        order("新車", "new", "regular_new", signed_contract_fingerprint="f" * 64)
        order("試乘", "new", "test_ride")
        order("中古", "used", "used")
        order("不一致", "used", "regular_new")
        order("已刪除中古", "used", "prize")
        Order._base_manager.filter(owner_name="已刪除中古").update(deleted_at=timezone.now())

        MigrationExecutor(connection).migrate([self.migrate_to])
        Order = self._apps(self.migrate_to).get_model("sales", "SalesOrder")
        self.assertNotIn("vehicle_category", {field.name for field in Order._meta.get_fields()})
        got = {o.owner_name: o for o in Order._base_manager.all()}
        self.assertEqual(got["新車"].transaction_type, "regular_new")
        self.assertEqual(got["新車"].signed_contract_fingerprint, "f" * 64)
        self.assertEqual(got["試乘"].transaction_type, "test_ride")
        self.assertEqual(got["中古"].transaction_type, "used")
        self.assertEqual(got["不一致"].transaction_type, "used", "車輛類別＝中古車的一律保留成中古車交易")
        self.assertEqual(got["已刪除中古"].transaction_type, "used", "軟刪除的訂單也要對齊")

        MigrationExecutor(connection).migrate([self.migrate_from])
        Order = self._apps(self.migrate_from).get_model("sales", "SalesOrder")
        got = {o.owner_name: (o.vehicle_category, o.transaction_type) for o in Order._base_manager.all()}
        self.assertEqual(got, {
            "新車": ("new", "regular_new"),
            "試乘": ("new", "test_ride"),
            "中古": ("used", "used"),
            "不一致": ("used", "used"),
            "已刪除中古": ("used", "used"),
        })

