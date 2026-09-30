"""原廠官網車型比對：只讀官網、記錄差異，寫入僅限補上空白的車色圖片。

不修改既有車型的名稱、型號、年份、排氣量、動力類型、領牌級別、車色名稱、
啟用／上架狀態與售價版本；這些欄位由既有管理頁維護。
"""

import hashlib
import html
import io
import json
import logging
import re
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from urllib.parse import urljoin, urlsplit

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; DMIS-catalog-check/1.0)"
REQUEST_TIMEOUT = 20
REQUEST_DELAY = 0.5
FINGERPRINT_DELAY = 0.2
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ERRORS = 50
STALE_AFTER_SECONDS = 30 * 60

SOURCES = {
    "sym": {
        "label": "SYM",
        "brand_query": "SYM",
        "list_url": "https://tw.sym-global.com/product",
        "hosts": {"tw.sym-global.com"},
    },
    "suzuki": {
        "label": "SUZUKI",
        "brand_query": "SUZUKI",
        "list_url": "https://www.suzukimotor.com.tw/products.html",
        "hosts": {"www.suzukimotor.com.tw", "suzukimotor.com.tw"},
    },
}


class OfficialCatalogError(Exception):
    """官網讀取或解析失敗；訊息可直接顯示給管理者。"""


# ---------- 讀取 ----------

