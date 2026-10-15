"""訂單裡選「其他」輸入的配件自動加入配件主檔（使用者 2026-10-15 選 A：加入即啟用）。

- 只收加購（贈送售價固定為 0，加入會變成 0 元主檔）。
- 名稱去掉多餘空白後不分大小寫比對；同名已存在就不新增、也不改主檔售價，避免單筆議價覆蓋主檔。
- 售價與工資取第一次輸入的金額；打錯的品項由人員在「配件與工資」停用即可，不影響既有訂單。
"""
from django.db import IntegrityError, transaction
from django.utils import timezone


def normalized_accessory_name(name):
    return " ".join((name or "").split())


def learn_custom_accessories(order, actor_name):
    """把訂單上尚未在主檔的「其他」加購配件建立成主檔品項；回傳新增的名稱。"""
    from sales.models import AccessoryLine, AccessoryProduct, OrderEvent

    added = []
    lines = order.accessories.filter(
        accessory_product__isnull=True, line_type=AccessoryLine.LineType.PURCHASE,
    ).order_by("pk")
    for line in lines:
        name = normalized_accessory_name(line.name)
        if not name or name.casefold() in {item.casefold() for item in added}:
            continue
        if AccessoryProduct.objects.filter(name__iexact=name).exists():
            continue
        note = f"由訂單 {order.number} 的「其他」配件自動加入（{actor_name}，{timezone.localdate():%Y/%m/%d}）"
        try:
            with transaction.atomic():
                AccessoryProduct.objects.create(
                    name=name, sale_price=line.amount or 0, labor_fee=line.labor_fee or 0, note=note[:250],
                )
        except IntegrityError:
            continue  # 同時有人建立同名品項，以先建立的為準。
        added.append(name)
    if added:
        OrderEvent.objects.create(
            order=order,
            event_type="accessory_master_added",
            description="「其他」配件已自動加入配件主檔：" + "、".join(added),
            actor_name=actor_name,
        )
    return added
