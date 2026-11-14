"""補齊尚未確認領牌的單的獎勵預先觸發（T-176 第 5 題，使用者 2026-11-14「補齊，先列出張數給我看」）。

新規則：確認領牌前，車行獎勵與原廠獎勵依訂單成立日預先觸發。既有的未確認單要等下次存檔才會套用，這支指令一次補齊。

- 範圍：未確認領牌（`registration_completed_at` 空白）、未取消／退款中／例外結案、未刪除、有車型的單；
  原廠獎勵已固定（`incentive_locked_at`）的單不動。
- 預設 dry-run：只列出會補的單數、車行獎勵與原廠獎勵各會新增幾列、依車行與活動分組的件數、會撤銷的件數，
  以及原廠獎勵三項金額合計的變化。不寫入任何資料；不列車主個資。
- --apply：逐張在交易內重新計算後寫入。
  - 車行獎勵：`apply_order_dealer_rewards`（只動 `OrderDealerRewardLine`，撤銷時寫 OrderEvent）。
  - 原廠獎勵：只寫三項獎勵金額（人工改過的欄位不動）、活動明細與判斷日，不重算強制險傭金、實際車價收入等其他收支。
  - 每張有變動的單寫一筆 OrderEvent（`reward_pretrigger_backfill`），原廠獎勵金額有變時另寫 OrderChange（改前、改後），
    回復時可依這兩筆紀錄改回。
"""
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from sales.models import OrderChange, OrderEvent, OrderOperationsProfile, SalesOrder
from sales.services.dealer_reward_campaign import (
    apply_order_dealer_rewards,
    order_reward_dealer,
    resolve_dealer_reward_campaigns,
)
from sales.services.incentive_rule import INCENTIVE_FIELDS, incentive_totals, replace_incentive_applications

ACTOR = "系統資料整理（backfill_reward_pretrigger）"
EVENT_TYPE = "reward_pretrigger_backfill"
EXCLUDED_STATUSES = ("draft", "cancel_refund_pending", "cancelled", "exception_closed")
FIELD_LABELS = {"sales_bonus": "實銷獎勵金", "promotion_subsidy": "促銷補助金", "installment_interest_subsidy": "分期補貼息"}


def candidates():
    return (
        SalesOrder.objects.filter(registration_completed_at__isnull=True, vehicle_model__isnull=False)
        .exclude(status__in=EXCLUDED_STATUSES)
        .select_related("vehicle_model", "source", "commission_recipient", "operations")
        .order_by("pk")
    )


def plan(order):
    """這張單補齊後的變化；沒有任何變化回傳 None。"""
    basis = order.reward_basis_date
    dealer = order_reward_dealer(order)
    model = order.vehicle_model
    result = {"order": order, "dealer": dealer, "basis": basis,
              "reward_added": [], "reward_revoked": [], "reward_rows": 0,
              "incentive_added": [], "incentive_revoked": [], "incentive_rows": 0, "amounts": {}}

    before = dict(order.dealer_reward_lines.values_list("campaign_id", "campaign_name"))
    after = resolve_dealer_reward_campaigns(model, dealer.pk if dealer else None, basis)
    after_ids = {campaign.pk for campaign in after}
    for campaign in after:
        if campaign.pk not in before:
            result["reward_added"].append(campaign.name)
            result["reward_rows"] += campaign.items.count()
    result["reward_revoked"] = [name for campaign_id, name in before.items() if campaign_id not in after_ids]

    profile = getattr(order, "operations", None)
    if profile is None or not profile.incentive_locked_at:
        current = {} if profile is None else dict(profile.incentive_applications.values_list("campaign_id", "campaign_name"))
        rows, totals, _matched, _promo, _regular = incentive_totals(
            model, order.source_type, basis, dealer.pk if dealer else None,
        )
        new_ids = {campaign.pk for campaign, _amounts in rows}
        result["incentive_added"] = [campaign.name for campaign, _amounts in rows if campaign.pk not in current]
        result["incentive_rows"] = len(result["incentive_added"])
        result["incentive_revoked"] = [name for campaign_id, name in current.items() if campaign_id not in new_ids]
        manual = set(profile.manual_financial_fields or []) if profile else set()
        for field in INCENTIVE_FIELDS:
            old = Decimal(getattr(profile, field) or 0) if profile else Decimal("0")
            if field not in manual and old != totals[field]:
                result["amounts"][field] = (old, totals[field])
        result["incentive_rows_detail"] = rows
    changed = any(result[key] for key in ("reward_added", "reward_revoked", "incentive_added", "incentive_revoked", "amounts"))
    return result if changed else None


