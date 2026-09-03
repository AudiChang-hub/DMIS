from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import DealerVolumeBonusRuleForm, DealerVolumeBonusTierFormSet
from sales.models import (DealerVolumeBonusRule, DealerVolumeBonusTier, DealerVolumeBonusSettlement,
                          OrderOperationsProfile, SalesOrder, SalesSource, VehicleBrand, VehicleModel, VehicleColor)
from sales.services.dealer_commission import (preview_volume_bonus, create_volume_bonus_settlement,
                                             revise_volume_bonus_settlement, dealer_volume_bonus_total, matching_bonus_rules)
from sales.services.order_commission_attribution import change_order_commission_recipient


class VolumeBonusConditionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('bonus-test', password='Test-Only-123')
        cls.a = SalesSource.objects.create(name='獎金 A 車行', source_type='dealer')
        cls.b = SalesSource.objects.create(name='獎金 B 車行', source_type='dealer')
        cls.platform = SalesSource.objects.create(name='獎金平台', source_type='platform')
        VehicleBrand.objects.get_or_create(name='SUZUKI')
        cls.model = VehicleModel.objects.create(brand='SUZUKI', name='油車測試', energy_type='gas', base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name='白')
        cls.ev = VehicleModel.objects.create(brand='SUZUKI', name='電車測試', energy_type='electric', base_dealer_commission=2000)
        cls.ev_color = VehicleColor.objects.create(vehicle_model=cls.ev, name='白')

    def order(self, dealer=None, **overrides):
        values = dict(source=self.a if dealer is None else dealer, source_type='dealer', order_date=date(2026, 9, 1),
                      owner_type='company', owner_name='測試公司', owner_id_number='83739807', owner_phone='0912345678',
                      owner_address='測試地址', vehicle_model=self.model, color=self.color, vehicle_price=70000,
                      actual_balance=70000, calculated_balance=70000, payment_type='cash',
                      registration_date=date(2026, 9, 3), registration_completed_at=timezone.now(), status='delivery_pending')
        values.update(overrides)
        return SalesOrder.objects.create(**values)

    def rule(self, amount=500, minimum=1, **fields):
        values = dict(name='測試獎金', starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        values.update(fields)
        rule = DealerVolumeBonusRule.objects.create(**values)
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=minimum, bonus_per_vehicle=amount)
        return rule

    def payload(self, **overrides):
        data = dict(name='9 月油車加碼', dealer='', brand='SUZUKI', energy_type='gas', vehicle_models=[str(self.model.pk)],
                    starts_on='2026-09-01', ends_on='2026-09-30', active='on', note='',
                    **{'tiers-TOTAL_FORMS': '1', 'tiers-INITIAL_FORMS': '0', 'tiers-0-minimum_quantity': '1', 'tiers-0-bonus_per_vehicle': '300'})
        data.update(overrides)
        return data

    def test_four_conditions_stack_and_revision_retains_other_bonuses(self):
        order = self.order()
        from sales.services.dealer_commission import apply_order_dealer_commission
        apply_order_dealer_commission(order, lock=True)
        original_profit = OrderOperationsProfile.objects.get(order=order).net_profit
        rules = [self.rule(500, brand='SUZUKI'), self.rule(300, energy_type='gas'), self.rule(200), self.rule(400, dealer=self.a)]
        rules[2].vehicle_models.add(self.model)
        preview = preview_volume_bonus(rules[0], self.a, include_combined=True)
        self.assertEqual(preview['combined_bonus_total'], 1400)
        self.assertEqual(len(preview['orders'][0].bonus_details), 4)
        settlements = [create_volume_bonus_settlement(rule, 'test', dealer=self.a) for rule in rules]
        self.assertEqual(dealer_volume_bonus_total(order), 1400)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.dealer_commission_expense, 3400)
        self.assertEqual(profile.net_profit, original_profit - 1400)
        revise_volume_bonus_settlement(settlements[1], 'test', 100, '修正油車加碼')
        self.assertEqual(dealer_volume_bonus_total(order), 1200)
        profile.refresh_from_db()
        self.assertEqual(profile.dealer_commission_expense, 3200)
        self.assertEqual(profile.net_profit, original_profit - 1200)
        self.assertEqual(settlements[1].adjustments.count(), 1)
        with self.assertRaisesMessage(ValueError, '不可重複'):
            create_volume_bonus_settlement(rules[0], 'test', dealer=self.a)

    def test_global_rule_counts_and_settles_dealers_independently(self):
        self.order(); self.order(); b = self.order(self.b)
        rule = self.rule(minimum=2, brand='SUZUKI')
        self.assertEqual(preview_volume_bonus(rule, self.a)['expected_amount'], 1000)
        self.assertEqual(preview_volume_bonus(rule, self.b)['expected_amount'], 0)
        create_volume_bonus_settlement(rule, 'test', dealer=self.a)
        self.order(self.b)
        second = create_volume_bonus_settlement(rule, 'test', dealer=self.b)
        self.assertEqual(second.actual_amount, 1000)
        self.assertEqual(dealer_volume_bonus_total(b), 500)
        self.assertEqual(rule.settlements.count(), 2)

    def test_conditions_intersect_and_multiple_models_do_not_duplicate_orders(self):
        gas = self.order(); self.order(vehicle_model=self.ev, color=self.ev_color); self.order(self.b)
        rule = self.rule(dealer=self.a, brand='SUZUKI', energy_type='gas')
        rule.vehicle_models.add(self.model, self.ev)
        self.assertEqual([item.pk for item in preview_volume_bonus(rule)['orders']], [gas.pk])
        self.assertEqual(list(matching_bonus_rules(gas, self.a.pk).values_list('pk', flat=True)), [rule.pk])
        self.assertFalse(matching_bonus_rules(gas, self.b.pk).exists())

    def test_four_energy_types_are_distinct(self):
        self.order(); self.order(vehicle_model=self.ev, color=self.ev_color)
        for energy in VehicleModel.EnergyType.values:
            rule = self.rule(energy_type=energy)
            self.assertEqual(preview_volume_bonus(rule, self.a)['quantity'], 1 if energy in ('gas', 'electric') else 0)

    def test_highest_tier_only_and_original_commission_not_repeated(self):
        for _ in range(3): self.order()
        rule = self.rule(100)
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=3, bonus_per_vehicle=500)
        preview = preview_volume_bonus(rule, self.a)
        self.assertEqual(preview['expected_amount'], 1500)
        self.assertEqual(preview['total_payable'], 7500)

    def test_store_attribution_platform_cancelled_and_unregistered(self):
        self.order(source=None, source_type='store')
        assigned = self.order(source=None, source_type='store', commission_recipient=self.a)
        self.order(self.platform, source_type='platform')
        self.order(registration_completed_at=None)
        self.order(status=SalesOrder.Status.CANCELLED)
        self.order(registration_date=date(2026, 8, 31))
        rule = self.rule(energy_type='gas')
        self.assertEqual([order.pk for order in preview_volume_bonus(rule, self.a)['orders']], [assigned.pk])

    def test_settled_global_rule_blocks_matching_but_not_other_energy(self):
        self.order(); target = self.order(self.b); other = self.order(self.b, vehicle_model=self.ev, color=self.ev_color)
        rule = self.rule(energy_type='gas')
        create_volume_bonus_settlement(rule, 'test', dealer=self.a)
        with self.assertRaisesMessage(ValidationError, '已結算'):
            change_order_commission_recipient(order_id=target.pk, recipient_id=self.a.pk, reason='指定車行', expected_revision=target.revision, actor_name='test', editing_session='test')
        self.assertTrue(change_order_commission_recipient(order_id=other.pk, recipient_id=self.a.pk, reason='指定車行', expected_revision=other.revision, actor_name='test', editing_session='test'))
        target.commission_recipient = self.a
        with self.assertRaisesMessage(ValidationError, '已結算'): target.save()

    def test_mismatched_or_missing_dealer_cannot_settle(self):
        self.order()
        with self.assertRaises(ValueError): create_volume_bonus_settlement(self.rule(), 'test')
        with self.assertRaises(ValueError): create_volume_bonus_settlement(self.rule(dealer=self.a), 'test', dealer=self.b)

    def test_manual_total_is_not_overwritten_when_bonuses_stack(self):
        order = self.order()
        profile = OrderOperationsProfile.objects.get(order=order)
        profile.manual_financial_fields = ['dealer_commission_expense']; profile.dealer_commission_expense = 9999
        profile.save()
        for rule in (self.rule(500, brand='SUZUKI'), self.rule(300, energy_type='gas')):
            create_volume_bonus_settlement(rule, 'test', dealer=self.a)
        profile.refresh_from_db()
        self.assertEqual(profile.dealer_commission_expense, 9999)
        self.assertEqual(dealer_volume_bonus_total(order), 800)

    def test_form_styles_search_and_optional_conditions(self):
        form = DealerVolumeBonusRuleForm(self.payload())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.fields['dealer'].widget.attrs['data-searchable-select'], '1')
        self.assertTrue(form.fields['vehicle_models'].widget.allow_multiple_selected)
        rule = form.save()
        self.assertIsNone(rule.dealer_id)
        self.assertEqual(list(rule.vehicle_models.all()), [self.model])

    def test_mismatched_filters_rejected(self):
        form = DealerVolumeBonusRuleForm(self.payload(energy_type='electric'))
        self.assertFalse(form.is_valid()); self.assertIn('vehicle_models', form.errors)

    def test_tier_validation_and_deleted_blank_row(self):
        for override in ({'tiers-0-minimum_quantity': '0'}, {'tiers-0-bonus_per_vehicle': '-1'}, {'tiers-0-bonus_per_vehicle': '1.5'}, {'tiers-0-DELETE': 'on'}):
            forms = DealerVolumeBonusTierFormSet(self.payload(**override), prefix='tiers')
            self.assertFalse(forms.is_valid(), override)
        forms = DealerVolumeBonusTierFormSet(self.payload(**{'tiers-TOTAL_FORMS': '2', 'tiers-1-DELETE': 'on'}), prefix='tiers')
        self.assertTrue(forms.is_valid(), forms.errors)
        duplicate = DealerVolumeBonusTierFormSet(self.payload(**{'tiers-TOTAL_FORMS': '2', 'tiers-1-minimum_quantity': '1', 'tiers-1-bonus_per_vehicle': '600'}), prefix='tiers')
        self.assertFalse(duplicate.is_valid())

    def test_pages_save_multiple_tiers_and_show_new_rule(self):
        self.client.force_login(self.user)
        create = reverse('dealer_volume_bonus_create')
        response = self.client.get(create)
        self.assertContains(response, 'data-add-bonus-tier')
        self.assertContains(response, 'bonus-save-bar')
        self.assertContains(response, 'href="/help/#dealer-volume-bonus"')
        response = self.client.post(create, self.payload(**{'tiers-TOTAL_FORMS': '2', 'tiers-1-minimum_quantity': '3', 'tiers-1-bonus_per_vehicle': '500'}))
        self.assertEqual(response.status_code, 302)
        rule = DealerVolumeBonusRule.objects.get(name='9 月油車加碼')
        self.assertEqual(rule.tiers.count(), 2)
        self.assertIn('show=all', response.url)
        listing = self.client.get(response.url)
        self.assertContains(listing, rule.name)

    def test_settlement_is_post_only_and_conditions_lock_after_settlement(self):
        self.order(); rule = self.rule(brand='SUZUKI', dealer=self.a)
        self.client.force_login(self.user)
        url = reverse('dealer_volume_bonus_settle', args=[rule.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(DealerVolumeBonusSettlement.objects.count(), 0)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url, {}).status_code, 403)
        create_volume_bonus_settlement(rule, 'test')
        self.assertEqual(self.client.get(reverse('dealer_volume_bonus_edit', args=[rule.pk])).status_code, 302)
        rule.energy_type = 'gas'
        with self.assertRaises(ValidationError): rule.save()
        tier = rule.tiers.get(); tier.bonus_per_vehicle = 999
        with self.assertRaises(ValidationError): tier.save()
        with self.assertRaises(ValidationError), transaction.atomic(): rule.vehicle_models.add(self.model)
        with self.assertRaises(ValidationError), transaction.atomic(): tier.delete()

    def test_unauthenticated_cannot_create_rule(self):
        self.assertEqual(self.client.post(reverse('dealer_volume_bonus_create'), self.payload()).status_code, 302)
        self.assertFalse(DealerVolumeBonusRule.objects.exists())

    def test_global_rule_page_settles_only_selected_dealer(self):
        self.order(); self.order(self.b)
        rule = self.rule(brand='SUZUKI')
        self.client.force_login(self.user)
        url = reverse('dealer_volume_bonus_settle', args=[rule.pk])
        self.assertContains(self.client.get(url), '先選擇收款車行')
        self.assertContains(self.client.get(f'{url}?dealer={self.platform.pk}'), '先選擇收款車行')
        response = self.client.post(f'{url}?dealer={self.a.pk}', {'actual_amount': '500', 'adjustment_reason': ''})
        self.assertEqual(response.status_code, 302)
        settlement = DealerVolumeBonusSettlement.objects.get(rule=rule)
        self.assertEqual(settlement.dealer_id, self.a.pk)
        self.assertEqual(settlement.qualified_quantity, 1)
        self.assertEqual(settlement.actual_amount, 500)
        self.assertFalse(rule.settlements.filter(dealer=self.b).exists())

    def test_combined_preview_uses_actual_settled_amount_and_excludes_inactive_estimates(self):
        self.order()
        first = self.rule(500, brand='SUZUKI')
        second = self.rule(300, energy_type='gas')
        self.rule(999, active=False)
        create_volume_bonus_settlement(first, 'test', 600, '核准加碼', dealer=self.a)
        first.active = False
        first.save()
        preview = preview_volume_bonus(second, self.a, include_combined=True)
        self.assertEqual(preview['combined_bonus_total'], 900)
        details = preview['orders'][0].bonus_details
        self.assertEqual([(item['amount'], item['settled']) for item in details], [(600, True), (300, False)])


