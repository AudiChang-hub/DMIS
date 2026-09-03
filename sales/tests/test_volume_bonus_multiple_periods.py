from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from sales.forms import DealerVolumeBonusRuleForm
from sales.models import DealerVolumeBonusRule, DealerVolumeBonusPeriod, DealerVolumeBonusSettlement, OrderOperationsProfile
from sales.services.dealer_commission import (preview_volume_bonus, create_volume_bonus_settlement,
    revise_volume_bonus_settlement, dealer_volume_bonus_total, matching_bonus_rules)
from sales.services.order_commission_attribution import change_order_commission_recipient
from .test_volume_bonus_conditions import VolumeBonusConditionsTests


class VolumeBonusMultiplePeriodsTests(TestCase):
    order = VolumeBonusConditionsTests.order
    payload = VolumeBonusConditionsTests.payload
    rule = VolumeBonusConditionsTests.rule

    @classmethod
    def setUpTestData(cls):
        VolumeBonusConditionsTests.setUpTestData.__func__(cls)

    def multi(self, months=('9', '10'), **overrides):
        values = self.payload(period_selection_version='2', period_type='month', period_year='2026', period_months=list(months), **overrides)
        form = DealerVolumeBonusRuleForm(values)
        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save()
        from sales.models import DealerVolumeBonusTier
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=3, bonus_per_vehicle=500)
        return rule

    def edit_payload(self, rule, months):
        return self.payload(period_selection_version='2', period_type='month', period_year='2026', period_months=list(months),
                            **{'tiers-INITIAL_FORMS': '1', 'tiers-0-id': str(rule.tiers.get().pk), 'tiers-0-minimum_quantity': '3', 'tiers-0-bonus_per_vehicle': '500'})

    def test_form_deduplicates_noncontiguous_months_without_filling_gap(self):
        rule = self.multi(('9', '11', '9'))
        self.assertEqual(list(rule.periods.values_list('starts_on', 'ends_on')), [(date(2026, 9, 1), date(2026, 9, 30)), (date(2026, 11, 1), date(2026, 11, 30))])
        gap = self.order(registration_date=date(2026, 10, 1))
        self.assertFalse(matching_bonus_rules(gap, self.a.pk).exists())
        form = DealerVolumeBonusRuleForm(instance=rule)
        self.assertEqual(form.initial['period_months'], ['9', '11'])

    def test_months_do_not_combine_to_reach_threshold(self):
        rule = self.multi()
        self.order(); self.order(); self.order(registration_date=date(2026, 10, 1))
        periods = list(rule.periods.all())
        self.assertEqual([preview_volume_bonus(rule, self.a, period=p)['quantity'] for p in periods], [2, 1])
        self.assertEqual([preview_volume_bonus(rule, self.a, period=p)['expected_amount'] for p in periods], [0, 0])
        for period in periods:
            with self.assertRaisesMessage(ValueError, '尚未達到'):
                create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=period)

    def test_each_month_settles_and_revises_independently(self):
        rule = self.multi()
        september = [self.order() for _ in range(3)]
        october = [self.order(registration_date=date(2026, 10, 1)) for _ in range(3)]
        periods = list(rule.periods.all())
        first = create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=periods[0])
        self.assertEqual(first.actual_amount, 1500)
        self.assertEqual(dealer_volume_bonus_total(october[0]), 0)
        second = create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=periods[1])
        self.assertEqual(second.actual_amount, 1500)
        revise_volume_bonus_settlement(first, 'test', 1200, '只修正九月')
        self.assertEqual([dealer_volume_bonus_total(o) for o in september], [400] * 3)
        self.assertEqual([dealer_volume_bonus_total(o) for o in october], [500] * 3)
        self.assertEqual(DealerVolumeBonusSettlement.objects.get(pk=second.pk).actual_amount, 1500)
        with self.assertRaisesMessage(ValueError, '不可重複'):
            create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=periods[0])

    def test_missing_and_foreign_period_never_guess(self):
        rule = self.multi()
        other = self.rule()
        for call in (preview_volume_bonus, lambda r, d, **kw: create_volume_bonus_settlement(r, 'test', dealer=d, **kw)):
            with self.assertRaisesMessage(ValueError, '請先選擇'):
                call(rule, self.a)
            with self.assertRaisesMessage(ValueError, '不屬於'):
                call(rule, self.a, period=other.periods.get())

    def test_quarters_and_leap_year_have_separate_complete_ranges(self):
        form = DealerVolumeBonusRuleForm(self.payload(period_selection_version='2', period_type='quarter', period_year='2024', period_quarters=['1', '4']))
        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save()
        self.assertEqual(list(rule.periods.values_list('starts_on', 'ends_on')), [(date(2024, 1, 1), date(2024, 3, 31)), (date(2024, 10, 1), date(2024, 12, 31))])
        form = DealerVolumeBonusRuleForm(self.payload(period_selection_version='2', period_type='month', period_year='2024', period_months=['2', '12']))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().periods.first().ends_on, date(2024, 2, 29))

    def test_empty_invalid_period_choices_and_year_rejected(self):
        for values in [dict(period_months=[]), dict(period_months=['13']), dict(period_months=['9'], period_year='0'), dict(period_type='quarter', period_quarters=['5'])]:
            data = self.payload(period_selection_version='2', period_type='month', period_year='2026', period_month='9')
            data.update(values)
            form = DealerVolumeBonusRuleForm(data)
            self.assertFalse(form.is_valid(), values)

    def test_period_overlap_foreign_rule_and_settled_date_changes_rejected(self):
        rule = self.multi()
        first = rule.periods.first()
        with self.assertRaises(ValidationError):
            DealerVolumeBonusPeriod.objects.create(rule=rule, starts_on=first.starts_on, ends_on=first.ends_on)
        for _ in range(3): self.order()
        settlement = create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=first)
        first.starts_on = date(2026, 8, 1); first.ends_on = date(2026, 8, 31)
        with self.assertRaisesMessage(ValidationError, '已結算'):
            first.save()
        with self.assertRaises((ProtectedError, ValidationError)):
            with transaction.atomic(): first.delete()
        settlement.period = self.rule().periods.get()
        with self.assertRaisesMessage(ValidationError, '不屬於'):
            settlement.save()

    def test_settled_rules_allow_only_other_period_changes_and_keep_finances(self):
        rule = self.multi()
        for _ in range(3): self.order()
        first = create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=rule.periods.first())
        before = list(OrderOperationsProfile.objects.values_list('id', 'dealer_commission_expense'))
        data = self.edit_payload(rule, ('9', '11'))
        data.update(name='竄改名稱', brands=[], period_year='2027')
        form = DealerVolumeBonusRuleForm(data, instance=rule)
        self.assertTrue(form.conditions_locked)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        rule.refresh_from_db()
        self.assertEqual(rule.name, '9 月油車加碼')
        self.assertEqual(rule.brand_names, ['SUZUKI'])
        self.assertEqual([p.starts_on.month for p in rule.periods.all()], [9, 11])
        self.assertEqual(rule.periods.first().pk, first.period_id)
        self.assertEqual(before, list(OrderOperationsProfile.objects.values_list('id', 'dealer_commission_expense')))
        form = DealerVolumeBonusRuleForm(self.edit_payload(rule, ('11',)), instance=rule)
        self.assertFalse(form.is_valid())
        self.assertIn('已結算期間不可取消', str(form.errors))

    def test_settled_september_does_not_freeze_october_recipient(self):
        rule = self.multi()
        for _ in range(3): self.order()
        create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=rule.periods.first())
        october = self.order(self.b, registration_date=date(2026, 10, 3))
        self.assertTrue(change_order_commission_recipient(order_id=october.pk, recipient_id=self.a.pk, reason='十月歸屬', expected_revision=october.revision, actor_name='test', editing_session='test'))
        september = self.order(self.b)
        with self.assertRaisesMessage(ValidationError, '已結算'):
            change_order_commission_recipient(order_id=september.pk, recipient_id=self.a.pk, reason='九月歸屬', expected_revision=september.revision, actor_name='test', editing_session='test')

    def test_list_and_settlement_views_keep_explicit_period(self):
        self.client.force_login(self.user)
        rule = self.multi()
        for _ in range(3): self.order(registration_date=date(2026, 10, 1))
        period = rule.periods.last()
        page = self.client.get(reverse('dealer_volume_bonus_list') + '?tab=settlements&show=all')
        self.assertContains(page, '2026 年 9 月')
        self.assertContains(page, '2026 年 10 月')
        self.assertContains(page, f'period={period.pk}')
        url = reverse('dealer_volume_bonus_settle', args=[rule.pk])
        self.assertContains(self.client.get(url), '先選擇統計期間')
        self.assertEqual(self.client.post(url, {'dealer': self.a.pk, 'actual_amount': '1500'}).status_code, 400)
        response = self.client.post(f'{url}?dealer={self.a.pk}&period={period.pk}', {'period': period.pk, 'actual_amount': '1500', 'adjustment_reason': ''})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('dealer_volume_bonus_list')}?tab=settlements&show=all#bonus-rule-{rule.pk}")
        self.assertEqual(rule.settlements.get().period_id, period.pk)
        self.assertEqual(self.client.get(f'{url}?period=999999').status_code, 404)
        self.assertEqual(self.client.post(f'{url}?dealer={self.a.pk}&period={period.pk}', {'period': rule.periods.first().pk, 'actual_amount': '1500'}).status_code, 400)
        foreign = self.rule().periods.get()
        self.assertEqual(self.client.get(f'{url}?period={foreign.pk}').status_code, 404)
        self.assertContains(self.client.get(reverse('dealer_volume_bonus_revise', args=[rule.settlements.get().pk])), '2026 年 10 月')

    def test_edit_after_settlement_keeps_shared_tier_even_tampered_post(self):
        self.client.force_login(self.user)
        rule = self.multi()
        for _ in range(3): self.order()
        create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=rule.periods.first())
        url = reverse('dealer_volume_bonus_edit', args=[rule.pk])
        self.assertContains(self.client.get(url), '共用條件及門檻已鎖定')
        data = self.edit_payload(rule, ('9', '10', '12'))
        data['tiers-0-bonus_per_vehicle'] = '99999'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(rule.periods.count(), 3)
        self.assertEqual(rule.tiers.get().bonus_per_vehicle, 500)

    def test_reverse_migration_refuses_multiple_periods(self):
        self.multi()
        module = import_module('sales.migrations.0116_bonus_multiple_periods')
        with self.assertRaisesMessage(RuntimeError, '不能直接降版'):
            module.verify_reverse_is_safe(apps, SimpleNamespace(connection=connection))

    def test_edit_periods_keeps_existing_period_identity(self):
        rule = self.multi()
        september = rule.periods.first()
        october = rule.periods.last()
        form = DealerVolumeBonusRuleForm(self.edit_payload(rule, ('9', '11')), instance=rule)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(rule.periods.first().pk, september.pk)
        self.assertFalse(DealerVolumeBonusPeriod.objects.filter(pk=october.pk).exists())
        self.assertEqual(rule.periods.last().starts_on, date(2026, 11, 1))

    def test_month_and_quarter_rules_stack_only_matching_periods(self):
        monthly = self.multi(('9', '10'))
        quarter = self.rule(amount=300, minimum=3, period_type='quarter', starts_on=date(2026, 7, 1))
        september = [self.order() for _ in range(3)]
        october = [self.order(registration_date=date(2026, 10, 3)) for _ in range(3)]
        first, second = list(monthly.periods.all())
        preview = preview_volume_bonus(monthly, self.a, period=first, include_combined=True)
        self.assertEqual(preview['combined_bonus_total'], 2400)
        preview = preview_volume_bonus(monthly, self.a, period=second, include_combined=True)
        self.assertEqual(preview['combined_bonus_total'], 1500)
        create_volume_bonus_settlement(quarter, 'test', dealer=self.a)
        create_volume_bonus_settlement(monthly, 'test', dealer=self.a, period=second)
        self.assertEqual([dealer_volume_bonus_total(o) for o in september], [300] * 3)
        self.assertEqual([dealer_volume_bonus_total(o) for o in october], [500] * 3)

    def test_order_save_guard_is_period_specific(self):
        rule = self.multi()
        for _ in range(3): self.order()
        late_sep = self.order(self.b)
        create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=rule.periods.first())
        self.order(registration_date=date(2026, 10, 2))  # 十月尚未結算，可新增。
        late_sep.commission_recipient = self.a
        with self.assertRaises(ValidationError):
            late_sep.save()

    def test_form_detects_settlement_created_after_validation(self):
        rule = self.multi()
        for _ in range(3): self.order()
        form = DealerVolumeBonusRuleForm(self.edit_payload(rule, ('9', '12')), instance=rule)
        self.assertTrue(form.is_valid(), form.errors)
        create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=rule.periods.first())
        with self.assertRaisesMessage(ValidationError, '剛完成結算'):
            form.save()
        self.assertEqual([p.starts_on.month for p in rule.periods.all()], [9, 10])

    def test_settlement_cannot_move_to_another_period_in_same_rule(self):
        rule = self.multi()
        for _ in range(3): self.order()
        settlement = create_volume_bonus_settlement(rule, 'test', dealer=self.a, period=rule.periods.first())
        settlement.period = rule.periods.last()
        with self.assertRaisesMessage(ValidationError, '不可變更'):
            settlement.save()

    def test_legacy_unnamed_settled_rule_can_manage_periods_without_renaming(self):
        rule = self.rule(name='', period_type='month')
        for _ in range(3): self.order()
        settlement = create_volume_bonus_settlement(rule, 'test', dealer=self.a)
        form = DealerVolumeBonusRuleForm(self.edit_payload(rule, ('9', '10')), instance=rule)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        rule.refresh_from_db()
        self.assertEqual(rule.name, '')
        self.assertEqual(rule.periods.count(), 2)
        self.assertEqual(rule.periods.first().pk, settlement.period_id)