class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl, self.hosts):
            raise OfficialCatalogError("官網轉址到非原廠網域，已停止讀取。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _allowed_url(url, hosts):
    parts = urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").lower() in hosts


def _fetch(url, hosts, limit):
    if not _allowed_url(url, hosts):
        raise OfficialCatalogError("網址不屬於原廠官網。")
    opener = urllib.request.build_opener(_SameHostRedirect(hosts))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            body = response.read(limit + 1)
            content_type = response.headers.get("Content-Type", "")
    except OfficialCatalogError:
        raise
    except urllib.error.HTTPError as exc:
        raise OfficialCatalogError(f"官網回應 {exc.code}。") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise OfficialCatalogError("無法連線到官網。") from None
    if len(body) > limit:
        raise OfficialCatalogError("官網回應內容過大。")
    return body, content_type


def fetch_page(url, hosts):
    body, _ = _fetch(url, hosts, MAX_PAGE_BYTES)
    return body.decode("utf-8", errors="replace")


def fetch_image_fingerprint(url, hosts):
    """以 HEAD 取得圖片版本標記；檔名不變但原廠換了照片時，ETag／修改時間／大小會不同。"""
    if not _allowed_url(url, hosts):
        return ""
    opener = urllib.request.build_opener(_SameHostRedirect(hosts))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            headers = response.headers
    except (OfficialCatalogError, urllib.error.URLError, TimeoutError, OSError):
        return ""
    return "|".join(headers.get(name, "") for name in ("ETag", "Last-Modified", "Content-Length"))


def add_image_fingerprints(entry, hosts):
    """單張失敗只留空白，不影響整頁；空白不列為變動。"""
    for color in entry.get("colors", []):
        if color.get("image_url"):
            time.sleep(FINGERPRINT_DELAY)
            color["image_fingerprint"] = fetch_image_fingerprint(color["image_url"], hosts)
    if entry.get("main_image_url"):
        entry["main_image_fingerprint"] = fetch_image_fingerprint(entry["main_image_url"], hosts)
    return entry


def fetch_image(url, hosts):
    """下載並驗證原廠圖片，回傳可存入 ImageField 的檔案。"""
    from PIL import Image, UnidentifiedImageError

    body, _ = _fetch(url, hosts, MAX_IMAGE_BYTES)
    try:
        with Image.open(io.BytesIO(body)) as image:
            fmt = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise OfficialCatalogError("官網圖片無法辨識或已損壞。") from None
    extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(fmt)
    if not extension:
        raise OfficialCatalogError("官網圖片不是 JPEG、PNG 或 WebP。")
    return ContentFile(body, name=f"{uuid.uuid4().hex}.{extension}")


# ---------- 解析 ----------

def _strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _text(fragment):
    value = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _attr(tag, name):
    match = re.search(rf'\b{name}\s*=\s*(["\'])(.*?)\1', tag, flags=re.S)
    return html.unescape(match.group(2)).strip() if match else ""


def _img_src(tag):
    return _attr(tag, "data-src") or _attr(tag, "src")


def _section(text, start_marker, end_markers):
    start = text.find(start_marker)
    if start < 0:
        return ""
    ends = [text.find(marker, start + len(start_marker)) for marker in end_markers]
    ends = [pos for pos in ends if pos >= 0]
    return text[start:min(ends)] if ends else text[start:]


def _split_blocks(text, marker):
    """以 class 開頭切成同層區塊；官網以固定 class 排列，不做完整 DOM 解析。"""
    positions = [match.start() for match in re.finditer(marker, text)]
    return [text[pos:positions[index + 1] if index + 1 < len(positions) else len(text)]
            for index, pos in enumerate(positions)]


YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
SHORT_YEAR_PATTERN = re.compile(r"(?<!\d)(\d{2})\s*年式")


def _year_hint(*values):
    for value in values:
        match = YEAR_PATTERN.search(value or "")
        if match:
            return int(match.group(1))
        match = SHORT_YEAR_PATTERN.search(value or "")
        if match:
            return 2000 + int(match.group(1))
    return None


def _number(value):
    match = re.search(r"\d+(?:\.\d+)?", (value or "").replace(",", ""))
    return match.group(0) if match else ""


def _price(text):
    match = re.search(r"NT\.?\$?\s*([\d,]{4,})\s*元", text)
    return int(match.group(1).replace(",", "")) if match else None


def parse_sym_list(text, base_url):
    text = _strip_comments(text)
    entries, seen = [], set()
    category = ""
    for match in re.finditer(r'<h3[^>]*>(.*?)</h3>|(<span class="new-label[^"]*">[^<]*</span>\s*</div>\s*<div class="product__thumb">\s*)?<a class="first__img" href="([^"]+)"[^>]*>(.*?)</a>\s*<div class="product__content">\s*<h4>(.*?)</h4>', text, flags=re.S):
        if match.group(1) is not None:
            category = _text(match.group(1))
            continue
        url = urljoin(base_url, html.unescape(match.group(3)))
        slug = urlsplit(url).path.strip("/")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        image = re.search(r"<img[^>]*>", match.group(4))
        entries.append({
            "slug": slug, "url": url, "name": _text(match.group(5)), "category": category,
            "image_url": urljoin(base_url, _img_src(image.group(0))) if image else "",
            "official_label": _text(match.group(2) or "").upper(),
        })
    return entries


SYM_CODE = re.compile(r"\b([A-Z]{1,3}\d{2,4})\s*$")


def _sym_color(label, image_url):
    code_match = SYM_CODE.search(label)
    code = code_match.group(1) if code_match else ""
    stem = label[:code_match.start()].strip() if code_match else label
    stem = re.split(r"[-－]", stem, maxsplit=1)[0].strip()
    return {"name": label, "code": code, "stem": stem, "image_url": image_url}


def parse_sym_model(text, listing):
    """一頁可有多個版本（例如 ABS／標準），每個版本各為一筆官網車型。"""
    text = _strip_comments(text)
    base_url = listing["url"]
    tabs = [_text(tab) for tab in re.findall(r"<a[^>]*>(.*?)</a>", _section(text, 'class="butline"', ["</div>"]))]
    names = [_text(name) for name in re.findall(r"<div>(.*?)</div>", _section(text, 'class="typeabscba"', ['id="changtp-next"']), flags=re.S)]
    colors_area = _section(text, 'id="colorposition"', ['class="motoslide"', 'id="mobile_colorposition"'])
    color_groups = [
        [_text(label) for label in re.findall(r'<div class="text">(.*?)</div>', block, flags=re.S)]
        for block in _split_blocks(colors_area, r'<div class="colorchose')
    ]
    slides = _section(text, 'class="motoslide"', ['id="mobile_colorposition"'])
    image_groups = [
        [urljoin(base_url, _img_src(tag)) for tag in re.findall(r'<div class="x">\s*(<img[^>]*>)', block)]
        for block in _split_blocks(slides, r'<div class="picgroup')
    ]
    spec_area = _section(text, 'class="formtable"', ['id="jumpform-end"', "<footer"])
    spec_groups = [
        {_text(label): _text(value) for label, value in re.findall(r"<span>(.*?)</span>(.*?)</div>", block, flags=re.S)}
        for block in _split_blocks(spec_area, r'<div class="onef')
    ]
    variant_count = max(len(color_groups), len(image_groups), len(names), 1)
    entries = []
    for index in range(variant_count):
        labels = color_groups[index] if index < len(color_groups) else []
        images = image_groups[index] if index < len(image_groups) else []
        if labels and len(labels) != len(images):
            raise OfficialCatalogError(f"{listing['name']}：車色與圖片數量不一致，未採用。")
        specs = spec_groups[index] if index < len(spec_groups) else {}
        name = names[index] if index < len(names) else " ".join(
            part for part in (listing["name"], tabs[index] if index < len(tabs) else "") if part)
        entries.append({
            "source_key": listing["slug"] if variant_count == 1 else f"{listing['slug']}#{index + 1}",
            "source_url": base_url,
            "name": name or listing["name"],
            "variant": tabs[index] if index < len(tabs) else "",
            "category": listing.get("category", ""),
            "energy": "electric" if "電" in listing.get("category", "") or "電動馬達" in specs.get("引擎形式", "") else "gas",
            "official_label": listing.get("official_label", ""),
            "year_hint": _year_hint(name, *images),
            "displacement_cc": _number(specs.get("排氣量", "")),
            "power": specs.get("最大馬力", ""),
            "price": None,
            "price_note": "",
            "main_image_url": images[0] if images else listing.get("image_url", ""),
            "colors": [_sym_color(label, image) for label, image in zip(labels, images)],
            "specs": specs,
        })
    return entries


def parse_suzuki_list(text, base_url):
    text = _strip_comments(text)
    entries, seen = [], set()
    cards = list(re.finditer(r'<figure>\s*(<img[^>]*>)\s*</figure>\s*<h5[^>]*>((?:[^<]|<br\s*/?>)*)</h5>\s*<a href="([^"]*product/([^"/]+)/intro\.html)"', text))
    for index, match in enumerate(cards):
        slug = match.group(4)
        if slug in seen:
            continue
        seen.add(slug)
        card_end = cards[index + 1].start() if index + 1 < len(cards) else len(text)
        entries.append({
            "official_label": _ribbon(text[match.end():card_end]),
            "slug": slug,
            "url": urljoin(base_url, f"product/{slug}/style_price.html"),
            "name": _text(match.group(2)),
            "category": "",
            "image_url": urljoin(base_url, _img_src(match.group(1))),
        })
    return entries


def _ribbon(fragment):
    match = re.search(r'class="product-ribbon"><span>(.*?)</span>', fragment, flags=re.S)
    return _text(match.group(1)).upper() if match else ""


SUZUKI_CODE = re.compile(r"[（(]\s*([A-Za-z0-9]{2,4})\s*[)）]")


def _suzuki_color(label, image_url):
    code_match = SUZUKI_CODE.search(label)
    code = code_match.group(1).upper() if code_match else ""
    stem = re.split(r"[（(]", label, maxsplit=1)[0].strip()
    return {"name": label, "code": code, "stem": stem, "image_url": image_url}


def parse_suzuki_model(text, listing):
    text = _strip_comments(text)
    base_url = listing["url"]
    color_area = _section(text, 'id="color"', ['class="color-pager', 'id="spec"'])
    colors = [
        _suzuki_color(_attr(tag, "alt"), urljoin(base_url, _img_src(tag)))
        for tag in re.findall(r"<img[^>]*>", _section(color_area, "cycle-slideshow", ["</div>"]))
        if _attr(tag, "alt")
    ]
    specs = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", _section(text, 'id="spec"', ["<footer"]), flags=re.S):
        cells = [_text(cell) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]
        if len(cells) == 2 and cells[0] and not cells[0].startswith("(") and cells[0] not in specs:
            specs[cells[0]] = cells[1]
    price_area = _section(text, 'id="color"', ['id="spec"'])
    price = _price(_text(price_area))
    kv = re.search(r'<img[^>]*src="([^"]*kv_[^"]*)"', text)
    return [{
        "source_key": listing["slug"],
        "source_url": base_url,
        "name": listing["name"],
        "variant": "",
        "category": "",
        "energy": "electric" if "電動" in specs.get("引擎形式", "") else "gas",
        "official_label": listing.get("official_label", ""),
        "year_hint": _year_hint(*(color["name"] for color in colors)),
        "displacement_cc": _number(specs.get("排氣量", "")),
        "power": specs.get("最大馬力") or specs.get("馬力", ""),
        "price": price,
        "price_note": "不含牌險" if price and "不含牌險" in _text(price_area) else "",
        "main_image_url": urljoin(base_url, kv.group(1)) if kv else listing.get("image_url", ""),
        "colors": colors,
        "specs": specs,
    }]


PARSERS = {
    "sym": (parse_sym_list, parse_sym_model),
    "suzuki": (parse_suzuki_list, parse_suzuki_model),
}


def content_hash(entry):
    """只以會影響判斷的欄位計算，避免官網排版調整造成誤報。"""
    relevant = {
        "name": entry.get("name"),
        "displacement_cc": entry.get("displacement_cc"),
        "power": entry.get("power"),
        "price": entry.get("price"),
        "official_label": entry.get("official_label", ""),
        "specs": entry.get("specs", {}),
        "main_image": (entry.get("main_image_url"), entry.get("main_image_fingerprint", "")),
        "colors": sorted((color["code"] or color["name"], color["image_url"], color.get("image_fingerprint", ""))
                         for color in entry.get("colors", [])),
    }
    return hashlib.sha256(json.dumps(relevant, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def describe_changes(before, after):
    """比對上次確認與目前官網內容，回傳可讀的差異清單。"""
    if not before:
        return []
    changes = []
    old_colors = {color["code"] or color["name"]: color for color in before.get("colors", [])}
    new_colors = {color["code"] or color["name"]: color for color in after.get("colors", [])}
    added = [new_colors[key]["name"] for key in new_colors if key not in old_colors]
    removed = [old_colors[key]["name"] for key in old_colors if key not in new_colors]
    if added:
        changes.append("新增車色：" + "、".join(added))
    if removed:
        changes.append("官網已移除車色：" + "、".join(removed))
    replaced = [new_colors[key]["name"] for key in new_colors
                if key in old_colors and _image_changed(old_colors[key], new_colors[key])]
    if replaced:
        changes.append("車色圖片更換（可能改款或改外觀）：" + "、".join(replaced))
    if _image_changed({"image_url": before.get("main_image_url"), "image_fingerprint": before.get("main_image_fingerprint")},
                      {"image_url": after.get("main_image_url"), "image_fingerprint": after.get("main_image_fingerprint")}):
        changes.append("官網主圖更換")
    for field, label in (("official_label", "官網標籤"), ("name", "官網名稱"), ("displacement_cc", "排氣量"), ("power", "馬力"), ("price", "建議售價")):
        if (before.get(field) or "") != (after.get(field) or ""):
            changes.append(f"{label}：{before.get(field) or '—'} → {after.get(field) or '—'}")
    old_specs, new_specs = before.get("specs", {}), after.get("specs", {})
    spec_changes = [f"{label}：{old_specs.get(label) or '—'} → {new_specs.get(label) or '—'}"
                    for label in dict.fromkeys([*old_specs, *new_specs])
                    if label not in {"排氣量", "最大馬力", "馬力"} and old_specs.get(label) != new_specs.get(label)]
    if spec_changes:
        changes.append("規格變更：" + "；".join(spec_changes[:8]) + ("…" if len(spec_changes) > 8 else ""))
    return changes


def _image_changed(old, new):
    """網址不同，或同網址但版本標記不同才算更換；任一邊沒取得標記時不下結論。"""
    if (old.get("image_url") or "") != (new.get("image_url") or ""):
        return True
    old_mark, new_mark = old.get("image_fingerprint") or "", new.get("image_fingerprint") or ""
    return bool(old_mark and new_mark and old_mark != new_mark)


# ---------- 車型與車色對應 ----------

def _norm(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s\-_/．.·()（）]+", "", value)


def suggest_vehicle_models(entry, candidates):
    """依名稱相似度排序建議；只是預設選項，必須由人確認對應。"""
    official = _norm(re.sub(r"^\s*20\d{2}\s*", "", entry.get("name", "")))
    official_cc = float(entry["displacement_cc"]) if entry.get("displacement_cc") else None
    scored = []
    for model in candidates:
        name = _norm(model.name)
        if not name:
            continue
        # 同名不同排氣量（例如 125／158）不建議，避免誤選。
        if official_cc and model.displacement_cc and abs(model.displacement_cc - official_cc) > 3:
            continue
        if name == official:
            score = 2
        elif name in official or official in name:
            score = 1
        else:
            continue
        scored.append((score, model.model_year or 0, model))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].pk))
    return [model for _, _, model in scored]


