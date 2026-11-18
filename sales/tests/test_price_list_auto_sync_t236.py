"""T-236：車行異動後，價格表分發「當月」（與已建立的下月）名單自動同步這一家車行；歷史月份與其他車行不動。"""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from sales.models import (
    PriceListDistributionItem,
    PriceListDistributionMonth,
    SalesSource,
    SalesSourceBrandPolicy,
    SalesSourceCooperationProfile,
)
from sales.services.price_list_distribution import ensure_distribution_month

TODAY = date(2026, 9, 15)
SYM = SalesSourceBrandPolicy.CooperationScope.SYM
FIELDS = ("dealer_name", "address", "contact_phone", "requires_sym", "requires_suzuki", "sym_exclusive",
          "assigned_to_id", "assigned_to_name", "visit_order", "completed", "note")


@patch("sales.services.price_list_distribution.timezone.localdate", return_value=TODAY)
class DealerAutoSyncTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.alice = User.objects.create_user(username="t236-alice", first_name="小愛", password="test-password")
        self.bob = User.objects.create_user(username="t236-bob", first_name="小柏", password="test-password")
        with patch("sales.services.price_list_distribution.timezone.localdate", return_value=TODAY):
            self.keep = self.dealer("穩定車行")
            self.other = self.dealer("其他車行")
            self.august, _ = ensure_distribution_month(date(2026, 8, 1))
            self.september, _ = ensure_distribution_month(date(2026, 9, 1))
            self.october, _ = ensure_distribution_month(date(2026, 10, 1))
        self.september.items.filter(dealer=self.keep).update(assigned_to=self.alice, assigned_to_name="小愛", visit_order=3)
        self.september.items.filter(dealer=self.other).update(completed=True, note="已送")
        self.confirm(self.september)
        self.confirm(self.october)

    def dealer(self, name, *, active=True, cooperates=True, scope=SYM, **extra):
        source = SalesSource.objects.create(source_type=SalesSource.SourceType.DEALER, name=name, active=active,
                                            address="新北市汐止區測試路1號", **extra)
        SalesSourceCooperationProfile.objects.create(source=source, cooperation_scope=scope, cooperates=cooperates)
        return source

    def confirm(self, distribution):
        distribution.assignment_confirmed_at = timezone.now()
        distribution.assignment_confirmed_by = "admin"
        distribution.save(update_fields=["assignment_confirmed_at", "assignment_confirmed_by"])

    def confirmed(self, distribution):
        distribution.refresh_from_db()
        return distribution.assignment_confirmed_at is not None

    def others_snapshot(self, exclude):
        return sorted(PriceListDistributionItem.objects.exclude(dealer=exclude).values_list("distribution_id", "dealer_id", *FIELDS))

    def months_of(self, dealer):
        return sorted(PriceListDistributionItem.objects.filter(dealer=dealer).values_list("distribution__month", flat=True))

    def test_new_dealer_joins_current_and_next_month_only_with_previous_assignee(self, _today):
        # 八月已有負責人：新車行九月沿用八月的負責人，十月沿用九月的
        before = self.others_snapshot(exclude=None)
        with self.captureOnCommitCallbacks(execute=True):
            new = self.dealer("新開車行")
        self.assertEqual(self.months_of(new), [date(2026, 9, 1), date(2026, 10, 1)])
        self.assertFalse(self.august.items.filter(dealer=new).exists(), "歷史月份不動")
        self.assertEqual(self.others_snapshot(exclude=new), before, "其他車行完全不受影響")
        self.assertFalse(self.confirmed(self.september), "新增項目要清除本月分工確認")
        self.assertFalse(self.confirmed(self.october))

    def test_new_dealer_reuses_last_month_assignee_and_goes_last_in_their_order(self, _today):
        existing = self.dealer("回鍋車行", active=False)
        self.august.items.create(dealer=existing, dealer_name="回鍋車行", assigned_to=self.alice, assigned_to_name="小愛", visit_order=1)
        with self.captureOnCommitCallbacks(execute=True):
            existing.active = True
            existing.save()
        item = self.september.items.get(dealer=existing)
        self.assertEqual((item.assigned_to, item.assigned_to_name, item.visit_order), (self.alice, "小愛", 4))
        october = self.october.items.get(dealer=existing)
        self.assertEqual((october.assigned_to, october.visit_order), (self.alice, 1), "十月沿用剛同步好的九月負責人")

    def test_deactivate_removes_only_pending_items_without_note(self, _today):
        before = self.others_snapshot(exclude=self.keep)
        with self.captureOnCommitCallbacks(execute=True):
            self.keep.active = False
            self.keep.save()
        self.assertEqual(self.months_of(self.keep), [date(2026, 8, 1)], "當月、下月移除，歷史保留")
        self.assertEqual(self.others_snapshot(exclude=self.keep), before)
        self.assertFalse(self.confirmed(self.september))
        with self.captureOnCommitCallbacks(execute=True):
            self.other.active = False
            self.other.save()
        self.assertTrue(self.september.items.filter(dealer=self.other).exists(), "已完成或有備註的保留")
        self.assertFalse(self.october.items.filter(dealer=self.other).exists())

    def test_source_type_change_removes_dealer(self, _today):
        with self.captureOnCommitCallbacks(execute=True):
            self.keep.source_type = SalesSource.SourceType.STORE
            self.keep.save()
        self.assertEqual(self.months_of(self.keep), [date(2026, 8, 1)])

    def test_cooperation_changes(self, _today):
        profile = SalesSourceCooperationProfile.objects.get(source=self.keep)
        with self.captureOnCommitCallbacks(execute=True):
            profile.relationship_type = SalesSourceCooperationProfile.RelationshipType.EXCLUSIVE
            profile.save()
        self.assertTrue(self.september.items.get(dealer=self.keep).sym_exclusive)
        self.assertTrue(self.confirmed(self.september), "只更新快照不清分工確認")
        with self.captureOnCommitCallbacks(execute=True):
            profile.cooperation_scope = SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC
            profile.save()
        self.assertEqual(self.months_of(self.keep), [date(2026, 8, 1)], "只剩台鈴電車不在名單")
        with self.captureOnCommitCallbacks(execute=True):
            profile.cooperation_scope = SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS
            profile.save()
        item = self.september.items.get(dealer=self.keep)
        self.assertEqual((item.requires_sym, item.requires_suzuki), (False, True))
        with self.captureOnCommitCallbacks(execute=True):
            profile.cooperates = False
            profile.save()
        self.assertFalse(self.september.items.filter(dealer=self.keep).exists())
        with self.captureOnCommitCallbacks(execute=True):
            profile.cooperates = True
            profile.save()
        self.assertTrue(self.september.items.filter(dealer=self.keep).exists())
        with self.captureOnCommitCallbacks(execute=True):
            profile.delete()
        self.assertFalse(self.september.items.filter(dealer=self.keep).exists(), "刪除合作設定也同步")

    def test_name_address_phone_update_snapshot_but_keep_assignment_and_confirmation(self, _today):
        before = self.others_snapshot(exclude=self.keep)
        with self.captureOnCommitCallbacks(execute=True):
            self.keep.name = "穩定車行（新招牌）"
            self.keep.address = "臺北市信義區新路2號"
            self.keep.phone = "0227001234"
            self.keep.save()
        item = self.september.items.get(dealer=self.keep)
        self.assertEqual((item.dealer_name, item.city, item.address, item.contact_phone),
                         ("穩定車行（新招牌）", "臺北市", "臺北市信義區新路2號", "02-27001234"))
        self.assertEqual((item.assigned_to, item.visit_order), (self.alice, 3), "指派與順序不動")
        self.assertEqual(self.october.items.get(dealer=self.keep).dealer_name, "穩定車行（新招牌）")
        self.assertEqual(self.august.items.get(dealer=self.keep).dealer_name, "穩定車行", "歷史月份不動")
        self.assertTrue(self.confirmed(self.september))
        self.assertTrue(self.confirmed(self.october))
        self.assertEqual(self.others_snapshot(exclude=self.keep), before)

    def test_unrelated_save_changes_nothing(self, _today):
        before = self.others_snapshot(exclude=None)
        with self.captureOnCommitCallbacks(execute=True):
            self.keep.holiday_gift = True
            self.keep.save()
        self.assertEqual(self.others_snapshot(exclude=None), before)
        self.assertTrue(self.confirmed(self.september))

    def test_next_month_not_created_is_not_created(self, _today):
        PriceListDistributionMonth.objects.filter(month=date(2026, 10, 1)).delete()
        with self.captureOnCommitCallbacks(execute=True):
            self.dealer("十月前新增")
        self.assertFalse(PriceListDistributionMonth.objects.filter(month=date(2026, 10, 1)).exists())

    def test_rolled_back_change_does_not_sync(self, _today):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.keep.active = False
                    self.keep.save()
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
        self.assertTrue(self.september.items.filter(dealer=self.keep).exists())
