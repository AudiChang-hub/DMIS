"""電子簽名蓋印：訂購單與個資同意書共用的圖像與頁尾註記。"""
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader

MUTED = HexColor("#777777")


@dataclass(frozen=True)
class DocumentSignature:
    image: bytes
    signer_name: str
    signed_at: datetime
    fingerprint: str
    staff_name: str = ""


def draw_signature_image(c, signature, x, baseline, max_width, max_height):
    reader = ImageReader(BytesIO(signature.image))
    width, height = reader.getSize()
    scale = min(max_width / width, max_height / height)
    c.drawImage(
        reader, x, baseline, width=width * scale, height=height * scale, mask="auto"
    )


def draw_signature_note(c, signature, font, x, y):
    c.saveState()
    c.setFillColor(MUTED)
    c.setFont(font, 6.5)
    c.drawString(
        x,
        y,
        f"電子簽署 {signature.signed_at:%Y-%m-%d %H:%M}・簽署人 {signature.signer_name}"
        f"・內容指紋 {signature.fingerprint[:12].upper()}",
    )
    c.restoreState()
