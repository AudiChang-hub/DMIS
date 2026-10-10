"""調車簽收：同一車行一次調走多台、領車人在店內裝置簽名一次。

只在登入後的店內平板／手機簽署，不產生對外簽署連結。簽署後車輛改為「已調出」
（不算庫存也不算售出，保留進車紀錄）；作廢保留簽收紀錄，仍為已調出的車改回簽署前狀態。
"""
import hashlib
import json
from io import BytesIO
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from sales.models import (
    PrintCompany,
    VehicleInventory,
    VehicleTransferSignoff,
    record_vehicle_history,
)
from sales.services.inventory_location_note import FACTORY_LABEL
from sales.services.pdf_signature import DocumentSignature

ELIGIBLE_STATUSES = (
    VehicleInventory.Status.AVAILABLE,
    VehicleInventory.Status.CONDITION_ISSUE,
)
STATEMENT = "上列車輛已由領車人於本店當面點交，車況、車身與引擎號碼確認無誤後領走。"


def eligible_vehicles():
    """可調出的車：可銷售或車況異常；已預留（已配給訂單）的車不能調走。"""
    return (
        VehicleInventory.objects.filter(status__in=ELIGIBLE_STATUSES)
        .select_related("vehicle_model", "color", "current_dealer")
        .order_by("vehicle_model__name", "color__name", "received_on", "id")
    )


def selected_vehicles(vehicle_ids, *, lock=False):
    ids = sorted({int(value) for value in vehicle_ids if str(value).isdigit()})
    if not ids:
        raise ValidationError("請至少選擇一台要調出的車。")
    queryset = VehicleInventory.objects.select_related("vehicle_model", "color", "current_dealer")
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    vehicles = list(queryset.filter(pk__in=ids).order_by("id"))
    if len(vehicles) != len(ids):
        raise ValidationError("部分車輛已不存在，請重新選擇。")
    blocked = [v.identifier for v in vehicles if v.status not in ELIGIBLE_STATUSES]
    if blocked:
        raise ValidationError(
            f"{'、'.join(blocked)} 目前不是可銷售或車況異常（可能已配車、售出或調出），不能調出。"
        )
    return vehicles


def vehicle_snapshot(vehicles):
    return [
        {
            "id": vehicle.pk,
            "model": vehicle.vehicle_model.name,
            "model_number": vehicle.vehicle_model.model_number or "",
            "color": vehicle.color.name,
            "engine_number": vehicle.engine_number or "",
            "frame_number": vehicle.frame_number or "",
            "location": vehicle.actual_location_label,
            "status": vehicle.status,
        }
        for vehicle in vehicles
    ]