def match_colors(official_colors, system_colors):
    """回傳 {系統車色 pk: 官網車色}；只接受雙向唯一的對應，其餘不猜。"""
    candidates = {}
    for color in system_colors:
        name = _norm(color.name)
        hits = []
        for index, official in enumerate(official_colors):
            code = _norm(official.get("code"))
            if (code and code in name) or name in {_norm(official.get("stem")), _norm(official.get("name"))}:
                hits.append(index)
        candidates[color.pk] = hits
    usage = {}
    for hits in candidates.values():
        for index in hits:
            usage[index] = usage.get(index, 0) + 1
    return {
        pk: official_colors[hits[0]]
        for pk, hits in candidates.items()
        if len(hits) == 1 and usage[hits[0]] == 1
    }


def fillable_colors(link):
    """已對應車型中，啟用、尚無圖片且可唯一對應官網圖片的車色。"""
    if not link.vehicle_model_id:
        return []
    system_colors = [color for color in link.vehicle_model.colors.all() if color.active]
    matches = match_colors(link.data.get("colors", []), system_colors)
    return [(color, matches[color.pk]) for color in system_colors
            if color.pk in matches and not color.catalog_image and matches[color.pk].get("image_url")]


# ---------- 從官網建立車型 ----------

def official_color_names(entry):
    """車色預填名稱：色名不重複時用簡名（去除色號與配色說明），否則用官網全名。"""
    colors = entry.get("colors", [])
    stems = [color.get("stem") or color["name"] for color in colors]
    if len({_norm(stem) for stem in stems}) == len(stems):
        return stems
    return [color["name"] for color in colors]


