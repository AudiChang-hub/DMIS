from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image, ImageOps
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


PURPOSE_LABELS = {
    "registration": "限領牌使用",
    "subsidy": "限申請補助使用",
}
SIDE_LABELS = {"id_front": "證件正面", "id_back": "證件反面"}
FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msjh.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
]
FONT_PATH = next((path for path in FONT_CANDIDATES if path.exists()), None)
if not FONT_PATH:
    raise RuntimeError("找不到可用的繁體中文字型。")
if "IdentityDocument" not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(
        TTFont("IdentityDocument", str(FONT_PATH), subfontIndex=0)
    )


def _image_reader(file_field):
    try:
        with file_field.open("rb") as source:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as raw:
                    image = ImageOps.exif_transpose(raw).convert("RGB")
                    output = BytesIO()
                    image.save(output, format="JPEG", quality=92, optimize=True)
                    output.seek(0)
                    return ImageReader(output), image.size, output
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ValueError("證件圖片過大、已損壞或無法讀取。") from exc


def _draw_watermark(pdf, text):
    pdf.saveState()
    pdf.setFillColor(Color(0.55, 0.08, 0.06, alpha=0.14))
    if hasattr(pdf, "setFillAlpha"):
        pdf.setFillAlpha(0.14)
    pdf.setFont("IdentityDocument", 21)
    pdf.translate(A4[0] / 2, A4[1] / 2)
    pdf.rotate(32)
    for y in range(-360, 361, 95):
        for x in (-240, 0, 240):
            pdf.drawCentredString(x, y, text)
    pdf.restoreState()


def build_identity_document_pdf(order, purpose, side_fields, generated_on):
    """Create a temporary, purpose-marked PDF without changing source images."""
    if purpose not in PURPOSE_LABELS:
        raise ValueError("不支援的證件使用目的。")
    # Follow the fixed document order and de-duplicate untrusted POST values.
    # Without this bound, repeating the same ``sides`` value could generate an
    # arbitrarily large PDF from a two-option form.
    requested_sides = set(side_fields)
    selected = [name for name in SIDE_LABELS if name in requested_sides]
    if not selected:
        raise ValueError("請至少選擇證件正面或反面。")

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdf.setTitle(f"{order.number} 證件影本")
    pdf.setAuthor("馭盛國際有限公司")
    watermark = f"{PURPOSE_LABELS[purpose]}  {generated_on:%Y/%m/%d}"

    for field_name in selected:
        file_field = getattr(order, field_name, None)
        if not file_field:
            raise ValueError(f"尚未保存{SIDE_LABELS[field_name]}。")
        image_reader, (image_width, image_height), buffer = _image_reader(file_field)
        try:
            margin_x, margin_y = 18 * mm, 28 * mm
            available_width = A4[0] - 2 * margin_x
            available_height = A4[1] - 2 * margin_y
            scale = min(
                available_width / image_width,
                available_height / image_height,
            )
            width, height = image_width * scale, image_height * scale
            x = (A4[0] - width) / 2
            y = (A4[1] - height) / 2
            pdf.setFillColor(HexColor("#17221D"))
            pdf.setFont("IdentityDocument", 12)
            pdf.drawString(margin_x, A4[1] - 16 * mm, SIDE_LABELS[field_name])
            pdf.drawRightString(
                A4[0] - margin_x,
                A4[1] - 16 * mm,
                order.number,
            )
            pdf.drawImage(
                image_reader,
                x,
                y,
                width=width,
                height=height,
                preserveAspectRatio=True,
                mask="auto",
            )
            _draw_watermark(pdf, watermark)
            pdf.setFillColor(HexColor("#5E6B64"))
            pdf.setFont("IdentityDocument", 9)
            pdf.drawCentredString(A4[0] / 2, 11 * mm, watermark)
            pdf.showPage()
        finally:
            buffer.close()

    pdf.save()
    return output.getvalue()
