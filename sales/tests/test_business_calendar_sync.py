import calendar
import csv
import io
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import BusinessHoliday
from sales.services.dgpa_calendar import (
    DATASET_METADATA_URL,
    CalendarSyncError,
    sync_official_business_calendar,
)


def build_calendar_csv(year, holidays):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["西元日期", "星期", "是否放假", "備註"])
    writer.writeheader()
    current = date(year, 1, 1)
    last_day = date(year, 12, 31)
    while current <= last_day:
        writer.writerow(
            {
                "西元日期": current.strftime("%Y%m%d"),
                "星期": str(current.isoweekday()),
                "是否放假": "2" if current in holidays else "0",
                "備註": holidays.get(current, ""),
            }
        )
        current += timedelta(days=1)
    return output.getvalue().encode("utf-8-sig")


def build_metadata(*years):
    return json.dumps(
        {
            "result": {
                "distribution": [
                    {
                        "resourceDescription": (
                            f"{year - 1911}年中華民國政府行政機關辦公日曆表"
                        ),
                        "resourceFormat": "CSV",
                        "resourceDownloadUrl": (
                            f"https://www.dgpa.gov.tw/calendar-{year}.csv"
                        ),
                    }
                    for year in years
                ]
            }
        }
    ).encode()


class BusinessCalendarSyncTests(TestCase):
    def setUp(self):
        BusinessHoliday.objects.all().delete()

    def reader_for(self, years_and_holidays):
        payloads = {
            DATASET_METADATA_URL: build_metadata(*years_and_holidays),
        }
        for year, holidays in years_and_holidays.items():
            payloads[f"https://www.dgpa.gov.tw/calendar-{year}.csv"] = (
                build_calendar_csv(year, holidays)
            )
        return payloads.__getitem__

    def test_sync_validates_then_updates_official_dates_without_overwriting_override(self):
        existing = BusinessHoliday.objects.create(
            date=date(2026, 2, 27),
            name="人工舊名稱",
            active=False,
        )
        stale = BusinessHoliday.objects.create(
            date=date(2026, 4, 3),
            name="已取消的官方假日",
            source=BusinessHoliday.Source.DGPA,
        )
        manual = BusinessHoliday.objects.create(
            date=date(2026, 6, 15),
            name="公司盤點日",
        )
        reader = self.reader_for(
            {
                2026: {
                    date(2026, 2, 27): "和平紀念日補假",
                    date(2026, 9, 25): "中秋節",
                }
            }
        )

        summary = sync_official_business_calendar(years=[2026], reader=reader)

        existing.refresh_from_db()
        stale.refresh_from_db()
        manual.refresh_from_db()
        self.assertEqual(existing.name, "和平紀念日補假")
        self.assertEqual(existing.source, BusinessHoliday.Source.DGPA)
        self.assertFalse(existing.active)
        self.assertFalse(stale.active)
        self.assertEqual(manual.source, BusinessHoliday.Source.MANUAL)
        self.assertTrue(manual.active)
        self.assertTrue(
            BusinessHoliday.objects.filter(
                date=date(2026, 9, 25),
                source=BusinessHoliday.Source.DGPA,
                active=True,
            ).exists()
        )
        self.assertEqual(summary["years"], [2026])
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["deactivated"], 1)

    def test_incomplete_calendar_does_not_change_database(self):
        existing = BusinessHoliday.objects.create(
            date=date(2026, 1, 1),
            name="原有資料",
            source=BusinessHoliday.Source.DGPA,
        )
        incomplete = (
            "西元日期,星期,是否放假,備註\n20260101,4,2,開國紀念日\n"
        ).encode("utf-8-sig")
        payloads = {
            DATASET_METADATA_URL: build_metadata(2026),
            "https://www.dgpa.gov.tw/calendar-2026.csv": incomplete,
        }

        with self.assertRaises(CalendarSyncError):
            sync_official_business_calendar(years=[2026], reader=payloads.__getitem__)

        existing.refresh_from_db()
        self.assertEqual(existing.name, "原有資料")
        self.assertTrue(existing.active)
        self.assertEqual(BusinessHoliday.objects.count(), 1)

    def test_next_year_can_be_missing_when_only_current_year_is_required(self):
        reader = self.reader_for(
            {2026: {date(2026, 1, 1): "開國紀念日"}}
        )

        summary = sync_official_business_calendar(
            years=[2026, 2027],
            required_years=[2026],
            reader=reader,
        )

        self.assertEqual(summary["years"], [2026])
        self.assertEqual(summary["skipped_years"], [2027])

    def test_explicit_missing_year_is_an_error(self):
        payloads = {DATASET_METADATA_URL: build_metadata(2026)}
        with self.assertRaisesMessage(CalendarSyncError, "2027"):
            sync_official_business_calendar(
                years=[2027],
                reader=payloads.__getitem__,
            )

    def test_parser_accepts_leap_year_full_calendar(self):
        reader = self.reader_for(
            {2028: {date(2028, 1, 3): "開國紀念日補假"}}
        )
        summary = sync_official_business_calendar(years=[2028], reader=reader)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(calendar.isleap(2028), True)


class BusinessCalendarPageTests(TestCase):
    def setUp(self):
        BusinessHoliday.objects.all().delete()
        self.user = get_user_model().objects.create_user(
            username="calendar-admin",
            password="test-pass-123",
        )
        self.client.force_login(self.user)

    def test_page_shows_official_source_and_sync_year(self):
        BusinessHoliday.objects.create(
            date=date(2026, 1, 1),
            name="開國紀念日",
            source=BusinessHoliday.Source.DGPA,
        )

        response = self.client.get(reverse("business_holiday_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "人事行政總處同步")
        self.assertContains(response, "每月同步當年與次年行事曆")
        self.assertContains(response, "2026 年")
