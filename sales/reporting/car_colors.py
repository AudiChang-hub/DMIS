"""T-274：堆疊圖的細分系列是車色時，依車色名稱上的色彩關鍵字配實際顏色。

只用在「再細分＝車色」的堆疊圖；依車色分組的長條圖、圓餅（例如車型 X 顏色）與其他系列照舊依序配色。
- 名稱裡出現多個關鍵字時取最後一個（中文顏色名稱通常以主色結尾，例如「珍珠白」「消光黑」「盧卡綠」）。
- 同一張圖裡兩個系列對到同一色系（例如白與珍珠白）時依序改用同色系較深／較淺的色階。
- 對不到關鍵字、或同色系色階用完的，從備用色盤取這張圖還沒用過的顏色；備用色盤也用完就依色相環產生新色。
- 很淺的顏色（白）在淺色底上看不到，標記 outline，畫面加邊框。
車色是實體顏色，不隨淺色／深色主題改變，所以直接用色碼，不用主題變數。
"""
import colorsys

# (色系, 關鍵字, 色階)；色階第一個是基本色，其餘用在同一張圖已有同色系時。
FAMILIES = (
    ("white", ("白",), ("#f4f5f7", "#e2e4e8", "#cfd2d8")),
    ("black", ("黑",), ("#2b2d31", "#45484e", "#5d6168")),
    ("red", ("紅",), ("#d6312b", "#a8221d", "#ec6a5e")),
    ("blue", ("藍",), ("#2f6fd6", "#1f4f9e", "#6a9ce8")),
    ("green", ("綠",), ("#2e9d57", "#1f7340", "#6cc58c")),
    ("gold", ("黃", "金"), ("#e0a800", "#b88600", "#f2cc4d")),
    ("gray", ("灰", "銀"), ("#9aa0a8", "#7b818a", "#b9bec5")),
    ("orange", ("橘", "橙"), ("#ef7d22", "#c45f10", "#f6a764")),
    ("purple", ("紫",), ("#8a4fd0", "#6a35a8", "#b08ae6")),
    ("pink", ("粉",), ("#ee7fb4", "#d4528f", "#f6b0d2")),
    ("brown", ("棕", "咖啡", "褐"), ("#8b5a2b", "#6b421d", "#ad7a48")),
)
# 對不到車色時用；刻意避開上面各色系的色相，免得被看成某個車色。
SPARE = ("#138a8a", "#7d8a2b", "#3e4f7a", "#7a2e4f", "#b5a36b", "#5fbfa0", "#5d7f99", "#9e6d8a")


def car_color_family(name):
    """回傳色系；名稱有多個關鍵字時取最後出現的那個，對不到回 None。"""
    name = name or ""
    best, position = None, -1
    for family, keywords, _shades in FAMILIES:
        for keyword in keywords:
            index = name.rfind(keyword)
            if index >= 0 and index + len(keyword) > position:
                best, position = family, index + len(keyword)
    return best


def outline(color):
    """很淺的顏色在白底看不到，需要邊框。"""
    r, g, b = (int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[1] > .85


def _generated(count):
    """備用色盤用完時，依黃金角在色相環上產生不重複的顏色。"""
    hue = (count * 137.508) % 360 / 360
    r, g, b = colorsys.hls_to_rgb(hue, .45, .45)
    return "#{:02x}{:02x}{:02x}".format(*(round(value * 255) for value in (r, g, b)))


def car_series_colors(keys):
    """{系列鍵: 色碼}；keys 依圖上系列順序，同一張圖保證不重複。"""
    shades = {family: list(values) for family, _keywords, values in FAMILIES}
    used, colors, pending = set(), {}, []
    for key in keys:
        family = car_color_family(key)
        choice = next((shade for shade in shades.get(family, ()) if shade not in used), None)
        if choice is None:
            pending.append(key)
            continue
        colors[key] = choice
        used.add(choice)
    generated = 0
    for key in pending:
        choice = next((color for color in SPARE if color not in used), None)
        while choice is None or choice in used:
            choice = _generated(generated)
            generated += 1
        colors[key] = choice
        used.add(choice)
    return colors
