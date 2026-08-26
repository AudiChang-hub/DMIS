from datetime import date

from django.test import TestCase

from sales.models import (
    BusinessHoliday,
    DealerVolumeBonusRule,
    SalesSource,
    SalesSourceCategory,
    SalesSourceBrandPolicy,
    VehicleModel,
    VehiclePriceVersion,
)
from sales.services.odoo_master_import import import_odoo_master_data


class OdooMasterImportTests(TestCase):
    def payload(self):
        return {
            "schema_version": 1,
            "dealers": [
                {
                    "id": 10,
                    "name": "測試車行",
                    "code": "D010",
                    "store_type_name": "專賣",
                    "owner_name": "王老闆",
                    "store_manager": "李窗口",
                    "phone_1": "02-12345678",
                    "mobile": "0912345678",
                    "address": "新北市測試路 1 號",
                    "line_group": True,
                    "holiday_gift": True,
                    "active": True,
                }
            ],
            "dealer_brand_auth": [
                {
                    "id": 20,
                    "dealer_id": 10,
                    "brand_id": 1,
                    "brand_name": "台鈴 Suzuki",
                    "auth_type": "authorized",
                    "create_date": "2026-01-01T00:00:00",
                }
            ],
            "legacy_dealer_brands": [],
            "products": [
                {
                    "id": 30,
                    "brand_name": "台鈴 Suzuki",
                    "name": "SUI 125 七期",
                    "model": "UQ125DA",
                    "production_year": 2026,
                    "brake_type": "前碟後鼓",
                    "energy_type": "oil",
                    "resolved_engine_displacement": "124.0",
                    "suggested_price": "77000",
                    "cash_price": "70000",
                    "active": True,
                    "create_date": "2026-01-01T00:00:00",
                }
            ],
            "product_colors": [
                {"id": 31, "product_id": 30, "name": "灰", "active": True}
            ],
            "price_versions": [],
            "product_commissions": [
                {"id": 32, "base_amount": "2000", "product_ids": [30]}
            ],
            "dealer_commission_rules": [
                {
                    "id": 40,
                    "brand_name": "台鈴 Suzuki",
                    "create_date": "2026-01-01T00:00:00",
                    "addon_amount": "500",
                    "dealer_ids": [10],
                    "name": "特別加碼",
                }
            ],
            "volume_rules": [
                {
                    "id": 50,
                    "brand_name": "台鈴 Suzuki",
                    "rule_type": "specific",
                    "dealer_ids": [10],
                    "date_from": "2026-01-01",
                    "date_to": "2026-12-31",
                    "min_qty": 10,
                    "bonus_per_unit": "500",
                    "active": True,
                }
            ],
            "holidays": [
                {"id": 60, "date": "2026-02-16", "name": "春節", "note": "除夕"}
            ],
            "installment_lines": [{"id": 70}],
            "legacy_only_counts": {
                "dms_sale_order": 1614,
                "dms_incentive_rule": 1,
                "dms_commission_volume_gift": 1,
            },
        }

    def test_dry_run_does_not_write(self):
        summary = import_odoo_master_data(self.payload(), apply=False)

        self.assertEqual(summary["sources_create"], 1)
        self.assertEqual(summary["models_create"], 1)
        self.assertEqual(summary["legacy_transactions_not_imported"], 1614)
        self.assertEqual(SalesSource.objects.count(), 0)
        self.assertEqual(VehicleModel.objects.count(), 0)

    def test_apply_is_idempotent_and_imports_business_rules(self):
        first = import_odoo_master_data(self.payload(), apply=True)
        second = import_odoo_master_data(self.payload(), apply=True)

        source = SalesSource.objects.get(code="D010")
        model = VehicleModel.objects.get(model_number="UQ125DA")
        policy = SalesSourceBrandPolicy.objects.get(
            source=source, brand="SUZUKI", effective_from=date(2026, 1, 1)
        )
        self.assertEqual(source.contacts.count(), 2)
        self.assertTrue(source.holiday_gift)
        self.assertEqual(source.relationship_note, "已加入 LINE 群組")
        self.assertEqual(source.note, "")
        self.assertFalse(source.contacts.exclude(note="").exists())
        self.assertEqual(policy.commission_adjustment, 500)
        self.assertEqual(policy.note, "特別加碼")
        self.assertEqual(model.displacement_cc, 124)
        self.assertEqual(model.base_dealer_commission, 2000)
        self.assertEqual(model.colors.get().name, "灰")
        self.assertEqual(
            VehiclePriceVersion.objects.get().suggested_price,
            77000,
        )
        self.assertEqual(
            VehiclePriceVersion.objects.get().source_note,
            "歷史價格資料匯入",
        )
        self.assertEqual(DealerVolumeBonusRule.objects.count(), 1)
        self.assertNotIn(
            "遷移 ID:",
            DealerVolumeBonusRule.objects.get().note,
        )
        self.assertEqual(
            BusinessHoliday.objects.get(date=date(2026, 2, 16)).name,
            "春節（除夕）",
        )
        self.assertEqual(first["installment_lines_review_required"], 1)
        self.assertEqual(second["sources_update"], 1)
        self.assertEqual(SalesSource.objects.count(), 1)
        self.assertEqual(VehicleModel.objects.count(), 1)

    def test_import_preserves_real_note_and_removes_legacy_marker(self):
        payload = self.payload()
        payload["dealers"][0]["note"] = "[Odoo 遷移 ID:10]\n請先電話聯絡"

        import_odoo_master_data(payload, apply=True)

        source = SalesSource.objects.get(code="D010")
        self.assertEqual(source.note, "請先電話聯絡")
        self.assertNotIn("遷移 ID:", source.note)

    def test_price_import_preserves_human_source_note_without_system_marker(self):
        payload = self.payload()
        payload["price_versions"] = [
            {
                "product_id": 30,
                "version_id": 88,
                "version_name": "2026 年八月",
                "effective_date": "2026-08-01",
                "cash_price": "70000",
                "list_price": "77000",
                "line_note": "八月營業通報",
            }
        ]

        import_odoo_master_data(payload, apply=True)

        self.assertEqual(
            VehiclePriceVersion.objects.get().source_note,
            "八月營業通報",
        )

    def test_staff_source_is_imported_as_store_category(self):
        payload = self.payload()
        payload["dealers"] = [
            {
                "id": 99,
                "name": "文傑",
                "code": "STAFF-01",
                "store_type_name": "店內員工",
                "active": True,
            }
        ]
        payload["dealer_brand_auth"] = []
        payload["dealer_commission_rules"] = []
        payload["volume_rules"] = []

        import_odoo_master_data(payload, apply=True)

        source = SalesSource.objects.get(code="STAFF-01")
        self.assertEqual(source.source_type, SalesSource.SourceType.STORE)
        self.assertEqual(source.category.name, "店內員工")
        self.assertEqual(
            source.category.system_behavior,
            SalesSourceCategory.SystemBehavior.STORE,
        )
