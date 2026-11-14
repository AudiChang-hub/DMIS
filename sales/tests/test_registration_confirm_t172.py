"""T-172 A′＋T-176（使用者 2026-11-14 定案）。

T-172 A′：領牌只有一個日期欄位；按「確認完成」之前只算預計日，不進報表、不算已領牌；按下才算實際領牌日並鎖定。
- 判斷用既有的 `registration_completed_at`（`registration_confirmed_q()`／`confirmed_registration_date`），不加 migration。
- 每個讀領牌日的地方都有「未確認不算」的測試（見各 Test 類別）。
- 確認卡的牌險規費列「稅金總額＋強制險費用」明細（11/13 簡報 p2：例 715+658=1373）。

T-176：車行獎勵與原廠獎勵確認前依訂單成立日預先觸發，預計日不觸發撤銷；確認時依實際領牌日重判，
不符合的撤銷並寫 OrderEvent；已給付的車行獎勵列「資格撤銷・待追回」，由使用者按已追回或不追回結案。
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    DealerRewardCampaign,
    DealerRewardCampaignItem,
    DealerVolumeBonusRule,
    DealerVolumeBonusTier,
    IncentiveCampaign,
    LegacyImportBatch,
    LegacyImportRow,
    LegacySalesSnapshot,
    OrderOperationsProfile,
    SalesOrder,
    SalesSource,
    Store,
    VehicleBrand,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleSettlementCostRule,
)
from sales.reporting.payout_models import DealerPayoutEntry, DealerPayoutEvent
from sales.services.order_steps import order_step_url
from sales.tests.campaign_helpers import make_campaign

GAS = VehicleModel.EnergyType.GAS


class ReaderFixture(TestCase):
    """讀領牌日的各處共用：一張已確認、一張只填預計日（同一天）。"""

    @classmethod
    def setUpTestData(cls):
        VehicleBrand.objects.get_or_create(name="SUZUKI")
        cls.dealer = SalesSource.objects.create(name="確認測試車行", source_type="dealer")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="確認測試車", energy_type=GAS,
                                                base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def make(self, *, confirmed, day=date(2026, 11, 10), **overrides):
        values = dict(
            source=self.dealer, source_type="dealer", order_date=date(2026, 11, 1), owner_type="company",
            owner_name="測試公司", owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址",
            vehicle_model=self.model, color=self.color, vehicle_price=70000, actual_balance=70000,
            calculated_balance=70000, payment_type="cash", registration_date=day,
            registration_completed_at=timezone.now() if confirmed else None,
            status="delivery_pending" if confirmed else "allocated",
        )
        values.update(overrides)
        return SalesOrder.objects.create(**values)


class ConfirmedHelperTests(ReaderFixture):
    def test_helpers_and_display(self):
        from sales.models import registration_confirmed_q

        confirmed, planned = self.make(confirmed=True), self.make(confirmed=False)
        self.assertEqual(set(SalesOrder.objects.filter(registration_confirmed_q()).values_list("pk", flat=True)),
                         {confirmed.pk})
        self.assertEqual(confirmed.confirmed_registration_date, date(2026, 11, 10))
        self.assertIsNone(planned.confirmed_registration_date)
        self.assertEqual(confirmed.registration_display, "2026/11/10")
        self.assertEqual(planned.registration_display, "預計 2026/11/10", "未確認標「預計」")
        self.assertTrue(planned.is_registration_date_planned)

    def test_reward_basis_date(self):
        planned = self.make(confirmed=False, established_on=date(2026, 10, 20))
        self.assertEqual(planned.reward_basis_date, date(2026, 10, 20), "確認前依訂單成立日，預計日不算")
        self.assertEqual(self.make(confirmed=True).reward_basis_date, date(2026, 11, 10))


class StatisticsReaderTests(ReaderFixture):
    def test_dashboard_snapshot_counts_only_confirmed(self):
        from sales.services.dashboard_metrics import _sales_snapshot

        confirmed = self.make(confirmed=True)
        self.make(confirmed=False)
        snapshot = _sales_snapshot(date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual([order.pk for order in snapshot["orders"]], [confirmed.pk])

    def test_dashboard_source_excludes_planned(self):
        from sales.services.dashboard_metrics import build_dashboard_metrics

        today = timezone.localdate()
        confirmed = self.make(confirmed=True, day=today)
        self.make(confirmed=False, day=today)
        metrics = build_dashboard_metrics()
        counted = {order.pk for row in metrics["trend"] for order in row["orders"]}
        self.assertEqual(counted, {confirmed.pk})

    def test_fee_variance_only_confirmed(self):
        from sales.services.order_filters import fee_variance_orders

        variance = dict(registration_calculated_total=1373, plate_insurance_fee=1000)
        confirmed = self.make(confirmed=True, **variance)
        self.make(confirmed=False, **variance)
        self.assertEqual(list(fee_variance_orders(SalesOrder.objects.all()).values_list("pk", flat=True)), [confirmed.pk])

    def test_order_list_date_filter_by_registration_only_confirmed(self):
        from sales.services.order_filters import filter_order_analysis

        confirmed = self.make(confirmed=True)
        planned = self.make(confirmed=False)
        rows = filter_order_analysis(SalesOrder.objects.all(), {"date_from": "2026-11-01", "date_to": "2026-11-30"})
        self.assertEqual(list(rows.values_list("pk", flat=True)), [confirmed.pk])
        by_order_date = filter_order_analysis(SalesOrder.objects.all(), {"date_basis": "order", "date_from": "2026-11-01"})
        self.assertEqual(set(by_order_date.values_list("pk", flat=True)), {confirmed.pk, planned.pk}, "其他日期基準不受影響")

    def test_cockpit_orders_between_and_stock_velocity(self):
        from sales.services.operations_cockpit import _orders_between, _stock

        today = timezone.localdate()
        confirmed = self.make(confirmed=True, day=today)
        planned = self.make(confirmed=False, day=today)
        self.assertEqual(_orders_between([confirmed, planned], today - timedelta(days=1), today), [confirmed])
        store = Store.objects.create(name="總店", code="HQ")
        VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, engine_number="ENG-T172-S",
                                        ownership_store=store, location_store=store, received_on=today)
        row = next(row for row in _stock(today)["models"] if row["name"] == self.model.name)
        self.assertEqual(row["sold"], 1, "近期銷量只算已確認領牌")

    def test_report_engine_registration_basis(self):
        from sales.reporting.engine import base_query, dimension_query

        confirmed = self.make(confirmed=True)
        planned = self.make(confirmed=False)
        config = {"date_basis": "registration_date", "include_undated": False}
        self.assertEqual(set(base_query(config, {}).values_list("pk", flat=True)), {confirmed.pk})
        undated = {**config, "include_undated": True}
        self.assertEqual(set(base_query(undated, {}).values_list("pk", flat=True)), {confirmed.pk, planned.pk})
        self.assertEqual(set(base_query(undated, {"start": date(2026, 11, 1)}).values_list("pk", flat=True)),
                         {confirmed.pk}, "選了期間就只算已確認")
        months = dict(dimension_query(base_query(undated, {}), "month", "registration_date").values_list("pk", "report_key"))
        self.assertIsNone(months[planned.pk], "預計日不分到月份，歸未領牌")
        self.assertEqual((months[confirmed.pk].year, months[confirmed.pk].month), (2026, 11))

    def test_report_records_mark_planned(self):
        from sales.reporting.records import record_cells

        planned = self.make(confirmed=False)
        confirmed = self.make(confirmed=True)
        self.assertEqual(record_cells(planned, ["registration_date"])[0]["value"], "預計 2026/11/10")
        self.assertEqual(record_cells(confirmed, ["registration_date"])[0]["value"], "2026/11/10")


class FlowReaderTests(ReaderFixture):
    def test_deletion_treats_planned_as_not_registered(self):
        from sales.services.order_deletion import deletion_blockers, is_order_registered

        planned = self.make(confirmed=False, final_plate_number="ABC-1234")
        self.assertFalse(is_order_registered(planned), "事先填的車牌與預計日不算已領牌")
        self.assertNotIn("已有領牌資料，請先確認並更正領牌紀錄；刪除不會撤銷領牌。", deletion_blockers(planned))
        confirmed = self.make(confirmed=True, final_plate_number="ABC-1235")
        self.assertTrue(is_order_registered(confirmed))
        self.assertIn("已有領牌資料，請先確認並更正領牌紀錄；刪除不會撤銷領牌。", deletion_blockers(confirmed))

    def test_imported_order_with_plate_still_counts_as_registered(self):
        from sales.services.order_deletion import is_order_registered

        imported = self.make(confirmed=False, final_plate_number="OLD-0001")
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx", file_size=0)
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=4, raw_data={}, mapped_data={})
        LegacySalesSnapshot.objects.create(order=imported, import_row=row)
        imported.refresh_from_db()
        self.assertTrue(is_order_registered(imported), "匯入單沿用舊判斷：有車牌就算")

    def test_deletion_review_impacts_skip_planned(self):
        from sales.order_deletion_views import _review_impacts

        self.assertNotIn(("warn", "已有領牌資料"), _review_impacts(self.make(confirmed=False, final_plate_number="ABC-1")))
        self.assertIn(("warn", "已有領牌資料"), _review_impacts(self.make(confirmed=True, final_plate_number="ABC-2")))

    def test_inventory_restore_trace_ignores_planned(self):
        from sales.services.inventory_restore import registration_trace

        vehicle = SimpleNamespace(registered_plate_number="", registered_on=None)
        planned = self.make(confirmed=False, final_plate_number="ABC-1234")
        self.assertIsNone(registration_trace(vehicle, planned))
        confirmed = self.make(confirmed=True, final_plate_number="ABC-1235")
        trace = registration_trace(vehicle, confirmed)
        self.assertEqual((trace["plate"], trace["registered_on"]), ("ABC-1235", date(2026, 11, 10)))

    def test_commission_attribution_ignores_planned_date_in_settled_period(self):
        from sales.services.dealer_commission import create_volume_bonus_settlement
        from sales.services.order_commission_attribution import change_order_commission_recipient

        self.make(confirmed=True)  # 讓 11 月有可結算的已確認單
        rule = DealerVolumeBonusRule.objects.create(name="11 月", starts_on=date(2026, 11, 1), ends_on=date(2026, 11, 30))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=1, bonus_per_vehicle=500)
        create_volume_bonus_settlement(rule, "test", dealer=self.dealer)
        other = SalesSource.objects.create(name="另一家", source_type="dealer")
        planned = self.make(confirmed=False, source=other, final_plate_number="")
        self.assertTrue(change_order_commission_recipient(
            order_id=planned.pk, recipient_id=self.dealer.pk, reason="指定車行", expected_revision=planned.revision,
            actor_name="test", editing_session="test",
        ), "預計日落在已結算期間不擋（尚未領牌沒有歸屬期間）")

    def test_print_values_leave_planned_date_blank(self):
        from sales.services.positioned_template_pdf import order_print_values

        self.assertEqual(order_print_values(self.make(confirmed=False))["registration_date"], "")
        self.assertEqual(order_print_values(self.make(confirmed=True))["registration_date"], "2026/11/10")

    def test_overview_labels_planned_date(self):
        from sales.services.order_overview import build_order_overview

        def labels(order):
            overview = build_order_overview(order, include_finance=False)
            return [row["label"] for section in overview["sections"] for row in section["rows"]]

        self.assertIn("預計領牌日期", labels(self.make(confirmed=False)))
        self.assertIn("實際領牌日期", labels(self.make(confirmed=True)))


class PlateFeeTextTests(TestCase):
    def test_breakdown_tax_plus_insurance(self):
        from sales.templatetags.lock_confirm_tags import plate_fee_text

        order = SimpleNamespace(registration_calculated_total=Decimal("1373"), registration_bundle_fee=0,
                                registration_tax_total=Decimal("715"), compulsory_insurance_fee=Decimal("658"))
        self.assertEqual(plate_fee_text(order), "715＋658＝1,373 元（稅金＋強制險）")

    def test_bundle_rule_shows_total_only(self):
        from sales.templatetags.lock_confirm_tags import plate_fee_text

        order = SimpleNamespace(registration_calculated_total=Decimal("2600"), registration_bundle_fee=Decimal("2600"),
                                registration_tax_total=Decimal("2600"), compulsory_insurance_fee=Decimal("0"))
        self.assertEqual(plate_fee_text(order), "2,600 元（試算合計）")


class ConfirmFlowTests(TestCase):
    """經由畫面：先填預計日與車牌、按確認完成才鎖定；獎勵預先觸發與撤銷；給付列表待追回。"""

    def setUp(self):
        from sales.services.print_company import initialize_company

        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        self.store = Store.objects.create(name="總店", code="HQ")
        self.model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=GAS, displacement_cc=125)
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="灰")
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("60000"),
                                                 effective_from=date(2026, 1, 1))
        self.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        self.campaign = DealerRewardCampaign.objects.create(name="11 月送機油", brands=["SUZUKI"],
                                                            effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30))
        DealerRewardCampaignItem.objects.create(campaign=self.campaign, reward_type="physical", name="機油", unit="罐",
                                                quantity=2)
        make_campaign(name="11 月加碼", kind=IncentiveCampaign.Kind.BONUS, brands=["SUZUKI"],
                      items={"sales_bonus": 500}, refresh=False,
                      effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30))
        self.order = SalesOrder(
            owner_name="測試車主", owner_phone="0900000000", owner_address="測試地址", owner_id_number="A100000001",
            vehicle_model=self.model, color=self.color, vehicle_price=Decimal("75000"), deposit_amount=Decimal("5000"),
            actual_balance=Decimal("70000"), id_verified=True, status=SalesOrder.Status.ALLOCATION_PENDING,
            source=self.dealer, source_type=SalesOrder.SourceType.DEALER,
        )
        initialize_company(self.order, self.admin)
        self.order.save()
        SalesOrder.objects.filter(pk=self.order.pk).update(established_on=date(2026, 11, 5))
        self.order.refresh_from_db()
        vehicle = VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, engine_number="ENG-T172",
                                                  ownership_store=self.store, location_store=self.store)
        self.order.allocate(vehicle)
        self.order.refresh_from_db()

    def save(self, registration_date="", plate=""):
        response = self.client.post(reverse("registration_save", args=[self.order.pk]),
                                    {"registration_date": registration_date, "final_plate_number": plate},
                                    HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.order.refresh_from_db()
        return response.json()

    def confirm(self):
        self.client.post(reverse("registration_complete", args=[self.order.pk]))
        self.order.refresh_from_db()

    def profile(self):
        return OrderOperationsProfile.objects.get(order=self.order)

    def test_pre_triggered_by_established_date_and_planned_date_does_not_revoke(self):
        from sales.services.dealer_reward_campaign import apply_order_dealer_rewards
        from sales.services.incentive_rule import apply_order_incentive_rule

        apply_order_dealer_rewards(self.order)
        apply_order_incentive_rule(self.order)
        self.assertEqual(list(self.order.dealer_reward_lines.values_list("name", flat=True)), ["機油"],
                         "訂單成立日 11/05 在期間內，先觸發")
        self.assertEqual(self.profile().sales_bonus, Decimal("500"))
        payload = self.save("2026-12-03", "")  # 預計日在活動期間外
        self.assertTrue(payload["ok"])
        self.assertFalse(self.order.is_registration_complete)
        self.assertEqual(self.order.dealer_reward_lines.count(), 1, "預計日不觸發撤銷")
        self.assertEqual(self.profile().sales_bonus, Decimal("500"))
        self.assertFalse(self.order.events.filter(event_type__in=["dealer_reward_revoked", "incentive_campaign_revoked"]).exists())

    def test_confirm_card_lists_breakdown_and_revocations(self):
        from sales.services.dealer_reward_campaign import apply_order_dealer_rewards

        apply_order_dealer_rewards(self.order)
        payload = self.save("2026-12-03", "abc-1234")
        html = payload["registration_html"]
        self.assertIn('data-lock-confirm="確認領牌完成"', html)
        self.assertIn(">確認完成</button>", html)
        self.assertIn("（稅金＋強制險）", html)
        self.assertIn(f"{self.order.registration_tax_total:,.0f}＋{self.order.compulsory_insurance_fee:,.0f}", html)
        self.assertIn("⚠ 將撤銷 11 月送機油", html)
        self.assertIn("⚠ 將撤銷 11 月加碼", html)
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertIn("領牌日期 <span class=\"ledger-tag ledger-tag--estimate\">預計</span>", page)
        self.assertIn("預計 2026/12/03", page, "頁首標預計")

    def test_confirm_revokes_and_paid_reward_becomes_recoverable(self):
        from sales.reporting import payouts
        from sales.services.dealer_reward_campaign import apply_order_dealer_rewards

        apply_order_dealer_rewards(self.order)
        items = [item for item in payouts.collect_items() if item.order and item.order.pk == self.order.pk]
        self.assertEqual(len(items), 1, "尚未確認領牌的預先觸發獎勵也列在給付列表")
        self.assertTrue(items[0].pre_triggered and items[0].checkable)
        self.assertIn("依訂單日，待領牌確認", items[0].period_label)
        payouts.set_paid([items[0].source_key], True, "tester")

        self.save("2026-12-03", "abc-1234")
        self.assertIn("已給付，將列待追回", self.save("2026-12-03", "abc-1234")["registration_html"])
        self.confirm()
        self.assertTrue(self.order.is_registration_complete)
        self.assertFalse(self.order.dealer_reward_lines.exists(), "實際領牌日 12/03 不在期間，撤銷")
        self.assertEqual(self.profile().sales_bonus, Decimal("0"))
        self.assertTrue(self.order.events.filter(event_type="dealer_reward_revoked").exists())
        self.assertTrue(self.order.events.filter(event_type="incentive_campaign_revoked").exists())

        orphans = payouts.orphan_entries(payouts.collect_items())
        self.assertEqual([entry.revoked for entry in orphans], [True])
        page = self.client.get(reverse("dealer_payout_list")).content.decode()
        self.assertIn("資格撤銷・待追回", page)
        self.assertIn(">已追回</button>", page)
        self.client.post(reverse("dealer_payout_update"),
                         {"action": "resolve", "entry": orphans[0].pk, "outcome": "recovered"})
        entry = DealerPayoutEntry.objects.get(pk=orphans[0].pk)
        self.assertIsNotNone(entry.resolved_at)
        self.assertTrue(entry.paid, "不自動取消已給付")
        event = entry.events.get(action=DealerPayoutEvent.Action.RESOLVE)
        self.assertEqual(event.note_after, "已追回")

    def test_confirm_inside_period_keeps_rewards_and_locks(self):
        from sales.services.dealer_reward_campaign import apply_order_dealer_rewards

        apply_order_dealer_rewards(self.order)
        self.save("2026-11-20", "abc-1234")
        self.confirm()
        self.assertEqual(self.order.dealer_reward_lines.get().registration_date, date(2026, 11, 20))
        profile = self.profile()
        self.assertEqual(profile.sales_bonus, Decimal("500"))
        self.assertIsNotNone(profile.incentive_locked_at)
        self.assertFalse(self.order.events.filter(event_type__in=["dealer_reward_revoked", "incentive_campaign_revoked"]).exists())

    def test_waived_outcome_and_invalid_outcome(self):
        from django.core.exceptions import ValidationError

        from sales.reporting import payouts

        with self.assertRaisesMessage(ValidationError, "請選擇已追回或不追回"):
            payouts.resolve_orphan(1, "tester", "other")


class BackfillPretriggerCommandTests(TestCase):
    """第 5 題（使用者 2026-11-14「補齊，先列出張數給我看」）：預設 dry-run，--apply 才寫入並留紀錄。"""

    def setUp(self):
        VehicleBrand.objects.get_or_create(name="SUZUKI")
        self.dealer = SalesSource.objects.create(name="補齊車行", source_type="dealer")
        self.model = VehicleModel.objects.create(brand="SUZUKI", name="補齊測試車", energy_type=GAS)
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="白")
        campaign = DealerRewardCampaign.objects.create(name="11 月送機油", brands=["SUZUKI"],
                                                       effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30))
        DealerRewardCampaignItem.objects.create(campaign=campaign, reward_type="physical", name="機油", unit="罐", quantity=2)
        make_campaign(name="11 月加碼", kind=IncentiveCampaign.Kind.BONUS, brands=["SUZUKI"], items={"sales_bonus": 500},
                      refresh=False, effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30))

    def make(self, **overrides):
        values = dict(source=self.dealer, source_type="dealer", order_date=date(2026, 11, 3), owner_type="company",
                      owner_name="測試公司", owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址",
                      vehicle_model=self.model, color=self.color, vehicle_price=70000, actual_balance=70000,
                      calculated_balance=70000, payment_type="cash", status="allocated")
        values.update(overrides)
        order = SalesOrder.objects.create(**values)
        SalesOrder.objects.filter(pk=order.pk).update(established_on=overrides.get("established_on", date(2026, 11, 3)))
        # 模擬部署前的舊單：還沒有預先觸發的明細與金額。
        order.dealer_reward_lines.all().delete()
        OrderOperationsProfile.objects.filter(order=order).update(sales_bonus=0)
        OrderOperationsProfile.objects.get(order=order).incentive_applications.all().delete()
        return order

    def run_command(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("backfill_reward_pretrigger", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_lists_counts_and_writes_nothing(self):
        pending = self.make()
        self.make(registration_completed_at=timezone.now(), registration_date=date(2026, 10, 1), status="delivery_pending")
        self.make(status="cancelled")
        self.make(established_on=date(2026, 10, 20))  # 成立日不在期間：不補
        output = self.run_command()
        self.assertIn("會補的單 1 張", output)
        self.assertIn("車行獎勵：新增 1 列", output)
        self.assertIn("補齊車行／11 月送機油：1 張", output)
        self.assertIn("原廠獎勵：新增 1 列", output)
        self.assertIn("實銷獎勵金 +500", output)
        self.assertIn("dry-run", output)
        self.assertFalse(pending.dealer_reward_lines.exists())
        self.assertFalse(pending.events.filter(event_type="reward_pretrigger_backfill").exists())

    def test_apply_writes_rewards_and_trace(self):
        pending = self.make()
        profile = OrderOperationsProfile.objects.get(order=pending)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(insurance_commission=999)
        output = self.run_command("--apply")
        self.assertIn("已寫入 1 張", output)
        self.assertEqual(list(pending.dealer_reward_lines.values_list("name", "registration_date")), [("機油", date(2026, 11, 3))])
        profile.refresh_from_db()
        self.assertEqual(profile.sales_bonus, Decimal("500"))
        self.assertEqual(profile.insurance_commission, Decimal("999"), "只動獎勵，不重算其他收支")
        self.assertTrue(pending.events.filter(event_type="reward_pretrigger_backfill").exists())
        self.assertTrue(pending.changes.filter(reason__startswith="補齊獎勵預先觸發").exists())
        self.assertIn("會補的單 0 張", self.run_command(), "重跑不重複")

    def test_manual_incentive_amount_is_kept(self):
        pending = self.make()
        OrderOperationsProfile.objects.filter(order=pending).update(sales_bonus=123, manual_financial_fields=["sales_bonus"])
        self.run_command("--apply")
        self.assertEqual(OrderOperationsProfile.objects.get(order=pending).sales_bonus, Decimal("123"))