def model_prefill(link, base_model=None):
    """新增機種／年式表單的預填值；只是起點，儲存前由人確認，型號與型式仍須人工填寫。"""
    from datetime import date

    entry = link.data
    initial = {"active": False}
    if base_model:
        initial.update({
            "existing_family": base_model.family_id,
            "brand": base_model.brand,
            "energy_type": base_model.energy_type,
            "name": base_model.family.name if base_model.family_id else base_model.name,
            "model_code": base_model.model_code,
            "electric_registration_class": base_model.electric_registration_class,
            "model_number": "、".join(base_model.factory_model_codes.filter(active=True)
                                      .order_by("code").values_list("code", flat=True)) or base_model.model_number,
        })
    else:
        brands = list(brand_models(link.brand).values_list("brand", flat=True))
        name = re.sub(r"^\s*20\d{2}\s*[-－]?\s*", "", entry.get("name", ""))
        initial.update({
            "brand": max(set(brands), key=brands.count) if brands else SOURCES[link.brand]["label"],
            "energy_type": "electric" if entry.get("energy") == "electric" else "gas",
            "name": re.sub(r"^全新\s*", "", name).strip(),
        })
        certified = SUZUKI_CODE.search(entry.get("specs", {}).get("認證車型", ""))
        if certified:
            initial["model_number"] = certified.group(1).upper()
    base_year = base_model.model_year if base_model else None
    initial["model_year"] = entry.get("year_hint") or (base_year + 1 if base_year else date.today().year)
    if entry.get("displacement_cc") and initial["energy_type"] == "gas":
        initial["displacement_cc"] = round(float(entry["displacement_cc"]))
    power = re.search(r"(\d+(?:\.\d+)?)\s*kw", entry.get("power", ""), flags=re.I)
    if power and initial["energy_type"] != "gas":
        initial["motor_power_kw"] = power.group(1)
    return initial, official_color_names(entry)


