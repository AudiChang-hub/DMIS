from django.test import TestCase
from django.urls import reverse

from sales.forms import DealerVolumeBonusRuleForm
from sales.models import DealerVolumeBonusRule, VehicleBrand, VehicleModel
from sales.services.dealer_commission import create_volume_bonus_settlement
from . import test_volume_bonus_conditions as fixtures


class BonusModelFilterTests(TestCase):
    payload = fixtures.VolumeBonusConditionsTests.payload
    order = fixtures.VolumeBonusConditionsTests.order
    rule = fixtures.VolumeBonusConditionsTests.rule

    @classmethod
    def setUpTestData(cls):
        fixtures.VolumeBonusConditionsTests.setUpTestData.__func__(cls)
        VehicleBrand.objects.get_or_create(name='SYM')
        cls.sym = VehicleModel.objects.create(brand='SYM', name='另一品牌油車', energy_type='gas')
        cls.inactive = VehicleModel.objects.create(brand='SUZUKI', name='歷史已選停用車型', energy_type='gas', active=False)

    def options(self, form):
        field = form['vehicle_models']
        widget = field.field.widget
        return {str(option['value']): option for _, options, _ in widget.optgroups(field.html_name, widget.format_value(field.value())) for option in options}

    def visible(self, form):
        return {key for key, option in self.options(form).items() if not option['attrs'].get('hidden')}

    def test_unrestricted_and_single_brand_energy_initial_options(self):
        self.assertEqual(self.visible(DealerVolumeBonusRuleForm()), {str(x.pk) for x in (self.model, self.ev, self.sym)})
        form = DealerVolumeBonusRuleForm(self.payload())
        self.assertEqual(self.visible(form), {str(self.model.pk)})
        option = self.options(form)[str(self.model.pk)]
        self.assertEqual(option['attrs']['data-bonus-brand'], 'suzuki')
        self.assertEqual(option['attrs']['data-bonus-energy'], 'gas')
        self.assertTrue(option['selected'])

    def test_multiple_brands_union_and_energy_intersection(self):
        form = DealerVolumeBonusRuleForm(self.payload(brands=['SYM', 'SUZUKI'], energy_type='gas'))
        self.assertEqual(self.visible(form), {str(self.model.pk), str(self.sym.pk)})
        form = DealerVolumeBonusRuleForm(self.payload(brands=[], energy_type='electric', vehicle_models=[]))
        self.assertEqual(self.visible(form), {str(self.ev.pk)})
        form = DealerVolumeBonusRuleForm(self.payload(brands=['SYM'], energy_type='electric', vehicle_models=[]))
        self.assertEqual(self.visible(form), set())

    def test_mismatched_post_retains_selection_but_cannot_save(self):
        form = DealerVolumeBonusRuleForm(self.payload(brands=['SYM']))
        self.assertFalse(form.is_valid())
        self.assertIn('vehicle_models', form.errors)
        option = self.options(form)[str(self.model.pk)]
        self.assertTrue(option['selected'])
        self.assertTrue(option['attrs']['hidden'])
        self.client.force_login(self.user)
        response = self.client.post(reverse('dealer_volume_bonus_create'), self.payload(brands=['SYM']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '指定車型不屬於所選品牌')
        self.assertFalse(DealerVolumeBonusRule.objects.exists())

    def test_energy_mismatch_post_blocked_and_empty_result_is_not_all(self):
        form = DealerVolumeBonusRuleForm(self.payload(energy_type='micro_electric'))
        self.assertFalse(form.is_valid())
        self.assertIn('vehicle_models', form.errors)
        self.assertEqual(self.visible(form), set())

    def test_edit_retains_selected_inactive_model_and_conditions(self):
        rule = self.rule(brand='SUZUKI', energy_type='gas')
        rule.vehicle_models.add(self.inactive)
        form = DealerVolumeBonusRuleForm(instance=rule)
        self.assertEqual(self.visible(form), {str(self.model.pk), str(self.inactive.pk)})
        self.assertTrue(self.options(form)[str(self.inactive.pk)]['selected'])
        form = DealerVolumeBonusRuleForm(self.payload(vehicle_models=[str(self.inactive.pk)]), instance=rule)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(list(rule.vehicle_models.all()), [self.inactive])

    def test_brand_keys_use_same_casefold_as_server_validation(self):
        model = VehicleModel.objects.create(brand='suzuki', name='品牌大小寫測試', energy_type='gas')
        form = DealerVolumeBonusRuleForm(self.payload(vehicle_models=[str(model.pk)]))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn(str(model.pk), self.visible(form))
        self.assertIn('data-bonus-brand="suzuki"', str(form['brands']))

    def test_settled_rule_ignores_forged_conditions_and_keeps_model(self):
        self.order()
        rule = self.rule(brand='SUZUKI', energy_type='gas', dealer=self.a)
        rule.vehicle_models.add(self.model)
        settlement = create_volume_bonus_settlement(rule, 'test')
        form = DealerVolumeBonusRuleForm(self.payload(brands=['SYM'], energy_type='electric', vehicle_models=[str(self.sym.pk)]), instance=rule)
        self.assertTrue(form.conditions_locked)
        self.assertEqual(self.visible(form), {str(self.model.pk)})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        rule.refresh_from_db(); settlement.refresh_from_db()
        self.assertEqual(rule.brand, 'SUZUKI')
        self.assertEqual(list(rule.vehicle_models.all()), [self.model])
        self.assertEqual(settlement.actual_amount, 500)

    def test_create_page_has_scoped_filter_and_clear_confirmation(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dealer_volume_bonus_create'))
        for marker in ('dealer-bonus-model-filter.js', 'data-model-conflict-confirm', '還原品牌與能源', '沒有符合條件的車型'):
            self.assertContains(response, marker)
