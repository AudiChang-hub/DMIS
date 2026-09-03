from datetime import date
from io import StringIO
from threading import Event, Thread
from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from sales.forms import DealerVolumeBonusRuleForm
from sales.models import (DealerVolumeBonusRule, DealerVolumeBonusDeletion, DealerVolumeBonusSettlement,
    DealerVolumeBonusPeriod, DealerVolumeBonusTier, OrderOperationsProfile, SalesOrder)
from sales.services.bonus_rule_deletion import bonus_rule_delete_preview, delete_bonus_rule
from sales.services.dealer_commission import create_volume_bonus_settlement
from . import test_volume_bonus_conditions as fixtures


class BonusRuleDeletionTests(TestCase):
    rule = fixtures.VolumeBonusConditionsTests.rule
    order = fixtures.VolumeBonusConditionsTests.order
    payload = fixtures.VolumeBonusConditionsTests.payload

    @classmethod
    def setUpTestData(cls):
        fixtures.VolumeBonusConditionsTests.setUpTestData.__func__(cls)

    def token(self, rule):
        return bonus_rule_delete_preview(rule, self.user)['confirmation_token']

    def delete(self, rule, token=None):
        return delete_bonus_rule(rule_id=rule.pk, actor=self.user, confirmation_token=token or self.token(rule))

    def test_delete_unsettled_rule_preserves_orders_and_all_financial_fields(self):
        order = self.order()
        rule = self.rule(brand='SUZUKI', dealer=self.a)
        rule.brands.create(brand='SUZUKI')
        rule.vehicle_models.add(self.model)
        before_order = SalesOrder.objects.filter(pk=order.pk).values().get()
        before_money = OrderOperationsProfile.objects.filter(order=order).values().get()
        original_id = rule.pk
        self.delete(rule)
        self.assertFalse(DealerVolumeBonusRule.objects.filter(pk=original_id).exists())
        self.assertFalse(DealerVolumeBonusTier.objects.filter(rule_id=original_id).exists())
        self.assertFalse(DealerVolumeBonusPeriod.objects.filter(rule_id=original_id).exists())
        self.assertEqual(before_order, SalesOrder.objects.filter(pk=order.pk).values().get())
        self.assertEqual(before_money, OrderOperationsProfile.objects.filter(order=order).values().get())
        audit = DealerVolumeBonusDeletion.objects.get(original_rule_id=original_id)
        self.assertEqual(audit.actor_id, self.user.pk)
        self.assertEqual(audit.actor_name, self.user.username)
        self.assertEqual(audit.snapshot['rule']['dealer'], self.a.pk)
        self.assertEqual(audit.snapshot['vehicle_models'], [self.model.pk])
        self.assertEqual(audit.snapshot['tiers'][0]['bonus_per_vehicle'], '500')
        self.assertEqual(len(audit.snapshot['periods']), 1)

    def test_other_rules_and_settlements_are_untouched(self):
        self.order()
        settled = self.rule(dealer=self.a)
        settlement = create_volume_bonus_settlement(settled, 'test')
        other = self.rule(dealer=self.a)
        before = list(OrderOperationsProfile.objects.values())
        allocations = list(settlement.allocations.values())
        self.delete(other)
        settlement.refresh_from_db()
        self.assertEqual(settlement.actual_amount, 500)
        self.assertEqual(allocations, list(settlement.allocations.values()))
        self.assertEqual(before, list(OrderOperationsProfile.objects.values()))

    def test_any_settled_period_blocks_deletion_even_after_confirmation_opened(self):
        self.order()
        rule = self.rule(dealer=self.a, period_type='month')
        DealerVolumeBonusPeriod.objects.create(rule=rule, starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 31))
        token = self.token(rule)
        create_volume_bonus_settlement(rule, 'test', period=rule.periods.first())
        with self.assertRaisesMessage(ValidationError, '已有結算'):
            self.delete(rule, token)
        self.assertTrue(DealerVolumeBonusRule.objects.filter(pk=rule.pk).exists())
        self.assertFalse(DealerVolumeBonusDeletion.objects.exists())

    def test_changed_scope_period_or_tier_requires_new_confirmation(self):
        for change in ('dealer', 'period', 'tier'):
            rule = self.rule()
            token = self.token(rule)
            if change == 'dealer':
                rule.dealer = self.b
                rule.save()
            elif change == 'period':
                DealerVolumeBonusPeriod.objects.create(rule=rule, starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 31))
            else:
                tier = rule.tiers.get()
                tier.bonus_per_vehicle = 900
                tier.save()
            with self.subTest(change=change), self.assertRaisesMessage(ValidationError, '設定已變更'):
                self.delete(rule, token)
        self.assertFalse(DealerVolumeBonusDeletion.objects.exists())

    def test_tampered_expired_cross_rule_and_cross_user_tokens_are_rejected(self):
        first, second = self.rule(), self.rule()
        with self.assertRaisesMessage(ValidationError, '確認已失效'):
            self.delete(first, 'tampered')
        with self.assertRaisesMessage(ValidationError, '設定已變更'):
            self.delete(second, self.token(first))
        other_user = get_user_model().objects.create_user('other-bonus-user')
        with self.assertRaises(ValidationError):
            delete_bonus_rule(rule_id=first.pk, actor=other_user, confirmation_token=self.token(first))
        with patch('django.core.signing.time.time', return_value=time.time() - 7200):
            expired = self.token(first)
        with self.assertRaisesMessage(ValidationError, '確認已失效'):
            self.delete(first, expired)
        self.assertFalse(DealerVolumeBonusDeletion.objects.exists())

    def test_deletion_and_audit_roll_back_together(self):
        rule = self.rule()
        with patch.object(DealerVolumeBonusRule, 'delete', side_effect=ProtectedError('blocked', [])):
            with self.assertRaises(ValidationError):
                self.delete(rule)
        self.assertTrue(DealerVolumeBonusRule.objects.filter(pk=rule.pk).exists())
        self.assertFalse(DealerVolumeBonusDeletion.objects.exists())

    def test_reverse_migration_cannot_discard_deletion_audit(self):
        from django.apps import apps
        from importlib import import_module
        from types import SimpleNamespace
        guard = import_module('sales.migrations.0117_bonus_rule_deletion_audit').prevent_audit_loss_on_reverse
        guard(apps, SimpleNamespace(connection=connection))
        self.delete(self.rule())
        with self.assertRaisesMessage(RuntimeError, '已有規則刪除紀錄'):
            guard(apps, SimpleNamespace(connection=connection))

    def test_get_is_read_only_post_needs_confirmation_and_csrf(self):
        rule = self.rule(dealer=self.a)
        url = reverse('dealer_volume_bonus_delete', args=[rule.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertContains(response, '>確認刪除</button>')
        self.assertContains(response, 'href="/help/#dealer-volume-bonus"')
        self.assertContains(response, '全部' if rule.dealer_id is None else self.a.name)
        self.assertTrue(DealerVolumeBonusRule.objects.filter(pk=rule.pk).exists())
        self.assertFalse(DealerVolumeBonusDeletion.objects.exists())
        data = {'confirmation_token': response.context['confirmation_token']}
        self.assertEqual(self.client.post(url, data).status_code, 400)
        data['confirm_delete'] = 'yes'
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(url, data).status_code, 403)
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse('dealer_volume_bonus_list') + '?tab=rules')
        self.assertEqual(self.client.post(url, data).status_code, 404)
        self.assertEqual(DealerVolumeBonusDeletion.objects.count(), 1)

    def test_settled_page_explains_limit_and_offers_no_delete_form(self):
        self.order()
        rule = self.rule(dealer=self.a)
        create_volume_bonus_settlement(rule, 'test')
        self.client.force_login(self.user)
        response = self.client.get(reverse('dealer_volume_bonus_delete', args=[rule.pk]))
        self.assertContains(response, '已有結算，不能刪除')
        self.assertNotContains(response, 'data-bonus-delete-form')

    def test_rules_can_use_dynamic_names_without_saving_old_dealer_name(self):
        rule = self.rule(name='', dealer=self.a, brand='SUZUKI')
        self.assertEqual(rule.display_name, 'SUZUKI 台數獎金')
        form = DealerVolumeBonusRuleForm(instance=rule)
        self.assertFalse(form['name'].value())
        form = DealerVolumeBonusRuleForm(self.payload(name='', dealer='', brands=['SUZUKI'], energy_type='gas'), instance=rule)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.name, '')
        self.assertIsNone(saved.dealer_id)
        self.assertEqual(saved.display_name, 'SUZUKI 油車 台數獎金')
        self.assertNotIn(self.a.name, str(saved))

    def test_custom_names_are_not_overwritten(self):
        rule = self.rule(name='年度合作方案', brand='SUZUKI')
        rule.brand = 'SYM'
        rule.save()
        self.assertEqual(rule.display_name, '年度合作方案')

    def test_name_repair_is_explicit_guarded_and_idempotent(self):
        rule = self.rule(name='新隆／SUZUKI／2026/04/01', brand='SUZUKI')
        other = self.rule(name='其他名稱')
        before = DealerVolumeBonusRule.objects.filter(pk=rule.pk).values().get()
        args = dict(rule_id=rule.pk, expected_name=rule.name, stdout=StringIO())
        call_command('reset_bonus_rule_name', **args)
        self.assertEqual(before, DealerVolumeBonusRule.objects.filter(pk=rule.pk).values().get())
        with self.assertRaises(CommandError):
            call_command('reset_bonus_rule_name', rule_id=rule.pk, expected_name='wrong', apply=True)
        call_command('reset_bonus_rule_name', **args, apply=True)
        rule.refresh_from_db()
        self.assertEqual(rule.name, '')
        self.assertEqual(rule.display_name, 'SUZUKI 台數獎金')
        after = DealerVolumeBonusRule.objects.filter(pk=rule.pk).values().get()
        for field in before.keys() - {'name', 'updated_at'}:
            self.assertEqual(before[field], after[field])
        call_command('reset_bonus_rule_name', **args, apply=True)
        other.refresh_from_db()
        self.assertEqual(other.name, '其他名稱')

    def test_settled_name_repair_is_blocked(self):
        self.order()
        rule = self.rule(dealer=self.a)
        create_volume_bonus_settlement(rule, 'test')
        with self.assertRaisesMessage(CommandError, '已有結算'):
            call_command('reset_bonus_rule_name', rule_id=rule.pk, expected_name=rule.name, apply=True)


class BonusDeletionConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_settlement_wins_and_waiting_delete_is_rejected(self):
        self._race(settle_first=True)

    @skipUnlessDBFeature('has_select_for_update')
    def test_deletion_wins_and_waiting_settlement_fails_cleanly(self):
        self._race(settle_first=False)

    def _race(self, *, settle_first):
        fixtures.VolumeBonusConditionsTests.setUpTestData.__func__(type(self))
        fixtures.VolumeBonusConditionsTests.order(self)
        rule = fixtures.VolumeBonusConditionsTests.rule(self, dealer=self.a)
        token = bonus_rule_delete_preview(rule, self.user)['confirmation_token']
        started, finished = Event(), Event()
        errors = []

        def competing_operation():
            close_old_connections()
            try:
                started.set()
                if settle_first:
                    delete_bonus_rule(rule_id=rule.pk, actor=self.user, confirmation_token=token)
                else:
                    create_volume_bonus_settlement(rule, 'test')
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()
                finished.set()

        with transaction.atomic():
            DealerVolumeBonusRule.objects.select_for_update().get(pk=rule.pk)
            if settle_first:
                create_volume_bonus_settlement(rule, 'test')
            else:
                delete_bonus_rule(rule_id=rule.pk, actor=self.user, confirmation_token=token)
            worker = Thread(target=competing_operation, daemon=True)
            worker.start()
            self.assertTrue(started.wait(5))
            self.assertFalse(finished.wait(.2))
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValidationError if settle_first else ValueError)
        self.assertEqual(DealerVolumeBonusSettlement.objects.count(), int(settle_first))
        self.assertEqual(DealerVolumeBonusDeletion.objects.count(), int(not settle_first))
