from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import DealerVolumeBonusRuleForm, DealerVolumeBonusTierFormSet
from sales.models import (DealerVolumeBonusRule, DealerVolumeBonusTier, DealerVolumeBonusSettlement, DealerVolumeBonusBrand,
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
        data = dict(name='9 月油車加碼', dealer='', brands=['SUZUKI'], energy_type='gas', vehicle_models=[str(self.model.pk)],
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
        self.assertIn(f'?tab=rules#bonus-rule-{rule.pk}', response.url)
        listing = self.client.get(response.url)
        self.assertContains(listing, rule.name)

    def test_rule_management_is_default_complete_and_does_not_run_preview(self):
        named = self.rule(name='有名稱規則', dealer=self.a, active=False)
        unnamed = self.rule(name='', dealer=self.b)
        self.client.force_login(self.user)
        with patch('sales.views.preview_volume_bonus') as preview:
            response = self.client.get(reverse('dealer_volume_bonus_list'))
        preview.assert_not_called()
        self.assertContains(response, 'data-bonus-view="rules"')
        self.assertContains(response, 'aria-current="page">規則管理')
        self.assertContains(response, named.name)
        self.assertContains(response, f'台數獎金規則 #{unnamed.pk}')
        self.assertContains(response, self.b.name)
        self.assertContains(response, reverse('dealer_volume_bonus_edit', args=[named.pk]))
        unnamed.refresh_from_db()
        self.assertEqual(unnamed.name, '')

    def test_unknown_tab_and_legacy_show_all_stay_in_rule_management(self):
        rule = self.rule(dealer=self.a)
        self.client.force_login(self.user)
        for suffix in ('?tab=unknown', '?show=all'):
            response = self.client.get(reverse('dealer_volume_bonus_list') + suffix)
            self.assertContains(response, 'data-bonus-view="rules"')
            self.assertContains(response, rule.name)

    def test_results_tab_keeps_preview_and_navigation_separate(self):
        self.order()
        rule = self.rule(dealer=self.a)
        self.client.force_login(self.user)
        url = reverse('dealer_volume_bonus_list') + '?tab=settlements'
        response = self.client.get(url)
        self.assertContains(response, 'data-bonus-view="settlements"')
        self.assertContains(response, 'aria-current="page">試算／結算')
        self.assertContains(response, '1 台')
        self.assertNotContains(response, reverse('dealer_volume_bonus_edit', args=[rule.pk]))
        self.assertContains(response, f'?tab=rules#bonus-rule-{rule.pk}')

    def test_listing_tabs_are_read_only(self):
        self.rule(dealer=self.a)
        self.client.force_login(self.user)
        before = (DealerVolumeBonusRule.objects.count(), DealerVolumeBonusSettlement.objects.count(), OrderOperationsProfile.objects.count())
        self.client.get(reverse('dealer_volume_bonus_list'))
        self.client.get(reverse('dealer_volume_bonus_list') + '?tab=settlements&show=all')
        self.assertEqual(before, (DealerVolumeBonusRule.objects.count(), DealerVolumeBonusSettlement.objects.count(), OrderOperationsProfile.objects.count()))

    def test_settled_rule_stays_locked_and_listings_preserve_financial_snapshot(self):
        order = self.order()
        rule = self.rule(dealer=self.a)
        settlement = create_volume_bonus_settlement(rule, 'test')
        before = OrderOperationsProfile.objects.filter(order=order).values().get()
        allocations = list(settlement.allocations.values())
        self.client.force_login(self.user)
        response = self.client.get(reverse('dealer_volume_bonus_list'))
        self.assertContains(response, '檢視規則／管理期間')
        self.assertContains(response, '共用條件與門檻已鎖定')
        self.client.get(reverse('dealer_volume_bonus_list') + '?tab=settlements&show=all')
        self.assertEqual(before, OrderOperationsProfile.objects.filter(order=order).values().get())
        self.assertEqual(allocations, list(settlement.allocations.values()))
        settlement.refresh_from_db()
        self.assertEqual(settlement.actual_amount, 500)

    def test_settlement_back_duplicate_and_revision_return_to_results(self):
        self.order()
        rule = self.rule(dealer=self.a)
        self.client.force_login(self.user)
        settle_url = reverse('dealer_volume_bonus_settle', args=[rule.pk])
        result_url = f"{reverse('dealer_volume_bonus_list')}?tab=settlements&show=all#bonus-rule-{rule.pk}"
        response = self.client.get(settle_url)
        self.assertEqual(response.context['return_url'], result_url)
        self.assertContains(response, '返回試算／結算')
        settlement = create_volume_bonus_settlement(rule, 'test')
        self.assertRedirects(self.client.get(settle_url), result_url, fetch_redirect_response=False)
        revise_url = reverse('dealer_volume_bonus_revise', args=[settlement.pk])
        self.assertEqual(self.client.get(revise_url).context['return_url'], result_url)
        response = self.client.post(revise_url, {'actual_amount': '600', 'reason': '測試核准加碼'})
        self.assertRedirects(response, result_url, fetch_redirect_response=False)
        settlement.refresh_from_db()
        self.assertEqual(settlement.actual_amount, 600)
        self.assertEqual(sum(item.amount for item in settlement.allocations.all()), 600)

    def test_edit_saved_rule_returns_to_management(self):
        self.client.force_login(self.user)
        rule = self.rule(name='舊名稱')
        data = self.payload(name='修正名稱', **{'tiers-INITIAL_FORMS': '1', 'tiers-0-id': str(rule.tiers.get().pk)})
        response = self.client.post(reverse('dealer_volume_bonus_edit', args=[rule.pk]), data)
        self.assertRedirects(response, f"{reverse('dealer_volume_bonus_list')}?tab=rules#bonus-rule-{rule.pk}", fetch_redirect_response=False)
        rule.refresh_from_db()
        self.assertEqual(rule.name, '修正名稱')

    def test_settlement_is_post_only_and_conditions_lock_after_settlement(self):
        self.order(); rule = self.rule(brand='SUZUKI', dealer=self.a)
        self.client.force_login(self.user)
        url = reverse('dealer_volume_bonus_settle', args=[rule.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(DealerVolumeBonusSettlement.objects.count(), 0)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url, {}).status_code, 403)
        create_volume_bonus_settlement(rule, 'test')
        locked_page = self.client.get(reverse('dealer_volume_bonus_edit', args=[rule.pk]))
        self.assertContains(locked_page, '共用條件及門檻已鎖定')
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
        self.assertEqual(response.url, f"{reverse('dealer_volume_bonus_list')}?tab=settlements&show=all#bonus-rule-{rule.pk}")
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
            self.assertEqual(upgraded.rule.brand_names, ['SYM'])
            self.assertEqual(upgraded.rule.period_type, 'custom')
            self.assertEqual(upgraded.period.rule_id, rule.pk)
            self.assertEqual((upgraded.period.starts_on, upgraded.period.ends_on), (date(2026, 8, 1), date(2026, 8, 31)))
            self.assertEqual(upgraded.rule.energy_type, '')
            self.assertFalse(upgraded.rule.vehicle_models.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)


class VolumeBonusPeriodsAndBrandsTests(TestCase):
    order = VolumeBonusConditionsTests.order
    rule = VolumeBonusConditionsTests.rule
    payload = VolumeBonusConditionsTests.payload

    @classmethod
    def setUpTestData(cls):
        VolumeBonusConditionsTests.setUpTestData.__func__(cls)
        cls.sym = VehicleModel.objects.create(brand='SYM', name='三陽測試', energy_type='gas', base_dealer_commission=1500)
        cls.sym_color = VehicleColor.objects.create(vehicle_model=cls.sym, name='白')

    def multiple_rule(self, **kwargs):
        rule = self.rule(**kwargs)
        rule.brands.create(brand='SYM')
        rule.brands.create(brand='SUZUKI')
        return rule

    def test_calendar_boundaries_and_leap_years(self):
        from sales.services.bonus_periods import bonus_period_dates
        for year, days in [(2024, 29), (2026, 28), (2100, 28), (2000, 29)]:
            self.assertEqual(bonus_period_dates('month', year, 2), (date(year, 2, 1), date(year, 2, days)))
        for quarter, start, end in [(1, 1, date(2026, 3, 31)), (2, 4, date(2026, 6, 30)), (3, 7, date(2026, 9, 30)), (4, 10, date(2026, 12, 31))]:
            self.assertEqual(bonus_period_dates('quarter', 2026, quarter), (date(2026, start, 1), end))
        self.assertEqual(bonus_period_dates('month', 9999, 12)[1], date(9999, 12, 31))
        for args in [('month', 2026, 13), ('quarter', 2026, 0), ('month', 1899, 1), ('custom', 2026, 1)]:
            with self.assertRaises(ValueError): bonus_period_dates(*args)

    def test_server_derives_preset_dates_instead_of_trusting_posted_dates(self):
        for kind, period, start, end in [('month', '2', date(2024, 2, 1), date(2024, 2, 29)), ('quarter', '3', date(2024, 7, 1), date(2024, 9, 30))]:
            form = DealerVolumeBonusRuleForm(self.payload(period_type=kind, period_year='2024', **{f'period_{kind}': period}))
            self.assertTrue(form.is_valid(), form.errors)
            rule = form.save()
            self.assertEqual((rule.starts_on, rule.ends_on), (start, end))
            self.assertEqual(rule.period_type, kind)

    def test_invalid_presets_and_custom_dates_are_rejected(self):
        for values in [dict(period_type='month'), dict(period_type='quarter', period_year='2026', period_quarter='5'), dict(period_type='month', period_year='0', period_month='1'), dict(period_type='custom', starts_on=''), dict(period_type='custom', ends_on='2026-08-31')]:
            form = DealerVolumeBonusRuleForm(self.payload(**values))
            self.assertFalse(form.is_valid(), values)
        form = DealerVolumeBonusRuleForm(self.payload(period_type='custom', starts_on='2026-08-15', ends_on='2026-10-14'))
        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save()
        self.assertEqual((rule.starts_on, rule.ends_on), (date(2026, 8, 15), date(2026, 10, 14)))

    def test_model_rejects_partial_month_or_quarter(self):
        with self.assertRaisesMessage(ValidationError, '完整月份'):
            self.rule(period_type='month', starts_on=date(2026, 9, 2))
        with self.assertRaisesMessage(ValidationError, '完整月份'):
            self.rule(period_type='quarter')

    def test_multiple_brands_combine_threshold_without_other_dealer(self):
        suzuki = self.order()
        sym1 = self.order(vehicle_model=self.sym, color=self.sym_color)
        sym2 = self.order(vehicle_model=self.sym, color=self.sym_color)
        self.order(self.b)
        rule = self.multiple_rule(minimum=3, energy_type='gas')
        preview = preview_volume_bonus(rule, self.a)
        self.assertEqual(preview['quantity'], 3)
        self.assertEqual(preview['expected_amount'], 1500)
        self.assertEqual({order.pk for order in preview['orders']}, {suzuki.pk, sym1.pk, sym2.pk})
        self.assertEqual(preview_volume_bonus(rule, self.b)['expected_amount'], 0)
        for order in (suzuki, sym1):
            self.assertEqual(list(matching_bonus_rules(order, self.a.pk).values_list('pk', flat=True)), [rule.pk])
        settled = create_volume_bonus_settlement(rule, 'test', dealer=self.a)
        self.assertEqual(settled.allocations.count(), 3)
        self.assertEqual(settled.actual_amount, 1500)

    def test_brand_energy_and_model_intersection(self):
        wanted = self.order(vehicle_model=self.sym, color=self.sym_color)
        self.order(); self.order(vehicle_model=self.ev, color=self.ev_color)
        rule = self.multiple_rule(energy_type='gas')
        rule.vehicle_models.add(self.sym)
        self.assertEqual([o.pk for o in preview_volume_bonus(rule, self.a)['orders']], [wanted.pk])
        rule.vehicle_models.clear()
        self.assertEqual(preview_volume_bonus(rule, self.a)['quantity'], 2)

    def test_monthly_and_quarterly_bonuses_stack_in_their_own_periods(self):
        orders = [self.order(order_date=date(2026, month, 1), registration_date=date(2026, month, day))
                  for month, day in [(6, 30), (7, 1), (7, 31), (8, 31), (9, 1), (9, 30), (10, 1)]]
        quarter = self.multiple_rule(minimum=5, period_type='quarter', starts_on=date(2026, 7, 1))
        month = self.multiple_rule(amount=300, minimum=2, period_type='month')
        self.assertEqual(preview_volume_bonus(quarter, self.a)['quantity'], 5)
        self.assertEqual(preview_volume_bonus(month, self.a)['quantity'], 2)
        create_volume_bonus_settlement(month, 'test', dealer=self.a)
        create_volume_bonus_settlement(quarter, 'test', dealer=self.a)
        self.assertEqual([dealer_volume_bonus_total(o) for o in orders], [0, 500, 500, 500, 800, 800, 0])

    def test_post_saves_multiple_brands_and_quarter_summary(self):
        self.client.force_login(self.user)
        data = self.payload(brands=['SYM', 'SUZUKI', 'SYM'], vehicle_models=[], period_type='quarter', period_year='2026', period_quarter='3', starts_on='', ends_on='')
        response = self.client.post(reverse('dealer_volume_bonus_create'), data)
        self.assertEqual(response.status_code, 302)
        rule = DealerVolumeBonusRule.objects.get(name=data['name'])
        self.assertEqual(rule.brand_names, ['SYM', 'SUZUKI'])
        self.assertEqual(rule.brand, '')
        self.assertEqual(rule.period_label, '2026 年第 3 季')
        self.assertContains(self.client.get(response.url), '2026 年第 3 季')
        self.assertContains(self.client.get(response.url), 'SYM＋SUZUKI')
        data.update(brands=[], period_type='custom', starts_on='2026-09-01', ends_on='2026-09-10', **{'tiers-INITIAL_FORMS': '1', 'tiers-0-id': str(rule.tiers.get().pk)})
        self.assertEqual(self.client.post(reverse('dealer_volume_bonus_edit', args=[rule.pk]), data).status_code, 302)
        rule.refresh_from_db()
        self.assertEqual(rule.brand_names, [])
        self.assertEqual(rule.period_type, 'custom')

    def test_selected_models_must_belong_to_one_of_selected_brands(self):
        form = DealerVolumeBonusRuleForm(self.payload(brands=['SYM', 'SUZUKI'], vehicle_models=[str(self.model.pk), str(self.sym.pk)]))
        self.assertTrue(form.is_valid(), form.errors)
        form = DealerVolumeBonusRuleForm(self.payload(brands=['SYM']))
        self.assertFalse(form.is_valid())
        self.assertIn('vehicle_models', form.errors)
        form = DealerVolumeBonusRuleForm(self.payload(brands=['unknown-brand']))
        self.assertFalse(form.is_valid())

    def test_settled_brand_collection_period_and_destination_are_locked(self):
        self.order()
        rule = self.multiple_rule(dealer=self.a)
        create_volume_bonus_settlement(rule, 'test')
        with self.assertRaises(ValidationError): rule.brands.create(brand='PGO')
        item = rule.brands.first(); item.brand = 'PGO'
        with self.assertRaises(ValidationError): item.save()
        with self.assertRaises(ValidationError), transaction.atomic(): rule.brands.all().delete()
        rule.period_type = 'month'
        with self.assertRaises(ValidationError): rule.save()
        target_order = self.order(self.b, vehicle_model=self.sym, color=self.sym_color)
        target_order.commission_recipient = self.a
        with self.assertRaisesMessage(ValidationError, '已結算'): target_order.save()

    def test_brand_master_usage_and_safe_rename_keep_matching(self):
        from sales.services.vehicle_brands import vehicle_brand_is_used, rename_vehicle_brand_references
        rule = self.multiple_rule()
        self.assertTrue(vehicle_brand_is_used('SYM'))
        rename_vehicle_brand_references('SYM', '更名三陽')
        self.assertEqual(rule.brand_names, ['更名三陽', 'SUZUKI'])

    def test_reverse_migration_refuses_to_drop_multi_brand_scope(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        self.multiple_rule()
        reverse_data = import_module('sales.migrations.0115_bonus_periods_and_brands').verify_reverse_is_safe
        with self.assertRaisesMessage(RuntimeError, '不能直接降版'):
            reverse_data(apps, SimpleNamespace(connection=connection))
