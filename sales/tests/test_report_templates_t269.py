"""T-269 方案 B＋E：常用範本庫（每個範本寫明回答的問題）、分組選單白話名稱、分期公司維度、付款方式條件。全部為合成資料。"""
import copy
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import InstallmentCompany, ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import DIMENSIONS, base_query, card_result, scope_labels, validate_config, validate_scope
from sales.reporting.forms import CardForm, designer_dimension_choices
from sales.reporting.starters import STARTERS, starter_choices, starter_config
from sales.reporting.tree_filter import expand_cards
from sales.reporting.views import publication_key


class TemplateLibraryT269Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        cls.gas = VehicleModel.objects.create(brand="SUZUKI", name="示範油車", model_number="DEMO125", energy_type="gas")
        cls.ev = VehicleModel.objects.create(brand="eReady", name="示範電車", model_number="EVDEMO", energy_type="electric")
        cls.gas_color = VehicleColor.objects.create(vehicle_model=cls.gas, name="白")
        cls.ev_color = VehicleColor.objects.create(vehicle_model=cls.ev, name="黑")
        cls.dealer = SalesSource.objects.create(name="示範車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="示範平台", source_type="platform")
        cls.alpha = InstallmentCompany.objects.create(name="示範融資")
        cls.beta = InstallmentCompany.objects.create(name="測試分期")
        InstallmentCompany.objects.create(name="示範融資租賃")
        InstallmentCompany.objects.create(name="停用分期", active=False)
        # 分期單：主檔 ×2（10 月）、只有文字對到主檔 ×1（11 月，包含）、文字對到停用主檔 ×1、對到兩家 ×1、對不到 ×1、空白 ×1。
        cls.order(cls.gas, cls.gas_color, payment_type="installment", installment_company_master=cls.alpha, installment_company="示範融資")
        cls.order(cls.gas, cls.gas_color, payment_type="installment", installment_company_master=cls.beta, installment_company="測試分期")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="測試分期股份有限公司", month=11)
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="停用分期")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="示範")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="其他公司")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="")
        # 現金單：車行 ×2（油、電）、平台 ×1。
        cls.order(cls.gas, cls.gas_color, source_type="dealer", source=cls.dealer)
        cls.order(cls.ev, cls.ev_color, source_type="dealer", source=cls.dealer)
        cls.order(cls.ev, cls.ev_color, source_type="platform", source=cls.platform)
        # 訂單存檔可能依付款方式整理分期欄位；測試需要的原始狀態直接寫回資料庫。
        for pk, master, text in cls.installments:
            SalesOrder.objects.filter(pk=pk).update(installment_company_master=master, installment_company=text, payment_type="installment")

    installments = []

    @classmethod
    def order(cls, model, color, *, month=10, payment_type="cash", installment_company_master=None, installment_company="", **extra):
        values = dict(source_type="store", order_date=date(2026, month, 2), registration_date=date(2026, month, 3),
                      registration_completed_at=timezone.now(), owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                      vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000, calculated_balance=10000,
                      payment_type="cash", status="completed")
        values.update(extra)
        created = SalesOrder.objects.create(**values)
        if payment_type == "installment":
            cls.installments.append((created.pk, installment_company_master, installment_company))
        return created

    def setUp(self):
        self.client.force_login(self.admin)

    def result(self, card, config=None):
        config = validate_config({**starter_config("blank"), **(config or {}), "cards": [card]})
        return card_result(config, card, {})

    def test_payment_type_scope(self):
        validate_scope({"payment_type": ["installment", "cash", "card"]})
        with self.assertRaises(ValidationError):
            validate_scope({"payment_type": ["bitcoin"]})
        self.assertEqual(scope_labels({"payment_type": ["installment"]}), ["付款方式：分期"])
        config = {**starter_config("blank"), "fixed_filters": {"payment_type": ["installment"]}}
        self.assertEqual(base_query(config, {}).count(), 7)
        self.assertIn("fixed_payment_type", CardForm().fields)
