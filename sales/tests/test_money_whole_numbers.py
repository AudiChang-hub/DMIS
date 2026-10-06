from django.db import models
from django.test import SimpleTestCase

from sales.models import DealerRewardCostVersion, DealerVehicleRewardItem, OrderOperationsProfile


class MoneyWholeNumberTests(SimpleTestCase):
    """全站金額不使用小數；比例、功率、折數與列印尺寸等非金額欄位不在此限。"""

    def test_money_fields_have_no_decimal_places(self):
        offenders = [
            f"{model.__name__}.{field.name}"
            for model in (OrderOperationsProfile, DealerVehicleRewardItem, DealerRewardCostVersion)
            for field in model._meta.concrete_fields
            if isinstance(field, models.DecimalField) and field.decimal_places
        ]
        self.assertEqual(offenders, [])

    def test_operations_form_renders_whole_number(self):
        from decimal import Decimal

        from sales.forms import OrderOperationsForm

        form = OrderOperationsForm(instance=OrderOperationsProfile(actual_disbursement=Decimal("87800")))
        self.assertIn('value="87800"', str(form["actual_disbursement"]))
        self.assertNotIn("87800.0", str(form["actual_disbursement"]))