def content_fingerprint(*, dealer, dealer_name, note, vehicles):
    """簽收時確認的內容；送出前內容被改過（例如車被配走）就要重新確認。不記錄領車人姓名電話（使用者 2026-10-10）。"""
    payload = {
        "dealer": dealer.pk if dealer else None,
        "dealer_name": dealer_name,
        "note": note,
        "vehicles": [
            [item["id"], item["model"], item["color"], item["engine_number"], item["frame_number"]]
            for item in vehicle_snapshot(vehicles)
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def home_company():
    company = PrintCompany.objects.filter(key="home").first()
    if not company:
        return {}
    return {key: getattr(company, key) for key in ("legal_name", "tax_id", "address", "phone")}


def build_signoff_pdf(signoff, signature=None):
    """A4 簽收單：抬頭、調往對象、車輛清單、點交聲明與簽名；車多時自動換頁。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    import sales.services.privacy_consent_pdf  # noqa: F401  註冊正式中文字型

    regular, bold = "PrivacyFormal", "PrivacyFormal-Bold"
    title = ParagraphStyle("ts-title", fontName=bold, fontSize=19, leading=26, alignment=1, spaceAfter=2)
    sub = ParagraphStyle("ts-sub", fontName=regular, fontSize=9.5, leading=14, alignment=1, textColor=colors.HexColor("#555555"))
    body = ParagraphStyle("ts-body", fontName=regular, fontSize=10.5, leading=16)
    cell = ParagraphStyle("ts-cell", fontName=regular, fontSize=9.5, leading=13)
    head = ParagraphStyle("ts-head", parent=cell, fontName=bold)
    muted = ParagraphStyle("ts-muted", fontName=regular, fontSize=7, leading=10, textColor=colors.HexColor("#777777"))

    company = signoff.company_snapshot or {}
    signed_at = timezone.localtime(signoff.signed_at)
    story = [Paragraph("車 輛 調 車 簽 收 單", title)]
    if company.get("legal_name"):
        story.append(Paragraph(escape(
            "　".join(part for part in (company.get("legal_name"), company.get("address"), company.get("phone")) if part)
        ), sub))
    story.append(Spacer(1, 7 * mm))

    def row(label, value):
        return [Paragraph(label, head), Paragraph(escape(value or "—"), cell)]

    info = Table(
        [
            row("簽收單號", signoff.number) + row("簽收日期", f"{signed_at:%Y/%m/%d %H:%M}"),
            row("調往車行", signoff.dealer_name) + row("車輛台數", f"{len(signoff.vehicles_snapshot)} 台"),
            row("經手人", signoff.staff_name) + row("備註", signoff.note),
        ],
        colWidths=[24 * mm, 61 * mm, 24 * mm, 61 * mm],
    )
    info.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f1ee")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f1ee")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [info, Spacer(1, 6 * mm)]

    rows = [[Paragraph(text, head) for text in ("序", "車型", "車色", "引擎號碼", "車身號碼")]]
    for index, item in enumerate(signoff.vehicles_snapshot, 1):
        model = item["model"] + (f"（{item['model_number']}）" if item.get("model_number") else "")
        rows.append([
            Paragraph(str(index), cell), Paragraph(escape(model), cell), Paragraph(escape(item["color"]), cell),
            Paragraph(escape(item["engine_number"] or "—"), cell), Paragraph(escape(item["frame_number"] or "—"), cell),
        ])
    vehicles = Table(rows, colWidths=[10 * mm, 52 * mm, 26 * mm, 41 * mm, 41 * mm], repeatRows=1)
    vehicles.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f1ee")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [vehicles, Spacer(1, 6 * mm), Paragraph(STATEMENT, body), Spacer(1, 8 * mm)]

    if signature:
        image = Image(BytesIO(signature.image))
        scale = min(70 * mm / image.imageWidth, 22 * mm / image.imageHeight)
        image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
        signed_cell = image
    else:
        signed_cell = Paragraph("", body)
    sign_table = Table(
        [[Paragraph("領車人簽名：", body), signed_cell]],
        colWidths=[28 * mm, 80 * mm], hAlign="RIGHT", rowHeights=[26 * mm],
    )
    sign_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEBELOW", (1, 0), (1, 0), 0.8, colors.black),
    ]))
    story.append(sign_table)
    if signature:
        story += [Spacer(1, 3 * mm), Paragraph(escape(
            f"電子簽署 {signed_at:%Y-%m-%d %H:%M}・經手 {signature.staff_name}"
            f"・內容指紋 {signature.fingerprint[:12].upper()}・本簽收單僅於店內裝置簽署"
        ), muted)]

    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
        title=f"{signoff.number} 調車簽收單", author=company.get("legal_name", ""),
    )
    document.build(story)
    return output.getvalue()


@transaction.atomic
def prepare_transfer(*, dealer, dealer_name, vehicle_ids, note, user, pending=None):
    """預備調車：先存成「待簽收」，等人來再簽名。車輛暫不改狀態，簽收時再檢查一次是否仍可調出。"""
    vehicles = selected_vehicles(vehicle_ids)
    actor = (user.get_full_name() or user.get_username())[:150]
    if pending is not None:
        signoff = VehicleTransferSignoff.objects.select_for_update().get(pk=pending.pk)
        if not signoff.is_pending:
            raise ValidationError("這筆預備調車已經簽收，不能再修改。")
    else:
        signoff = VehicleTransferSignoff(status=VehicleTransferSignoff.Status.PENDING)
    signoff.dealer = dealer
    signoff.dealer_name = dealer_name
    signoff.note = note
    signoff.vehicles_snapshot = vehicle_snapshot(vehicles)
    signoff.prepared_by = actor
    signoff.save()
    signoff.vehicles.set(vehicles)
    return signoff


@transaction.atomic
def cancel_pending(signoff):
    """取消預備調車：還沒簽收、車輛也沒異動，直接移除這筆預備。"""
    signoff = VehicleTransferSignoff.objects.select_for_update().get(pk=signoff.pk)
    if not signoff.is_pending:
        raise ValidationError("這筆調車已經簽收，請改用作廢。")
    signoff.delete()


@transaction.atomic
def sign_transfer(*, dealer, dealer_name, vehicle_ids, note, expected_fingerprint, signature_png,
                  user, client_ip, user_agent, pending=None):
    vehicles = selected_vehicles(vehicle_ids, lock=True)
    fingerprint = content_fingerprint(dealer=dealer, dealer_name=dealer_name, note=note, vehicles=vehicles)
    if fingerprint != expected_fingerprint:
        raise ValidationError("車輛或簽收內容剛被修改，請返回重新確認後再簽名。")
    staff_name = (user.get_full_name() or user.get_username())[:60]
    signed_at = timezone.now()
    fields = dict(
        status=VehicleTransferSignoff.Status.SIGNED, dealer=dealer, dealer_name=dealer_name,
        vehicles_snapshot=vehicle_snapshot(vehicles), company_snapshot=home_company(), note=note,
        fingerprint=fingerprint, signed_at=signed_at, staff=user, staff_name=staff_name,
        client_ip=client_ip or "", user_agent=(user_agent or "")[:300],
    )
    if pending is not None:
        signoff = VehicleTransferSignoff.objects.select_for_update().get(pk=pending.pk)
        if not signoff.is_pending:
            raise ValidationError("這筆預備調車已經簽收過了。")
        for name, value in fields.items():
            setattr(signoff, name, value)
        signoff.save()
    else:
        signoff = VehicleTransferSignoff.objects.create(**fields)
    signature = DocumentSignature(
        image=signature_png, signer_name="", signed_at=timezone.localtime(signed_at),
        fingerprint=fingerprint, staff_name=staff_name,
    )
    pdf = build_signoff_pdf(signoff, signature)
    stem = f"{signoff.number}-{signed_at:%H%M%S}"
    signoff.signature_image.save(f"{stem}-signature.png", ContentFile(signature_png), save=False)
    signoff.signed_pdf.save(f"{stem}.pdf", ContentFile(pdf), save=False)
    signoff.pdf_sha256 = hashlib.sha256(pdf).hexdigest()
    signoff.save(update_fields=["signature_image", "signed_pdf", "pdf_sha256", "updated_at"])
    signoff.vehicles.set(vehicles)

    today = timezone.localdate()
    reason = f"調車簽收 {signoff.number}：調往 {dealer_name}"
    for vehicle in vehicles:
        before_status = vehicle.status
        vehicle.status = VehicleInventory.Status.TRANSFERRED_OUT
        vehicle.disposition = VehicleInventory.Disposition.TRANSFER_OUT
        vehicle.disposition_dealer = dealer
        vehicle.disposition_dealer_name = dealer_name
        vehicle.disposition_on = today
        vehicle.save(update_fields=[
            "status", "disposition", "disposition_dealer", "disposition_dealer_name",
            "disposition_on", "updated_at",
        ])
        record_vehicle_history(vehicle, actor_name=staff_name, reason=reason, before_status=before_status)
    return signoff


@transaction.atomic
def void_signoff(signoff, *, actor_name, reason):
    """作廢保留簽收紀錄；只把仍為已調出、且最後一次調出就是這張簽收單的車改回簽署前狀態。"""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("請填寫作廢原因。")
    signoff = VehicleTransferSignoff.objects.select_for_update().get(pk=signoff.pk)
    if signoff.is_voided:
        raise ValidationError("這張簽收單已經作廢。")
    if signoff.is_pending:
        raise ValidationError("預備調車尚未簽收，請改用取消預備。")
    previous = {item["id"]: item.get("status") for item in signoff.vehicles_snapshot}
    restored, kept = [], []
    vehicles = VehicleInventory.objects.select_for_update(of=("self",)).filter(
        pk__in=signoff.vehicles.values("pk")
    ).order_by("id")
    for vehicle in vehicles:
        latest = vehicle.transfer_signoffs.filter(
            voided_at__isnull=True, status=VehicleTransferSignoff.Status.SIGNED,
        ).order_by("-signed_at", "-id").first()
        if vehicle.status != VehicleInventory.Status.TRANSFERRED_OUT or latest != signoff:
            kept.append(vehicle.identifier)
            continue
        before_status = vehicle.status
        vehicle.status = previous.get(vehicle.pk) or VehicleInventory.Status.AVAILABLE
        if vehicle.status not in ELIGIBLE_STATUSES:
            vehicle.status = VehicleInventory.Status.AVAILABLE
        vehicle.disposition = ""
        vehicle.disposition_dealer = None
        vehicle.disposition_dealer_name = ""
        vehicle.disposition_on = None
        vehicle.save(update_fields=[
            "status", "disposition", "disposition_dealer", "disposition_dealer_name",
            "disposition_on", "updated_at",
        ])
        record_vehicle_history(
            vehicle, actor_name=actor_name,
            reason=f"作廢調車簽收 {signoff.number}：{reason}", before_status=before_status,
        )
        restored.append(vehicle.identifier)
    signoff.voided_at = timezone.now()
    signoff.voided_by = actor_name[:150]
    signoff.void_reason = reason[:300]
    signoff.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    return restored, kept