class VolumeBonusMigrationTests(TransactionTestCase):
    def test_old_settlement_recipient_and_amounts_are_preserved(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes('sales')
        before = [('sales', '0113_user_calendar_view')]
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            Dealer = apps.get_model('sales', 'SalesSource')
            Rule = apps.get_model('sales', 'DealerVolumeBonusRule')
            Settlement = apps.get_model('sales', 'DealerVolumeBonusSettlement')
            dealer = Dealer.objects.create(name='舊結算保留測試', source_type='dealer')
            rule = Rule.objects.create(dealer=dealer, brand='SYM', starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
            settlement = Settlement.objects.create(rule=rule, qualified_quantity=2, bonus_per_vehicle=500,
                                                  expected_amount=1000, actual_amount=1100, adjustment_reason='舊調整原因', settled_by='original')
            MigrationExecutor(connection).migrate(latest)
            upgraded = DealerVolumeBonusSettlement.objects.get(pk=settlement.pk)
            self.assertEqual(upgraded.dealer_id, dealer.pk)
            self.assertEqual(upgraded.rule_id, rule.pk)
            self.assertEqual(upgraded.expected_amount, 1000)
            self.assertEqual(upgraded.actual_amount, 1100)
            self.assertEqual(upgraded.adjustment_reason, '舊調整原因')
            self.assertEqual(upgraded.rule.brand, 'SYM')
            self.assertEqual(upgraded.rule.energy_type, '')
            self.assertFalse(upgraded.rule.vehicle_models.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
