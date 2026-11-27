"""把來源名稱是「代交車」的本店訂單轉成交易類型「代交車」（T-320，使用者 2026-11-25）。

交易類型加「代交車」之前，代交車的單是用本店來源「代交車」記的；轉換後才會不計業績、在報表中心歸「代交車」。

- 對象：訂單來源＝本店、來源名稱＝「代交車」（--source-name 可改），交易類型還不是代交車。Excel 匯入單不動。
- 預設 dry-run：逐張列出單號、狀態，以及轉換前後的車價收入、車輛成本、淨利、應收（在交易裡實際轉一次再復原，
  數字和 --apply 相同；只列單號，不列個資），不寫入。
- --apply：寫入交易類型並重算收支（每張一筆 OrderChange、一筆 OrderEvent）。整批在同一個交易裡、先鎖住目標單；
  可重跑，已是代交車的單不再處理。
- 不能轉的單會列出原因並略過：不是現金單、已指定台數與傭金歸屬車行、車價不是 0（請先在訂單頁處理）。
- 車價收入、車輛成本、淨利或應收會變動的單，--apply 預設整批不執行，確認後加 --accept-changes 才寫入。
- --order：只處理指定訂單編號（可多個）。
- --revert：退回 2.41.1 前用（2.41.1 不認得交易類型「代交車」，那些單存檔會失敗）。把交易類型是代交車的單
  （含匯入單）全部改回「一般新車」，同一個交易裡把車輛成本設成人工調整的 0（和收支畫面人工改成本同一套：
  vehicle_cost_manual＋manual_financial_fields），2.41.1 重新同步時不會依車型帶入成本；車價收入不動。
  Excel 匯入單的收支本來就照匯入值（2.41.1 也保護），成本不動、只改交易類型。
  留 OrderChange／OrderEvent。dry-run 逐張列還原前後的車輛成本，2.41.1 會依來源發本店人員傭金的單標
  「退版後可能產生人員傭金」（不另外處理）。同樣預設 dry-run、--apply 才寫入、整批同一個交易並先鎖住目標單、
  可重跑；只列單號，不列個資。
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from sales.models import OrderChange, OrderEvent, OrderOperationsProfile, SalesOrder, SalesSource
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_summary import payment_summary

ACTOR = "系統資料整理（T-320，依使用者 2026-11-25）"
REASON = "來源名稱「代交車」的本店訂單改用交易類型「代交車」（不計業績）"
REVERT_REASON = "退回 2.41.1 前，交易類型「代交車」改回「一般新車」（2.41.1 沒有代交車）"
DEFAULT_SOURCE_NAME = "代交車"
ZERO = Decimal("0")
FIGURES = (("actual_disbursement", "車價收入"), ("vehicle_cost", "車輛成本"), ("net_profit", "淨利"), ("receivable", "應收"))


class _Rollback(Exception):
    """dry-run 用：在交易裡轉一次拿到轉換後的數字，再整個復原。"""


def _figures(order_id):
    order = SalesOrder.objects.get(pk=order_id)
    profile = OrderOperationsProfile.objects.filter(order_id=order_id).first()
    summary = payment_summary(order)
    return {
        "actual_disbursement": (profile.actual_disbursement if profile else None) or ZERO,
        "vehicle_cost": (profile.vehicle_cost if profile else None) or ZERO,
        "net_profit": profile.net_profit if profile else ZERO,
        "receivable": summary["customer_due"] + summary["lender_due"],
    }


def _block_reason(order):
    if order.payment_type != SalesOrder.PaymentType.CASH or any(
            row.get("method") != SalesOrder.PaymentSplitMethod.CASH for row in order.payment_splits or ()):
        return "付款方式不是現金"
    if order.commission_recipient_id:
        return "已指定台數與傭金歸屬車行"
    if order.vehicle_price:
        return "車價不是 0"
    return ""


def _convert(order, write_audit):
    """改交易類型並重算收支。已結案的單也要能轉，所以不經整單驗證（比照 mark_closed 只寫必要欄位）。"""
    now = timezone.now()
    before = order.get_transaction_type_display()
    SalesOrder.objects.filter(pk=order.pk).update(
        transaction_type=SalesOrder.TransactionType.PROXY_DELIVERY, updated_at=now)
    sync_order_operations(order.pk)
    if write_audit:
        OrderChange.objects.create(order=order, actor_name=ACTOR, reason=REASON, changes={
            "交易類型": {"before": before, "after": SalesOrder.TransactionType.PROXY_DELIVERY.label}})
        OrderEvent.objects.create(order=order, event_type="transaction_type_converted", actor_name=ACTOR,
                                  description=f"交易類型由「{before}」改為「代交車」（不計業績；車價收入、車輛成本固定 0）")


def _vehicle_cost(order):
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    return (profile.vehicle_cost if profile else None) or ZERO


def _staff_commission_after_rollback(order):
    """2.41.1 的本店人員傭金規則（沒有代交車不發的例外）：本店單、來源是有設傭金的本店人員、沒指定歸屬車行。"""
    source = order.source
    if (order.source_type != SalesOrder.SourceType.STORE or not source or order.commission_recipient_id
            or source.source_type != SalesSource.SourceType.STORE):
        return ZERO
    return source.staff_commission or ZERO


def _revert(order):
    """改回一般新車，車輛成本設成人工調整的 0；車價收入不動（已結案的單也要能改，所以不經整單驗證）。"""
    regular = SalesOrder.TransactionType.REGULAR_NEW
    pin_cost = order.zero_vehicle_finance          # 改之前判斷：系統建立的代交車才把成本釘成人工 0
    SalesOrder.objects.filter(pk=order.pk).update(transaction_type=regular, updated_at=timezone.now())
    changes = {"交易類型": {"before": SalesOrder.TransactionType.PROXY_DELIVERY.label, "after": regular.label}}
    if pin_cost:
        profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
        changes["車輛成本"] = {"before": _money(profile.vehicle_cost or ZERO), "after": "0（人工調整）"}
        profile.vehicle_cost = ZERO
        profile.vehicle_cost_rule = None
        profile.vehicle_cost_manual = True
        profile.manual_financial_fields = sorted({*(profile.manual_financial_fields or []), "vehicle_cost"})
        profile.save(update_fields=["vehicle_cost", "vehicle_cost_rule", "vehicle_cost_manual",
                                    "manual_financial_fields", "updated_at"])
    OrderChange.objects.create(order=order, actor_name=ACTOR, reason=REVERT_REASON, changes=changes)
    detail = "車輛成本設為人工調整的 0（車價收入不動）" if pin_cost else "Excel 匯入單，收支不動"
    OrderEvent.objects.create(order=order, event_type="transaction_type_reverted", actor_name=ACTOR,
                              description=f"退版前把交易類型由「代交車」改回「一般新車」，{detail}")


def _money(value):
    return f"{value:,.0f}"


class Command(BaseCommand):
    help = "來源名稱「代交車」的本店訂單轉成交易類型「代交車」；預設 dry-run，--apply 才寫入。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="實際寫入（預設只列出）")
        parser.add_argument("--accept-changes", action="store_true",
                            help="車價收入、車輛成本、淨利或應收會變動的單也照轉（先看過 dry-run 再加）")
        parser.add_argument("--source-name", default=DEFAULT_SOURCE_NAME, help="本店來源名稱（預設：代交車）")
        parser.add_argument("--order", nargs="*", default=[], help="只處理這些訂單編號")
        parser.add_argument("--revert", action="store_true",
                            help="退回 2.41.1 前用：交易類型「代交車」的單全部改回一般新車（搭配 --apply 才寫入）")

    def handle(self, *args, **options):
        run = self._revert if options["revert"] else self._run
        if not options["apply"]:
            run(options)
            return
        # --apply：挑單、檢查、轉換都在同一個交易裡，目標單先鎖住，免得檢查完到寫入之間被人改掉。
        with transaction.atomic():
            run(options)

    def _revert(self, options):
        targets = SalesOrder.objects.filter(transaction_type=SalesOrder.TransactionType.PROXY_DELIVERY).order_by("pk")
        if options["order"]:
            targets = targets.filter(number__in=options["order"])
        if options["apply"]:
            targets = targets.select_for_update(of=("self",))
        targets = list(targets)
        self.stdout.write(f"交易類型「代交車」的訂單：要改回一般新車 {len(targets)} 張"
                          "（含 Excel 匯入單；車輛成本設為人工調整的 0、匯入單不動，車價收入不動）")
        for order in targets:
            cost = _money(_vehicle_cost(order))
            line = (f"  {order.number}（{order.get_status_display()}）｜代交車→一般新車"
                    + (f"｜車輛成本 {cost}→0（人工調整）" if order.zero_vehicle_finance
                       else f"｜車輛成本 {cost}→{cost}（Excel 匯入單，不動）"))
            commission = _staff_commission_after_rollback(order)
            if commission:
                line += f"｜※退版後可能產生人員傭金 {_money(commission)}"
            self.stdout.write(line)
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。確認後加上 --apply 才會改回。")
            return
        for order in targets:
            _revert(order)
        self.stdout.write(f"已改回 {len(targets)} 張。")

    def _run(self, options):
        matched = SalesOrder.objects.filter(
            source_type=SalesOrder.SourceType.STORE, source__source_type=SalesOrder.SourceType.STORE,
            source__name=options["source_name"],
        ).order_by("pk")
        if options["order"]:
            matched = matched.filter(number__in=options["order"])
        imported = matched.filter(legacy_snapshot__isnull=False).count()
        matched = matched.filter(legacy_snapshot__isnull=True)
        done = matched.filter(transaction_type=SalesOrder.TransactionType.PROXY_DELIVERY).count()
        targets = matched.exclude(transaction_type=SalesOrder.TransactionType.PROXY_DELIVERY)
        if options["apply"]:
            # 只鎖訂單本身：查詢有接來源、匯入快照（可空的外部連接），PostgreSQL 不能鎖可空的那一邊。
            targets = targets.select_for_update(of=("self",))
        plan, blocked, changed, lines = [], [], [], []
        for order in list(targets):
            reason = _block_reason(order)
            if reason:
                blocked.append(order)
                lines.append(f"  {order.number}（{order.get_status_display()}）｜不能轉：{reason}，請先在訂單頁處理")
                continue
            before = _figures(order.pk)
            try:
                with transaction.atomic():
                    _convert(order, write_audit=False)
                    after = _figures(order.pk)
                    raise _Rollback
            except _Rollback:
                pass
            differs = any(before[key] != after[key] for key, _label in FIGURES)
            if differs:
                changed.append(order)
            plan.append(order)
            text = "｜".join(f"{label} {_money(before[key])}→{_money(after[key])}" for key, label in FIGURES)
            lines.append(f"  {order.number}（{order.get_status_display()}）｜{order.get_transaction_type_display()}→代交車"
                         f"｜{text}｜{'※金額有變動' if differs else '金額不變'}")
        # 「要轉」只算真的會轉的單；不能轉的另外列張數。
        header = (f"來源「{options['source_name']}」（本店）：要轉 {len(plan)} 張；已是代交車 {done} 張；"
                  f"Excel 匯入單 {imported} 張（不動）")
        if blocked:
            header += f"；不能轉 {len(blocked)} 張（略過）"
        self.stdout.write(header)
        for line in lines:
            self.stdout.write(line)
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。確認後加上 --apply 才會轉換。")
            return
        if changed and not options["accept_changes"]:
            raise CommandError(
                f"{len(changed)} 張的車價收入、車輛成本、淨利或應收會變動（上面標 ※ 的單），沒有寫入任何一張。"
                "確認後加上 --accept-changes 再執行。")
        for order in plan:
            _convert(order, write_audit=True)
        self.stdout.write(f"已轉換 {len(plan)} 張；略過 {len(blocked)} 張。")
