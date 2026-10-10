"""訂車時選擇的補助方案 → 訂單補助項目（使用者 2026-10-10 選方案 1）。

- 新選的方案：建立補助項目，名稱、單位、預設金額取自主檔（沒有預設金額為 0，之後在汰舊補助分頁修改）。
- 取消勾選的方案：只刪除還沒送出申請、也沒填申請日期的項目；已申請的保留，避免誤刪進度。
- 選了汰舊類方案：開啟汰舊補助流程（is_trade_in_subsidy），補助類型空白時帶入方案名稱。
- 「其他」自填名稱：建立類別「其他」、未連方案的補助項目；同名已存在就不重複建立，也不會因清空而刪除。
"""
import re
from decimal import Decimal

from django.db import transaction

from sales.models import OrderOperationsProfile, SubsidyItem


def other_subsidy_names(text):
    names = []
    for name in re.split(r"[、,，;；/\n]+", text or ""):
        name = name.strip()[:160]
        if name and name not in names:
            names.append(name)
    return names


@transaction.atomic
def apply_subsidy_programs(order, programs, other_names=()):
    programs = list(programs or [])
    other_names = list(other_names or [])
    selected = {program.pk: program for program in programs}
    existing = {
        item.program_id: item
        for item in order.subsidy_items.filter(program__isnull=False).select_related("program")
    }
    for program_id, program in selected.items():
        if program_id not in existing:
            SubsidyItem.objects.create(
                order=order, program=program, category=program.category, item_name=program.name,
                expected_amount=program.default_amount or Decimal("0"),
            )
    existing_other = set(order.subsidy_items.filter(program__isnull=True).values_list("item_name", flat=True))
    for name in other_names:
        if name not in existing_other:
            SubsidyItem.objects.create(order=order, category=SubsidyItem.Category.OTHER, item_name=name)
    for program_id, item in existing.items():
        if program_id not in selected and item.status == SubsidyItem.Status.NOT_SUBMITTED and not item.applied_on:
            item.delete()
    update_fields = []
    if any(program.requires_old_vehicle for program in programs) and not order.is_trade_in_subsidy:
        order.is_trade_in_subsidy = True
        update_fields.append("is_trade_in_subsidy")
    if (programs or other_names) and not order.subsidy_type:
        order.subsidy_type = "、".join([program.name for program in programs] + other_names)[:120]
        update_fields.append("subsidy_type")
    if update_fields:
        type(order).objects.filter(pk=order.pk).update(**{name: getattr(order, name) for name in update_fields})
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if profile:
        profile.subsidy_amount = order.subsidy_total
        profile.save(update_fields=["subsidy_amount", "updated_at"])
    return order
