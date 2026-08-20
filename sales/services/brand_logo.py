from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageOps


LOGO_ASPECT_RATIO = 2
LOGO_OUTPUT_SIZE = (800, 400)


def _read_file(file_value):
    file_value.open("rb")
    try:
        return file_value.read()
    finally:
        file_value.close()


def _normalized_crop(crop_data):
    values = {
        key: float((crop_data or {}).get(key, default))
        for key, default in (("x", 0), ("y", 0), ("width", 1), ("height", 1))
    }
    values["width"] = min(max(values["width"], 0.01), 1)
    values["height"] = min(max(values["height"], 0.01), 1)
    values["x"] = min(max(values["x"], 0), 1 - values["width"])
    values["y"] = min(max(values["y"], 0), 1 - values["height"])
    return {key: round(value, 6) for key, value in values.items()}


def _centered_crop(image):
    width, height = image.size
    if width / height >= LOGO_ASPECT_RATIO:
        crop_height = height
        crop_width = height * LOGO_ASPECT_RATIO
    else:
        crop_width = width
        crop_height = width / LOGO_ASPECT_RATIO
    return _normalized_crop(
        {
            "x": (width - crop_width) / 2 / width,
            "y": (height - crop_height) / 2 / height,
            "width": crop_width / width,
            "height": crop_height / height,
        }
    )


def build_brand_logo(source_bytes, crop_data=None):
    with Image.open(BytesIO(source_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        normalized = _normalized_crop(crop_data) if crop_data else _centered_crop(image)
        width, height = image.size
        left = round(normalized["x"] * width)
        top = round(normalized["y"] * height)
        right = round((normalized["x"] + normalized["width"]) * width)
        bottom = round((normalized["y"] + normalized["height"]) * height)
        cropped = image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
        cropped.thumbnail(LOGO_OUTPUT_SIZE, Image.Resampling.LANCZOS)
        output = Image.new("RGBA", LOGO_OUTPUT_SIZE, (255, 255, 255, 0))
        output.alpha_composite(
            cropped,
            ((LOGO_OUTPUT_SIZE[0] - cropped.width) // 2, (LOGO_OUTPUT_SIZE[1] - cropped.height) // 2),
        )
        buffer = BytesIO()
        output.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), normalized


def apply_brand_logo(brand, uploaded_file=None, crop_data=None):
    if uploaded_file:
        uploaded_file.seek(0)
        source_bytes = uploaded_file.read()
        uploaded_file.seek(0)
        suffix = Path(uploaded_file.name or "logo.png").suffix.lower() or ".png"
        brand.logo_original.save(
            f"brand-logo-source-{uuid4().hex}{suffix}",
            ContentFile(source_bytes),
            save=False,
        )
    else:
        source_field = brand.logo_original or brand.logo
        if not source_field:
            return
        source_bytes = _read_file(source_field)
        if not brand.logo_original:
            brand.logo_original.save(
                f"brand-logo-source-{uuid4().hex}{Path(source_field.name).suffix or '.png'}",
                ContentFile(source_bytes),
                save=False,
            )

    rendered, normalized = build_brand_logo(source_bytes, crop_data)
    brand.logo.save(
        f"brand-logo-{uuid4().hex}.png",
        ContentFile(rendered),
        save=False,
    )
    brand.logo_crop_data = normalized


def clear_brand_logo(brand):
    brand.logo = ""
    brand.logo_original = ""
    brand.logo_crop_data = {}