# ---------- 背景檢查 ----------

def brand_models(brand):
    from sales.models import VehicleModel
    from sales.services.vehicle_brands import vehicle_brand_search_q

    return VehicleModel.objects.filter(vehicle_brand_search_q(SOURCES[brand]["brand_query"])).order_by("name", "-model_year", "pk")


def active_check(brand):
    from sales.models import OfficialCatalogCheck

    cutoff = timezone.now() - timezone.timedelta(seconds=STALE_AFTER_SECONDS)
    return OfficialCatalogCheck.objects.filter(
        brand=brand, status__in=("queued", "running"), updated_at__gte=cutoff,
    ).order_by("-created_at").first()


def run_official_catalog_check(check_id):
    """RQ 背景工作；逐頁讀取，單頁失敗只記錄錯誤，不影響其他車型。"""
    from sales.models import OfficialCatalogCheck

    check = OfficialCatalogCheck.objects.get(pk=check_id)
    if check.status != "queued":
        return
    source = SOURCES[check.brand]
    list_parser, model_parser = PARSERS[check.brand]
    check.status, check.started_at = "running", timezone.now()
    check.save(update_fields=["status", "started_at", "updated_at"])
    errors = []
    try:
        listings = list_parser(fetch_page(source["list_url"], source["hosts"]), source["list_url"])
        if not listings:
            raise OfficialCatalogError("官網產品列表沒有讀到任何車型，可能已改版。")
    except OfficialCatalogError as exc:
        _finish(check, "failed", [f"產品列表：{exc}"], 0)
        return
    except Exception:
        logger.exception("official_catalog_list_failed check=%s", check.pk)
        _finish(check, "failed", ["產品列表：解析失敗，官網可能已改版。"], 0)
        return
    OfficialCatalogCheck.objects.filter(pk=check.pk).update(pages_total=len(listings), updated_at=timezone.now())
    seen, found = set(), 0
    for number, listing in enumerate(listings, start=1):
        try:
            time.sleep(REQUEST_DELAY)
            entries = model_parser(fetch_page(listing["url"], source["hosts"]), listing)
            for entry in entries:
                add_image_fingerprints(entry, source["hosts"])
                _upsert_entry(check, entry)
                seen.add(entry["source_key"])
                found += 1
        except OfficialCatalogError as exc:
            errors.append(f"{listing['name']}：{exc}")
        except Exception:
            logger.exception("official_catalog_page_failed check=%s url=%s", check.pk, listing["url"])
            errors.append(f"{listing['name']}：解析失敗，官網可能已改版。")
        OfficialCatalogCheck.objects.filter(pk=check.pk).update(pages_done=number, updated_at=timezone.now())
    failed_keys = {listing["slug"] for listing in listings}
    _mark_missing(check.brand, seen, failed_keys if errors else set())
    _finish(check, "succeeded", errors, found)


