"""教學影片用的示範環境資料（全為虛構，不含任何真實客戶個資）。

用法：
    set PYTHONPATH=<含 tutorial_settings.py 的資料夾>
    python tools/tutorials/demo_seed.py
資料庫與媒體檔放在 tutorial_settings 指定的暫存位置，錄完即可刪除。
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tutorial_settings")

import django  # noqa: E402

django.setup()

from io import BytesIO  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.files.base import ContentFile  # noqa: E402
from django.utils import timezone  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from sales.models import (  # noqa: E402
    AccessoryProduct, PrintCompany, SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel,
    VehiclePriceVersion,
)

PASSWORD = "Tutorial-Only-123"
FONT = Path(r"C:\Windows\Fonts\msjh.ttc")


def sample_id_images(folder):
    """產生「範例」字樣的假證件圖，供上傳示範；不是任何真人的證件。"""
    folder.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(FONT), 40) if FONT.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(FONT), 28) if FONT.exists() else ImageFont.load_default()
    for side, lines in (
        ("front", ["示範用證件・正面", "姓名　王小明", "出生　民國 80 年 5 月 20 日", "統一編號　A123456789"]),
        ("back", ["示範用證件・反面", "住址　新北市示範區示範路 1 號", "（教學影片範例，非真實資料）"]),
    ):
        image = Image.new("RGB", (856, 540), (236, 242, 247))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 840, 524), outline=(120, 140, 170), width=4)
        draw.text((48, 40), "範例", font=font, fill=(200, 40, 40))
        for index, text in enumerate(lines):
            draw.text((48, 130 + index * 70), text, font=small if index else font, fill=(30, 40, 60))
        image.save(folder / f"id-{side}.png")


COLOR_RGB = {
    "消光黑": (48, 50, 56), "珍珠白": (238, 236, 230), "帕瑪森白": (232, 228, 214), "消光灰": (128, 132, 138),
    "鈦灰": (96, 102, 110), "競技藍": (36, 92, 196),
}


def scooter_image(color_name):
    """車色示意圖（程式繪製的機車剪影，標示「示意圖」），讓選車頁不顯示「圖片待補」。"""
    body = COLOR_RGB.get(color_name, (150, 150, 150))
    image = Image.new("RGB", (960, 640), (244, 245, 248))
    draw = ImageDraw.Draw(image)
    draw.ellipse((150, 380, 330, 560), fill=(40, 40, 44))
    draw.ellipse((640, 380, 820, 560), fill=(40, 40, 44))
    draw.ellipse((195, 425, 285, 515), fill=(170, 172, 176))
    draw.ellipse((685, 425, 775, 515), fill=(170, 172, 176))
    draw.polygon([(210, 420), (330, 300), (560, 300), (640, 250), (720, 250), (760, 420), (620, 470), (340, 470)], fill=body, outline=(60, 60, 64))
    draw.rounded_rectangle((360, 255, 600, 300), radius=18, fill=(34, 34, 38))
    draw.line((700, 250, 660, 140), fill=(60, 60, 64), width=14)
    draw.line((630, 140, 700, 140), fill=(60, 60, 64), width=12)
    font = ImageFont.truetype(str(FONT), 30) if FONT.exists() else ImageFont.load_default()
    draw.text((32, 24), "示意圖", font=font, fill=(150, 150, 156))
    output = BytesIO()
    image.save(output, format="PNG")
    return ContentFile(output.getvalue(), name=f"demo-{color_name}.png")


def run():
    User = get_user_model()
    admin, _ = User.objects.get_or_create(username="admin", defaults={"is_superuser": True, "is_staff": True})
    admin.is_superuser = admin.is_staff = True
    admin.first_name = "示範店長"
    admin.set_password(PASSWORD)
    admin.save()

    store, _ = Store.objects.get_or_create(code="MAIN", defaults={"name": "示範門市"})
    PrintCompany.objects.update_or_create(key="home", defaults=dict(
        legal_name="示範機車行有限公司", tax_id="12345678", address="新北市示範區示範路 1 號", phone="02-1234-5678",
    ))
    SalesSource.objects.get_or_create(name="示範門市", defaults={"source_type": "store", "active": True})
    for name in ("昌勝車行", "大發車行"):
        SalesSource.objects.get_or_create(name=name, defaults={"source_type": "dealer", "active": True})
    for name, price, labor in (("全罩式安全帽", 2800, 0), ("後扶手置物箱", 1800, 300)):
        AccessoryProduct.objects.get_or_create(name=name, defaults={"sale_price": price, "labor_fee": labor, "active": True})

    today = timezone.localdate()
    models = (
        ("SYM", "JET SL 125", "TB12V1", 125, 89800, ("消光黑", "珍珠白")),
        ("SUZUKI", "SUI 125", "UQ125DA", 125, 75000, ("帕瑪森白", "消光灰")),
        ("SYM", "DRG 158", "TD16V1", 158, 112000, ("鈦灰", "競技藍")),
    )
    serial = 1000
    for brand, name, number, cc, price, colors in models:
        model, _ = VehicleModel.objects.get_or_create(
            brand=brand, name=name,
            defaults={"model_number": number, "energy_type": "gas", "model_year": today.year, "displacement_cc": cc},
        )
        VehiclePriceVersion.objects.get_or_create(
            vehicle_model=model, effective_from=today - timedelta(days=30), defaults={"cash_price": price},
        )
        for color_name in colors:
            color, _ = VehicleColor.objects.get_or_create(vehicle_model=model, name=color_name, defaults={"active": True})
            if not color.catalog_image:
                color.catalog_image.save(f"demo-{color.pk}.png", scooter_image(color_name), save=True)
            for offset in range(2):
                serial += 1
                VehicleInventory.objects.get_or_create(
                    engine_number=f"DEMO{serial}",
                    defaults=dict(vehicle_model=model, color=color, ownership_store=store, location_store=store,
                                  received_on=today - timedelta(days=10 + offset), manufactured_year_month=f"{today.year}/0{6 + offset}"),
                )
    sample_id_images(Path(os.environ.get("TUTORIAL_ASSETS", ROOT / "tools/tutorials/.assets")))
    print("demo ready")


if __name__ == "__main__":
    run()
