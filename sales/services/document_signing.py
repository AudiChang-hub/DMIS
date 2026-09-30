"""店內行動裝置電子簽署：內容指紋、簽名驗證、簽署存檔與選擇列印。

指紋只涵蓋客戶同意的合約內容，不含收款進度與領牌結果；
內容改變後原簽署即失效，必須重新簽署（紙本上傳亦同）。
"""
import base64
import binascii
import hashlib
import json
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from sales.services.pdf_signature import DocumentSignature

DOCUMENTS = {
    "contract": {"label": "車輛訂購單", "field": "signed_contract"},
    "privacy": {"label": "個人資料使用同意書", "field": "privacy_consent"},
}
PRINT_PARTS = {
    "contract_store": ("contract", 0, "訂購單・店家留存聯"),
    "contract_customer": ("contract", 1, "訂購單・客戶留存聯"),
    "privacy": ("privacy", 0, "個資同意書"),
}
MAX_SIGNATURE_BYTES = 1_500_000
MAX_SIGNATURE_SIDE = 4000
MIN_INK_PIXELS = 120


def _plain(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value else "0"
    return "" if value is None else str(value)


def _company_name(order):
    return (order.print_company_snapshot or {}).get("legal_name", "")


def contract_terms(order):
    fields = (
        "owner_name", "owner_phone", "owner_address", "vehicle_category", "source_id",
        "vehicle_model_id", "color_id", "payment_type", "installment_company",
        "installment_periods", "installment_monthly", "installment_opening_fee",
        "delivery_method", "delivery_destination", "plate_choice", "watched_numbers",
        "plate_preference_note", "note", "vehicle_price", "plate_insurance_fee",
        "plate_selection_fee", "lien_registration_fee", "compulsory_insurance_period",
        "approved_discount_amount", "deposit_amount", "is_trade_in_subsidy", "subsidy_type",
        "old_owner_same_as_owner", "old_owner_name", "trade_in_plate",
    )
    terms = {name: _plain(getattr(order, name)) for name in fields}
    terms["company"] = _company_name(order)
    terms["total"] = _plain(order.calculate_balance()) if order.pk else ""
    if order.pk:
        terms["accessories"] = [
            [line.name, line.line_type, _plain(line.quantity), _plain(line.amount), _plain(line.labor_fee), line.note]
            for line in order.accessories.all()
        ]
        terms["other_fees"] = [[fee.name, _plain(fee.amount)] for fee in order.other_fees.all()]
    return terms


def privacy_terms(order):
    return {
        "owner_name": order.owner_name,
        "owner_id_number": order.owner_id_number,
        "company": _company_name(order),
    }


def current_fingerprint(order, document):
    terms = contract_terms(order) if document == "contract" else privacy_terms(order)
    payload = json.dumps(terms, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def document_state(order, document):
    field = DOCUMENTS[document]["field"]
    if getattr(order, f"{field}_stale"):
        return "stale"
    if getattr(order, f"{field}_is_electronic"):
        return "electronic"
    if order.has_signed_contract if document == "contract" else order.has_privacy_consent:
        return "paper"
    return "missing"


def decode_signature(data_url):
    """只接受畫布輸出的 PNG；重新編碼並裁切空白，避免保存原始上傳內容。"""
    prefix = "data:image/png;base64,"
    if not data_url or not data_url.startswith(prefix):
        raise ValidationError("請在簽名框內簽名。")
    encoded = data_url[len(prefix):]
    if len(encoded) > MAX_SIGNATURE_BYTES * 4 // 3 + 4:
        raise ValidationError("簽名資料過大，請清除後重新簽名。")
    try:
        raw = base64.b64decode(encoded, validate=True)
        image = Image.open(BytesIO(raw))
        if image.format != "PNG" or max(image.size) > MAX_SIGNATURE_SIDE:
            raise ValidationError("簽名格式不正確，請清除後重新簽名。")
        image = image.convert("RGBA")
    except (binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise ValidationError("簽名格式不正確，請清除後重新簽名。") from exc
    alpha = image.getchannel("A").point(lambda value: 255 if value > 40 else 0)
    box = alpha.getbbox()
    ink = alpha.histogram()[255] if box else 0
    if not box or ink < MIN_INK_PIXELS or box[2] - box[0] < 30:
        raise ValidationError("簽名太短或空白，請完整簽名。")
    pad = 8
    box = (
        max(box[0] - pad, 0), max(box[1] - pad, 0),
        min(box[2] + pad, image.width), min(box[3] + pad, image.height),
    )
    # 夜間主題的筆跡是淺色；蓋到白色文件前一律改成黑色，只保留筆跡透明度。
    ink_only = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ink_only.putalpha(image.getchannel("A"))
    output = BytesIO()
    ink_only.crop(box).save(output, format="PNG", optimize=True)
    return output.getvalue()


def build_document_pdf(order, document, signature=None):
    from sales.services.order_contract_pdf import build_order_contract_pdf
    from sales.services.privacy_consent_pdf import build_privacy_consent_pdf
    builder = build_order_contract_pdf if document == "contract" else build_privacy_consent_pdf
    return builder(order, signature=signature)


def render_preview_png(pdf_bytes, page_index=0, scale=1.6):
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        image = page.render(scale=scale).to_pil()
        page.close()
    finally:
        document.close()
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


@transaction.atomic
def sign_documents(order, *, documents, signature_png, signer_name, staff_name, actor, client_ip, user_agent):
    """產生含簽名的 PDF 存回原附件欄位；回傳被取代的舊檔名供交易後清理。"""
    from sales.models import OrderEvent, SalesOrder, SignatureMethod

    order = (
        SalesOrder.objects.select_for_update()
        .select_related("source", "vehicle_model", "color")
        .prefetch_related("accessories", "other_fees")
        .get(pk=order.pk)
    )
    signed_at = timezone.localtime()
    replaced = {}
    update_fields = {"updated_at"}
    for document in documents:
        field = DOCUMENTS[document]["field"]
        fingerprint = order.document_fingerprint(document)
        signature = DocumentSignature(
            image=signature_png,
            signer_name=signer_name,
            signed_at=signed_at,
            fingerprint=fingerprint,
            staff_name=staff_name,
        )
        pdf = build_document_pdf(order, document, signature)
        replaced[field] = getattr(order, field).name or ""
        getattr(order, field).save(
            f"{order.number}-{document}-esign-{signed_at:%Y%m%d%H%M%S}.pdf",
            ContentFile(pdf),
            save=False,
        )
        setattr(order, f"{field}_uploaded_at", timezone.now())
        setattr(order, f"{field}_method", SignatureMethod.ELECTRONIC)
        setattr(order, f"{field}_fingerprint", fingerprint)
        update_fields |= {field, f"{field}_uploaded_at", f"{field}_method", f"{field}_fingerprint"}
        OrderEvent.objects.create(
            order=order,
            event_type=f"{document}_esigned",
            description=(
                f"客戶於店內行動裝置電子簽署{DOCUMENTS[document]['label']}。簽署人：{signer_name}；"
                f"經手：{staff_name}；IP：{client_ip or '未知'}；裝置：{(user_agent or '未知')[:160]}；"
                f"內容指紋：{fingerprint}；檔案 SHA-256：{hashlib.sha256(pdf).hexdigest()}"
            ),
            actor_name=actor,
        )
    order.save(update_fields=sorted(update_fields))
    return order, replaced


def record_paper_upload(order, document):
    """紙本上傳視為簽署當下內容；之後改合約內容同樣需要重簽。"""
    from sales.models import SignatureMethod

    field = DOCUMENTS[document]["field"]
    setattr(order, f"{field}_method", SignatureMethod.PAPER)
    setattr(order, f"{field}_fingerprint", order.document_fingerprint(document))


def build_selected_pdf(order, parts):
    """依選擇的聯別合併列印；有效電子簽署用已簽檔，否則印空白供紙本簽名。"""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.add_metadata({"/Author": _company_name(order), "/Title": f"{order.number} 簽署文件"})
    readers = {}
    for part in parts:
        document, page_index, _ = PRINT_PARTS[part]
        if document not in readers:
            field = DOCUMENTS[document]["field"]
            if getattr(order, f"{field}_is_electronic"):
                with getattr(order, field).open("rb") as handle:
                    content = handle.read()
            else:
                content = build_document_pdf(order, document)
            readers[document] = PdfReader(BytesIO(content))
        pages = readers[document].pages
        if page_index < len(pages):
            writer.add_page(pages[page_index])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