def apply_plan(order_id):
    """交易內重新鎖單、重算後寫入；回傳實際寫入的計畫（已不需要時回傳 None）。"""
    with transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order_id)
        if order.registration_completed_at or order.status in EXCLUDED_STATUSES:
            return None
        result = plan(order)
        if result is None:
            return None
        if result["reward_added"] or result["reward_revoked"]:
            apply_order_dealer_rewards(order, actor_name=ACTOR)
        profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
        if not profile.incentive_locked_at and "incentive_rows_detail" in result:
            rows = result["incentive_rows_detail"]
            for field, (_old, new) in result["amounts"].items():
                setattr(profile, field, new)
            profile.incentive_registration_date = result["basis"] if rows else None
            profile.incentive_rule = next(
                (campaign.legacy_rule for campaign, _a in rows if campaign.kind == campaign.Kind.REGULAR), None,
            )
            profile.save(update_fields=[*INCENTIVE_FIELDS, "incentive_registration_date", "incentive_rule", "updated_at"])
            replace_incentive_applications(profile, rows, result["basis"])
            if result["amounts"]:
                OrderChange.objects.create(
                    order=order, actor_name=ACTOR, reason="補齊獎勵預先觸發（T-176）",
                    changes={FIELD_LABELS[field]: {"before": str(int(old)), "after": str(int(new))}
                             for field, (old, new) in result["amounts"].items()},
                )
        parts = []
        for label, key in (("車行獎勵新增", "reward_added"), ("車行獎勵撤銷", "reward_revoked"),
                           ("原廠獎勵新增", "incentive_added"), ("原廠獎勵撤銷", "incentive_revoked")):
            if result[key]:
                parts.append(f"{label}：{'、'.join(result[key])}")
        OrderEvent.objects.create(
            order=order, event_type=EVENT_TYPE, actor_name=ACTOR,
            description=f"補齊獎勵預先觸發（依訂單成立日 {result['basis']:%Y/%m/%d}）：" + ("；".join(parts) or "金額更新"),
        )
        return result


class Command(BaseCommand):
    help = "補齊未確認領牌的單的車行／原廠獎勵預先觸發；預設 dry-run，--apply 才寫入並留 OrderEvent。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="實際寫入（預設只列出）")

    def handle(self, *args, **options):
        plans = [result for result in (plan(order) for order in candidates()) if result]
        dealer_groups, incentive_groups = Counter(), Counter()
        reward_rows = incentive_rows = reward_revoked = incentive_revoked = 0
        amount_delta = Counter()
        for result in plans:
            dealer_name = result["dealer"].name if result["dealer"] else "（無收款車行）"
            for name in result["reward_added"]:
                dealer_groups[(dealer_name, name)] += 1
            for name in result["incentive_added"]:
                incentive_groups[name] += 1
            reward_rows += result["reward_rows"]
            incentive_rows += result["incentive_rows"]
            reward_revoked += len(result["reward_revoked"])
            incentive_revoked += len(result["incentive_revoked"])
            for field, (old, new) in result["amounts"].items():
                amount_delta[field] += new - old
        write = self.stdout.write
        write(f"範圍：未確認領牌的有效單 {candidates().count()} 張；會補的單 {len(plans)} 張。")
        write(f"車行獎勵：新增 {reward_rows} 列（{sum(dealer_groups.values())} 件活動），撤銷 {reward_revoked} 件。")
        for (dealer_name, campaign), count in sorted(dealer_groups.items()):
            write(f"  {dealer_name}／{campaign}：{count} 張")
        write(f"原廠獎勵：新增 {incentive_rows} 列，撤銷 {incentive_revoked} 件。")
        for campaign, count in sorted(incentive_groups.items()):
            write(f"  {campaign}：{count} 張")
        write("原廠獎勵金額合計變化：" + ("、".join(
            f"{FIELD_LABELS[field]} {amount_delta[field]:+,.0f}" for field in INCENTIVE_FIELDS if amount_delta[field]
        ) or "無"))
        if not options["apply"]:
            write("dry-run：未寫入任何資料。確認後加 --apply 執行。")
            return
        applied = sum(1 for result in plans if apply_plan(result["order"].pk))
        write(f"已寫入 {applied} 張，每張留一筆 OrderEvent（{EVENT_TYPE}）。")
