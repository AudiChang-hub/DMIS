from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase
from openpyxl import Workbook

from sales.models import SalesSource, SalesSourceBrandPolicy, SalesSourceCooperationProfile
from sales.services.dealer_workbook_sync import sync_dealer_workbook


class DealerWorkbookSyncTests(TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.workbook_path = Path(self.tempdir.name) / "車行、網路平台.xlsx"

    def tearDown(self):
        self.tempdir.cleanup()

    def write_workbook(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "車行"
        sheet.append(["月餅", "LINE群組", "", "", "", "", "", "", "", "價格表", "", "排車容量", "", ""])
        sheet.append(["", "", "店名", "負責人", "電話一", "電話二", "手機", "手機/傳真", "地址", "三陽", "台鈴", "三陽", "台鈴", "備註"])
        sheet.append(["V", "S", "油電車行", "王先生", "02-1111", "", "0911", "傳真一", "新北市汐止區", "專銷", "V", 2, 3, "Excel 備註"])
        sheet.append(["", "E", "電車車行", "李小姐", "02-2222", "", "0922", "", "基隆市仁愛區", "", "電動車", "", 4, ""])
        sheet.append(["", "", "東湖上慶", "陳先生", "02-3333", "", "", "", "臺北市內湖區", "", "", "", "", "別名備註"])
        workbook.save(self.workbook_path)

    def test_dry_run_rolls_back_all_changes(self):
        self.write_workbook()
        result = sync_dealer_workbook(self.workbook_path, apply=False)
        self.assertEqual(result.created, 3)
        self.assertFalse(SalesSource.objects.exists())

    def test_sync_maps_suzuki_v_to_gas_and_electric_and_electric_only(self):
        self.write_workbook()
        preserved = SalesSource.objects.create(
            source_type=SalesSource.SourceType.DEALER,
            name="系統限定車行",
            note="保留",
        )
        alias_target = SalesSource.objects.create(
            source_type=SalesSource.SourceType.DEALER,
            name="上慶",
            note="舊備註",
        )

        result = sync_dealer_workbook(self.workbook_path, apply=True)

        self.assertEqual(result.source_rows, 3)
        self.assertEqual(result.created, 2)
        self.assertEqual(result.aliases_used, 1)
        self.assertEqual(result.database_only, 1)
        self.assertTrue(SalesSource.objects.filter(pk=preserved.pk).exists())

        oil_and_electric = SalesSource.objects.get(name="油電車行")
        profiles = {
            item.cooperation_scope: item
            for item in oil_and_electric.cooperation_profiles.all()
        }
        self.assertTrue(profiles[SalesSourceBrandPolicy.CooperationScope.SYM].cooperates)
        self.assertEqual(
            profiles[SalesSourceBrandPolicy.CooperationScope.SYM].relationship_type,
            SalesSourceCooperationProfile.RelationshipType.EXCLUSIVE,
        )
        self.assertTrue(profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS].cooperates)
        self.assertTrue(profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC].cooperates)
        policies = {
            item.cooperation_scope: item
            for item in oil_and_electric.brand_policies.all()
        }
        self.assertTrue(policies[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS].cooperates)
        self.assertTrue(policies[SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC].cooperates)
        self.assertEqual(profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS].vehicle_capacity, 3)
        self.assertEqual(oil_and_electric.note, "Excel 備註")
        self.assertTrue(oil_and_electric.holiday_gift)
        self.assertTrue(oil_and_electric.has_line_group)

        electric_only = SalesSource.objects.get(name="電車車行")
        electric_profiles = {
            item.cooperation_scope: item
            for item in electric_only.cooperation_profiles.all()
        }
        self.assertFalse(electric_profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS].cooperates)
        self.assertTrue(electric_profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC].cooperates)
        electric_policies = {
            item.cooperation_scope: item
            for item in electric_only.brand_policies.all()
        }
        self.assertFalse(electric_policies[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS].cooperates)
        self.assertTrue(electric_policies[SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC].cooperates)
        self.assertEqual(electric_only.note, "")

        alias_target.refresh_from_db()
        self.assertEqual(alias_target.responsible_person, "陳先生")
        self.assertEqual(alias_target.note, "別名備註")
        self.assertFalse(SalesSource.objects.filter(name="東湖上慶").exists())
