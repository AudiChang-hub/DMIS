import copy
from django.test import TestCase
from django.urls import reverse
from sales.tests import test_reporting as fixtures
from sales.models import SalesOrder, LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot
from sales.reporting.forms import FilterForm
from sales.reporting.records import record_cells, record_context, record_queryset, visible_record_columns


class ReportReaderCleanupTests(TestCase):
    login = fixtures.ReportingTests.login

    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def test_reader_removes_duplicate_filters_but_keeps_fixed_scope(self):
        from sales.reporting.engine import base_query
        config = {**self.config, 'reader_layout':'sales_overview', 'fixed_filters':{'legacy_energy':['電車']}}
        form = FilterForm({'source':['99999'], 'legacy_energy':['油車']}, config=config)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('source', form.fields)
        self.assertNotIn('legacy_energy', form.fields)
        self.assertEqual(form.fields['legacy_dealer'].label, '車行／平台')
        self.assertEqual(base_query(config, form.cleaned_data).count(), base_query(config, {}).count())
        self.assertIn('source', FilterForm().fields)

    def test_dealer_blank_labels_payment_and_sort(self):
        batch = LegacyImportBatch.objects.create(import_type='operations', source_file='test.xlsx', original_filename='test.xlsx', file_sha256='c'*64, file_size=0, uploaded_by='tester')
        orders = list(SalesOrder.objects.all()[:3])
        for index, (order, name) in enumerate(zip(orders, ['   ', None, '阿明'])):
            row = LegacyImportRow.objects.create(batch=batch, sheet_name='測試', source_row=index+1, fingerprint=str(index)*64, action='create', mapped_data={'dealer_name_raw':name})
            LegacySalesSnapshot.objects.create(order=order, import_row=row)
        config = {**self.config, 'reader_layout':'sales_overview', 'records_columns':['legacy_source_name','energy','payment_confirmed','historical_received_price','total_received']}
        rows = record_context(config, {})
        self.assertEqual(rows['records_headers'], ['售出車行','能源別','收款確認','收款價'])
        sorted_orders = list(record_queryset(config, {'records_sort':'legacy_source_name'}))
        names = [record_cells(order, ['legacy_source_name'])[0]['value'] for order in sorted_orders]
        self.assertEqual(names, ['阿明','馭盛','馭盛'])
        self.assertEqual(visible_record_columns({**config, 'reader_layout':'standard'})[-1], 'total_received')
        order = sorted_orders[0]
        if getattr(order, 'operations', None):
            order.operations.payment_confirmed = True
            self.assertEqual(record_cells(order, ['payment_confirmed'])[0]['value'], '已收款')
            order.operations.payment_confirmed = False
            self.assertEqual(record_cells(order, ['payment_confirmed'])[0]['value'], '未收款')

    def test_csv_and_reader_share_columns(self):
        self.login()
        config = copy.deepcopy(self.report.published)
        config.update(reader_layout='sales_overview', include_records=True, records_columns=['number','payment_confirmed','energy','total_received'])
        self.report.published = config
        self.report.save(update_fields=['published'])
        response = self.client.get(reverse('report_display', args=[self.report.pk]))
        self.assertContains(response, '收款確認')
        self.assertNotContains(response, 'DMIS 已確認實收')
        response = self.client.get(f'/reports/{self.report.pk}/orders/export/')
        self.assertEqual(response.status_code, 200)
        csv = response.content.decode('utf-8-sig')
        self.assertIn('訂單編號,收款確認,能源別', csv)
        self.assertNotIn('DMIS 已確認實收', csv)
