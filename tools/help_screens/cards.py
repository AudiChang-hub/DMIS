"""合成證件照片：明顯標示「合成樣本」，只有裁切需要的版面特徵（正面右側照片區、反面左下條碼）。"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (r"C:/Windows/Fonts/msjh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


def _font(size, bold=False):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size, index=1 if bold and path.endswith("msjh.ttc") else 0)
    return ImageFont.load_default()


def _card(lines, title, side):
    width, height = 856, 540
    card = Image.new("RGB", (width, height), (232, 240, 236))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), 28, outline=(150, 170, 160), width=4)
    draw.text((40, 30), title, fill=(40, 70, 60), font=_font(40, True))
    y = 120
    for label, value in lines:
        draw.text((40, y), label, fill=(90, 100, 95), font=_font(26))
        draw.text((230, y), value, fill=(20, 20, 20), font=_font(34, True))
        y += 78
    if side == "front":
        draw.rounded_rectangle((width - 260, 110, width - 40, 440), 16, fill=(110, 118, 114))
        draw.text((width - 196, 250), "照片示意", fill=(235, 235, 235), font=_font(28))
    else:
        rng = random.Random(7)
        x = 40
        while x < 520:
            bar = rng.choice((3, 5, 8))
            draw.rectangle((x, 400, x + bar, 500), fill=(30, 30, 30))
            x += bar + rng.choice((3, 5, 7))
    mark = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(mark).text((170, 200), "合成樣本  SAMPLE", fill=(200, 40, 40, 110), font=_font(72, True))
    return Image.alpha_composite(card.convert("RGBA"), mark.rotate(18, center=(width / 2, height / 2))).convert("RGB")


def _photo(card, angle, path):
    desk = Image.new("RGB", (1400, 1050), (120, 112, 104))
    turned = card.rotate(angle, expand=True, fillcolor=(120, 112, 104))
    desk.paste(turned, ((1400 - turned.width) // 2, (1050 - turned.height) // 2))
    desk.save(path, quality=90)


def make_cards(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _photo(_card((("姓名", "王小明"), ("出生", "民國 79 年 5 月 12 日"), ("統一編號", "A123456789")), "示範證件（正面）", "front"),
           6, folder / "demo-id-front.jpg")
    _photo(_card((("住址", "示範市中正區示範路100號"), ("說明", "此為說明書用合成資料")), "示範證件（反面）", "back"),
           -4, folder / "demo-id-back.jpg")
    return folder