def _upsert_entry(check, entry):
    from sales.models import OfficialCatalogModel

    now = timezone.now()
    digest = content_hash(entry)
    with transaction.atomic():
        link, created = OfficialCatalogModel.objects.select_for_update().get_or_create(
            brand=check.brand, source_key=entry["source_key"],
            defaults={"source_url": entry["source_url"], "name": entry["name"], "data": entry,
                      "content_hash": digest, "last_seen_at": now, "last_check": check},
        )
        if not created:
            link.source_url, link.name, link.data = entry["source_url"], entry["name"], entry
            link.content_hash, link.last_seen_at, link.last_check, link.missing = digest, now, check, False
            link.save(update_fields=["source_url", "name", "data", "content_hash", "last_seen_at",
                                     "last_check", "missing", "updated_at"])


def _mark_missing(brand, seen, uncertain_slugs):
    """官網列表不再出現的車型標示為已下架；讀取失敗的頁面不下結論。"""
    from sales.models import OfficialCatalogModel

    for link in OfficialCatalogModel.objects.filter(brand=brand, missing=False).exclude(source_key__in=seen):
        if link.source_key.split("#", 1)[0] in uncertain_slugs:
            continue
        link.missing = True
        link.save(update_fields=["missing", "updated_at"])


def _finish(check, status, errors, found):
    from sales.models import OfficialCatalogCheck

    OfficialCatalogCheck.objects.filter(pk=check.pk).update(
        status=status, finished_at=timezone.now(), entries_found=found,
        errors=errors[:MAX_ERRORS], error_count=len(errors), updated_at=timezone.now(),
    )
