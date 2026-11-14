"""訂單裡選「其他」輸入的配件自動加入配件主檔（使用者 2026-10-15 選 A：加入即啟用）。

- 只收加購（贈送售價固定為 0，加入會變成 0 元主檔）。
- 名稱去掉多餘空白後不分大小寫比對；同名已存在就不新增、也不改主檔售價，避免單筆議價覆蓋主檔。
- 售價與工資取第一次輸入的金額；打錯的品項由人員在「配件與工資」停用或合併即可，不影響既有訂單。
- 那一列選了類別就歸到該類別，沒選就是未分類（使用者 2026-11-09 T-138）。
- 只學「這次新增或改了名稱的列」（使用者 2026-11-14 T-179）：舊單上的自填列是歷史紀錄，
  再存檔不會把已從主檔刪掉的名稱加回來。建立訂單時每一列都是新的。
"""
from django.db import IntegrityError, transaction
from django.utils import timezone


def normalized_accessory_name(name):
    return " ".join((name or "").split())


def custom_accessory_categories(formset):
    """從配件表單取出「其他」配件名稱對應的類別：{正規化名稱（不分大小寫）: 類別}。"""
    categories = {}
    for form in formset.forms:
        data = getattr(form, "cleaned_data", None) or {}
        name = normalized_accessory_name(data.get("custom_name"))
        if name and data.get("accessory_category") and not data.get("DELETE"):
            categories.setdefault(name.casefold(), data["accessory_category"])
    return categories


def learnable_custom_names(formset):
    """存檔前呼叫：這次新增或改了名稱的自填列名稱（正規化、不分大小寫）。舊列原樣保留的不算（T-179）。"""
    names = set()
    for form in formset.forms:
        data = getattr(form, "cleaned_data", None) or {}
        name = normalized_accessory_name(data.get("custom_name"))
        if not name or data.get("DELETE") or data.get("accessory_product"):
            continue
        if not form.instance.pk or "custom_name" in form.changed_data or name != normalized_accessory_name(form.instance.name):
            names.add(name.casefold())
    return names


def learn_custom_accessories(order, actor_name, categories=None, names=None):
    """把訂單上尚未在主檔的「其他」加購配件建立成主檔品項；回傳新增的名稱。
    names 有值時只看這些名稱（訂單頁存檔傳入 learnable_custom_names 的結果）。"""
    from sales.models import AccessoryLine, AccessoryProduct, OrderEvent

    added = []
    lines = order.accessories.filter(
        accessory_product__isnull=True, line_type=AccessoryLine.LineType.PURCHASE,
    ).order_by("pk")
    for line in lines:
        name = normalized_accessory_name(line.name)
        if not name or name.casefold() in {item.casefold() for item in added}:
            continue
        if names is not None and name.casefold() not in names:
            continue
        if AccessoryProduct.objects.filter(name__iexact=name).exists():
            continue
        note = f"由訂單 {order.number} 的「其他」配件自動加入（{actor_name}，{timezone.localdate():%Y/%m/%d}）"
        try:
            with transaction.atomic():
                category = (categories or {}).get(name.casefold())
                product = AccessoryProduct.objects.create(
                    name=name, sale_price=line.amount or 0, labor_fee=line.labor_fee or 0, note=note[:250],
                )
                if category:
                    product.categories.add(category)  # 舊的單一類別外鍵由訊號同步（T-179）
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
