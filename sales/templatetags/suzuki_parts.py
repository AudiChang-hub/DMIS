from django import template

register = template.Library()


@register.inclusion_tag("sales/_suzuki_parts_lookup.html", takes_context=True)
def suzuki_parts_lookup(context, vehicle_model, number, icon=False):
    """SUZUKI 車款顯示「查零件」：複製引擎／車身號碼後另開台鈴官方零件圖冊。

    icon=True 只給庫存列表用（T-317，操作欄放不下文字按鈕）：改成圖示鈕，名稱由 aria-label／title 提供；
    沒帶 icon 的呼叫端輸出不變。
    """
    request = context.get("request")
    number = (number or "").strip()
    if not request or not number or vehicle_model is None:
        return {"show": False}
    from sales.access.services import policy_for
    from sales.services.vehicle_brands import suzuki_brand_keys

    keys = getattr(request, "_suzuki_brand_keys", None)
    if keys is None:
        keys = request._suzuki_brand_keys = suzuki_brand_keys()
    show = (vehicle_model.brand or "").strip().casefold() in keys and policy_for(request).route("suzuki_parts_manual")
    return {"show": show, "number": number, "icon": bool(icon)}
