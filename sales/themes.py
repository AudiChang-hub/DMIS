THEME_DEFINITIONS = (
    {
        "value": "professional",
        "label": "專業藍綠",
        "description": "沉穩、清晰，適合日常長時間使用。",
        "meta_color": "#18323b",
    },
    {
        "value": "night-blue",
        "label": "夜間深藍",
        "description": "降低夜間亮度，保留清楚的文字、表格與操作層級。",
        "meta_color": "#0a151b",
    },
    {
        "value": "system",
        "label": "跟隨裝置",
        "description": "依手機或電腦的亮色／深色設定即時切換。",
        "meta_color": "#18323b",
    },
    {
        "value": "deep-blue",
        "label": "沉穩深藍",
        "description": "企業管理系統風格，資訊層級明確。",
        "meta_color": "#162c4a",
    },
    {
        "value": "graphite-gold",
        "label": "石墨灰金",
        "description": "低彩度、成熟，重要操作以暖金提示。",
        "meta_color": "#2b2e33",
    },
    {
        "value": "bright-indigo",
        "label": "明亮靛藍",
        "description": "色彩辨識較強，適合明亮環境。",
        "meta_color": "#252a57",
    },
    {
        "value": "high-contrast",
        "label": "高對比",
        "description": "加深文字與邊界，提升戶外及小螢幕可讀性。",
        "meta_color": "#0b1f2a",
    },
)

DEFAULT_THEME = THEME_DEFINITIONS[0]["value"]
THEME_CHOICES = tuple(
    (theme["value"], theme["label"]) for theme in THEME_DEFINITIONS
)
THEME_VALUES = frozenset(value for value, _label in THEME_CHOICES)
THEME_META_COLORS = {
    theme["value"]: theme["meta_color"] for theme in THEME_DEFINITIONS
}
