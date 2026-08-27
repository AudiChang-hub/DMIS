import calendar
import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.db import transaction

from sales.models import BusinessHoliday


DATASET_METADATA_URL = "https://data.gov.tw/api/v2/rest/dataset/14718"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
USER_AGENT = "DMIS-business-calendar/1.0"


class CalendarSyncError(RuntimeError):
    """官方行事曆無法安全套用時使用。"""


@dataclass(frozen=True)
class CalendarResource:
    year: int
    url: str


def _read_url(url):
    parsed = urlparse(url)
    allowed_hosts = {"data.gov.tw", "www.dgpa.gov.tw"}
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise CalendarSyncError("官方行事曆來源網址不在允許清單內。")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in allowed_hosts:
                raise CalendarSyncError("官方行事曆下載被導向非允許來源。")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise CalendarSyncError("官方行事曆回傳內容超過安全大小限制。")
            return payload
    except OSError as exc:
        raise CalendarSyncError(f"無法連線官方行事曆：{exc}") from exc


def _discover_resources(payload, years):
    try:
        metadata = json.loads(payload.decode("utf-8"))
        distributions = metadata["result"]["distribution"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CalendarSyncError("政府資料開放平臺回傳格式無法辨識。") from exc

    resources = {}
    for year in years:
        roc_year = year - 1911
        expected_name = f"{roc_year}年中華民國政府行政機關辦公日曆表"
        candidates = [
            item
            for item in distributions
            if item.get("resourceDescription") == expected_name
            and str(item.get("resourceFormat", "")).upper() == "CSV"
        ]
        if not candidates:
            continue
        url = candidates[0].get("resourceDownloadUrl", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "www.dgpa.gov.tw":
            raise CalendarSyncError(f"{year} 年官方下載網址不符合安全規則。")
        resources[year] = CalendarResource(year=year, url=url)
    return resources


def _decode_csv(payload):
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CalendarSyncError("官方行事曆 CSV 編碼無法辨識。")


def _parse_calendar(payload, expected_year):
    reader = csv.DictReader(io.StringIO(_decode_csv(payload)))
    required_fields = {"西元日期", "是否放假", "備註"}
    if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
        raise CalendarSyncError(f"{expected_year} 年官方行事曆缺少必要欄位。")

    all_dates = set()
    holidays = {}
    for row in reader:
        raw_date = (row.get("西元日期") or "").strip()
        holiday_flag = (row.get("是否放假") or "").strip()
        try:
            day = datetime.strptime(raw_date, "%Y%m%d").date()
        except ValueError as exc:
            raise CalendarSyncError(
                f"{expected_year} 年官方行事曆含無效日期：{raw_date or '空白'}。"
            ) from exc
        if day.year != expected_year or day in all_dates:
            raise CalendarSyncError(f"{expected_year} 年官方行事曆日期範圍或內容重複。")
        if holiday_flag not in {"0", "2"}:
            raise CalendarSyncError(
                f"{expected_year} 年官方行事曆含未知放假代碼：{holiday_flag or '空白'}。"
            )
        all_dates.add(day)
        if holiday_flag == "2" and day.weekday() < 5:
            holidays[day] = (row.get("備註") or "").strip() or "政府行政機關放假日"

    expected_days = 366 if calendar.isleap(expected_year) else 365
    if len(all_dates) != expected_days:
        raise CalendarSyncError(
            f"{expected_year} 年官方行事曆不完整：應有 {expected_days} 日，實際 {len(all_dates)} 日。"
        )
    if not holidays:
        raise CalendarSyncError(f"{expected_year} 年官方行事曆沒有任何平日放假資料。")
    return holidays


def sync_official_business_calendar(*, years, required_years=None, reader=None):
    """下載並同步指定年度；所有資料驗證完成後才會開始寫入。"""
    normalized_years = tuple(sorted({int(year) for year in years}))
    if not normalized_years:
        raise CalendarSyncError("至少需要指定一個同步年度。")
    required = set(required_years or normalized_years)
    read = reader or _read_url

    resources = _discover_resources(read(DATASET_METADATA_URL), normalized_years)
    missing_required = sorted(required - resources.keys())
    if missing_required:
        joined = "、".join(str(year) for year in missing_required)
        raise CalendarSyncError(f"官方尚未提供必要年度：{joined}。")

    parsed_years = {
        year: _parse_calendar(read(resource.url), year)
        for year, resource in resources.items()
    }
    summary = {
        "years": sorted(parsed_years),
        "skipped_years": sorted(set(normalized_years) - resources.keys()),
        "created": 0,
        "updated": 0,
        "deactivated": 0,
    }

    with transaction.atomic():
        for year, holidays in parsed_years.items():
            official_rows = BusinessHoliday.objects.filter(
                date__year=year,
                source=BusinessHoliday.Source.DGPA,
            )
            stale_rows = official_rows.exclude(date__in=holidays)
            summary["deactivated"] += stale_rows.filter(active=True).count()
            stale_rows.update(active=False)

            for day, name in holidays.items():
                holiday, created = BusinessHoliday.objects.get_or_create(
                    date=day,
                    defaults={
                        "name": name,
                        "active": True,
                        "source": BusinessHoliday.Source.DGPA,
                    },
                )
                if created:
                    summary["created"] += 1
                    continue
                holiday.name = name
                holiday.source = BusinessHoliday.Source.DGPA
                # active 是人工可調整的例外開關；同步時不覆寫人員決定。
                holiday.save(update_fields=["name", "source", "updated_at"])
                summary["updated"] += 1

    return summary
