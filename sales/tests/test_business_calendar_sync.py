import calendar
import csv
import io
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import BusinessHoliday, UserAppearancePreference
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
    def test_year_has_twelve_months_and_leap_day(self):
        response = self.client.get(reverse("business_holiday_list"), {"view": "year", "month": "2028-02"})
        self.assertContains(response, 'class="holiday-year-month"', count=12)
        february = response.context["year_months"][1]
        self.assertEqual(max(day["number"] for day in february["days"]), 29)
        self.assertContains(response, '?view=month&amp;month=2028-02')

    def test_view_preference_is_remembered_and_isolated_by_account(self):
        url = reverse("business_holiday_list")
        self.client.get(url, {"view": "year"})
        self.assertEqual(self.client.get(url).context["calendar_view"], "year")
        self.assertEqual(UserAppearancePreference.objects.get(user=self.user).calendar_view, "year")
        another = get_user_model().objects.create_user(username="other-calendar-user")
        self.client.force_login(another)
        self.assertEqual(self.client.get(url).context["calendar_view"], "month")

    def test_day_shows_official_record_and_weekend_remains_excluded(self):
        holiday = BusinessHoliday.objects.create(date=date(2026, 9, 26), name="測試假日", source=BusinessHoliday.Source.DGPA, active=False)
        response = self.client.get(reverse("business_holiday_list"), {"view": "day", "day": "2026-09-26"})
        self.assertEqual(response.context["editing"], holiday)
        self.assertTrue(response.context["day_excluded"])
        self.assertContains(response, "未啟用額外排除")
        self.assertContains(response, 'name="selected_date" value="2026-09-26"')

    def test_day_weekday_without_record_prefills_date(self):
        response = self.client.get(reverse("business_holiday_list"), {"view": "day", "day": "2026-09-03"})
        self.assertFalse(response.context["day_excluded"])
        self.assertEqual(response.context["form"].initial["date"], date(2026, 9, 3))

    def test_day_save_and_delete_preserve_selected_date(self):
        url = reverse("business_holiday_list")
        response = self.client.post(url, {"view": "day", "selected_date": "2026-09-30", "month": "2026-09", "date": "2026-10-01", "name": "例外休假", "active": "on"})
        expected = f"{url}?month=2026-10&view=day&day=2026-10-01"
        self.assertRedirects(response, expected)
        holiday = BusinessHoliday.objects.get(date=date(2026, 10, 1))
        response = self.client.post(reverse("business_holiday_delete", args=[holiday.pk]), {"view": "day", "selected_date": "2026-10-01", "month": "2026-10"})
        self.assertRedirects(response, expected)
        self.assertFalse(BusinessHoliday.objects.filter(pk=holiday.pk).exists())

    def test_invalid_view_and_date_fall_back_safely(self):
        response = self.client.get(reverse("business_holiday_list"), {"view": "invalid", "month": "9999-99", "day": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_view"], "month")

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

    def test_page_renders_selected_month_as_calendar_and_limits_list_to_month(self):
        official = BusinessHoliday.objects.create(
            date=date(2026, 9, 25),
            name="中秋節",
            source=BusinessHoliday.Source.DGPA,
        )
        manual = BusinessHoliday.objects.create(
            date=date(2026, 9, 30),
            name="公司盤點日",
            source=BusinessHoliday.Source.MANUAL,
        )
        BusinessHoliday.objects.create(
            date=date(2026, 10, 1),
            name="十月測試日",
        )

        response = self.client.get(
            reverse("business_holiday_list"),
            {"month": "2026-09"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_month"], date(2026, 9, 1))
        self.assertEqual(
            {holiday.pk for holiday in response.context["holidays"]},
            {official.pk, manual.pk},
        )
        self.assertEqual(len(response.context["calendar_weeks"]), 5)
        self.assertContains(response, 'class="holiday-calendar-grid"')
        self.assertContains(response, 'data-holiday-date="2026-09-25"')
        self.assertContains(response, 'data-holiday-source="dgpa"')
        self.assertContains(
            response,
            'aria-label="9 月 25 日，中秋節，排除工作日計算"',
        )
        self.assertContains(response, "本月日期清單")
        self.assertContains(response, "新增日期")

    def test_calendar_post_can_edit_existing_official_date_and_preserves_month(self):
        holiday = BusinessHoliday.objects.create(
            date=date(2026, 9, 25),
            name="原名稱",
            source=BusinessHoliday.Source.DGPA,
        )

        response = self.client.post(
            reverse("business_holiday_list"),
            {
                "holiday_id": holiday.pk,
                "month": "2026-09",
                "date": "2026-09-25",
                "name": "中秋節",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('business_holiday_list')}?month=2026-09",
            fetch_redirect_response=False,
        )
        holiday.refresh_from_db()
        self.assertEqual(holiday.name, "中秋節")
        self.assertEqual(holiday.source, BusinessHoliday.Source.DGPA)
        self.assertFalse(holiday.active)

    def test_delete_returns_to_same_calendar_month(self):
        holiday = BusinessHoliday.objects.create(
            date=date(2026, 9, 30),
            name="公司盤點日",
        )

        response = self.client.post(
            reverse("business_holiday_delete", args=[holiday.pk]),
            {"month": "2026-09"},
        )

        self.assertRedirects(
            response,
            f"{reverse('business_holiday_list')}?month=2026-09",
            fetch_redirect_response=False,
        )
        self.assertFalse(BusinessHoliday.objects.filter(pk=holiday.pk).exists())
