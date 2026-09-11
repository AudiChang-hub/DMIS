from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.test import Client, TestCase
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from sales.tests import test_reporting as fixtures
from sales.models import SalesOrder, VehicleModel, ReportClassification, ReportClassificationRevision
from sales.reporting.classification import (apply_change, classification_expression, impact, initial_snapshot,
    inventory, preview_token, published_snapshot, validate_snapshot, unclassified, ClassificationSnapshotMiddleware)
from sales.reporting.engine import card_result, drill_query, dimension_color
from sales.reporting.views import publication_key


class ReportClassificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.url = reverse('report_classification')
        self.client.force_login(self.admin)

    def state(self):
        return ReportClassification.objects.get(pk=1)

    def change(self, action, data):
        return apply_change(self.state().version, action, data, self.admin)

    def publish(self):
        state = self.state()
        return self.change('publish', {'token':preview_token(state, self.admin, impact(state.published, state.draft))})

    def test_seed_equivalence_and_idempotency(self):
        self.assertEqual(self.state().published, initial_snapshot())
        before = list(ReportClassificationRevision.objects.values())
        import_module('sales.migrations.0125_seed_report_classification').seed(apps, SimpleNamespace(connection=connection))
        self.assertEqual(list(ReportClassificationRevision.objects.values()), before)
        card = {**self.config['cards'][0], 'dimension':'legacy_motor_type'}
        for text, expected in [('UQ125DA','速克達'),('UT125XZ','速克達'),('DS250M4','擋車'),('GSX-R150','擋車'),
                               ('EV062','白牌電車'),('EV062FL','其他'),('Pulse Ultra','其他'),('uq125','其他'),('UQ\n','其他')]:
            VehicleModel.objects.all().update(model_number=text)
            result = card_result(self.config, card, {})
            self.assertEqual([(r['label'],r['count']) for r in result['rows']], [(expected,3)])
            self.assertEqual(drill_query(self.config, card, {}, 'v:'+expected).count(), 3)

    def test_draft_publish_rename_color_and_rollback(self):
        VehicleModel.objects.all().update(model_number='UQ125DA')
        before_orders = list(SalesOrder.objects.values())
        original = self.state().published
        key = publication_key(self.report)
        self.change('category', {**original['categories'][3], 'name':'一般速克達', 'color':'#123456'})
        self.assertEqual(published_snapshot()[0], original)
        state = self.state(); result = impact(state.published, state.draft)
        self.assertEqual(result['total'],3)
        self.assertEqual(result['rows'][0]['after'],'一般速克達')
        self.publish()
        self.assertNotEqual(publication_key(self.report), key)
        self.assertEqual(dimension_color('legacy_motor_type','一般速克達',0),'#123456')
        from django.template.loader import render_to_string
        card = {**self.config['cards'][0], 'dimension':'legacy_motor_type', 'chart':'bar'}
        result = card_result(self.config, card, {})
        rendered = render_to_string('sales/reporting/result.html', {'result':result, 'is_preview':True})
        self.assertIn(';background:#123456', rendered)
        self.assertEqual(list(inventory().annotate(c=classification_expression()).values_list('c',flat=True)), ['一般速克達']*3)
        self.change('restore', {'revision':1})
        self.assertEqual(published_snapshot()[0]['categories'][3]['name'],'一般速克達')
        self.publish()
        self.assertEqual(published_snapshot()[0], original)
        self.assertEqual(list(SalesOrder.objects.values()), before_orders)

    def test_conflicts_and_exact_override(self):
        self.change('rule', {'match':'prefix','text':'NEW','category':'category-3','enabled':True})
        with self.assertRaisesMessage(ValidationError,'重疊'):
            self.change('rule', {'match':'prefix','text':'NEW-X','category':'category-4','enabled':True})
        self.change('rule', {'match':'exact','text':'NEW-X','category':'category-4','enabled':True})
        VehicleModel.objects.all().update(model_number='NEW-X')
        self.assertEqual(list(inventory().annotate(c=classification_expression(self.state().draft)).values_list('c',flat=True)), ['擋車']*3)

    def test_reserved_duplicate_and_malformed_categories(self):
        for change in ({'enabled':False}, {'name':'未知'}):
            with self.assertRaises(ValidationError):
                self.change('category', {**self.state().draft['categories'][-1], **change})
        for name, color in [('速克達','#123456'),('新類別','red'),('新類別','</style>')]:
            with self.assertRaises(ValidationError):
                self.change('category', dict(name=name, color=color, order=10, enabled=True))
        bad = initial_snapshot(); bad['rules'][0]['match'] = []
        with self.assertRaises(ValidationError): validate_snapshot(bad)

    def test_delete_used_category(self):
        for key in ('category-3','other'):
            with self.assertRaises(ValidationError): self.change('delete_category', {'id':key})
        self.change('category', dict(name='暫存類別',color='#123456',order=20,enabled=True))
        new = self.state().draft['categories'][-1]['id']
        self.change('delete_category', {'id':new})
        self.assertNotIn(new, [c['id'] for c in self.state().draft['categories']])
        for rule in self.state().draft['rules']:
            if rule['category'] == 'category-3': self.change('delete_rule', {'id':rule['id']})
        with self.assertRaises(ValidationError): self.change('delete_category', {'id':'category-3'})

    def test_disabled_category_and_batch_assignment(self):
        VehicleModel.objects.all().update(model_number='UQ125DA')
        self.change('category', {**self.state().draft['categories'][3], 'enabled':False})
        self.assertEqual(list(unclassified(self.state().draft))[0]['count'],3)
        self.change('batch', {'models':['UQ125DA'], 'category':'category-4'})
        self.assertFalse(unclassified(self.state().draft).exists())
        self.assertEqual(impact(self.state().published,self.state().draft)['total'],3)
        self.change('batch', {'models':['UQ125DA'], 'category':'category-3'})
        self.assertEqual(sum(r['text']=='UQ125DA' for r in self.state().draft['rules']),1)

    def test_stale_edit_preview_signature_user_and_data(self):
        old_version = self.state().version
        self.change('rule', dict(match='prefix',text='UNIQUE',category='category-3',enabled=True))
        with self.assertRaisesMessage(ValidationError,'版本已變更'):
            apply_change(old_version, 'delete_rule', {'id':'rule-0'}, self.admin)
        state = self.state(); token = preview_token(state, self.admin, impact(state.published,state.draft))
        VehicleModel.objects.all().update(model_number='UNIQUE125')
        before = self.state().version
        with self.assertRaisesMessage(ValidationError,'重新試算'): self.change('publish', {'token':token})
        with self.assertRaises(ValidationError): self.change('publish', {'token':'tampered'})
        self.assertEqual(self.state().version,before)
        token = preview_token(state, self.other_admin, impact(state.published,state.draft))
        with self.assertRaises(ValidationError): self.change('publish', {'token':token})

    def test_request_snapshot_resets(self):
        old = published_snapshot()
        def response(request):
            self.assertEqual(published_snapshot(),old)
            ReportClassification.objects.filter(pk=1).update(published_version=88)
            self.assertEqual(published_snapshot(),old)
            return 'done'
        self.assertEqual(ClassificationSnapshotMiddleware(response)(None),'done')
        self.assertEqual(published_snapshot()[1],88)

    def test_access_csrf_and_http_workflow(self):
        self.assertContains(self.client.get(self.url), '報表分類設定')
        self.assertContains(self.client.get(self.url), 'id_category-enabled')
        self.assertContains(self.client.get(self.url), 'id_rule-enabled')
        client = Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(self.url, {'action':'preview','version':1}).status_code,403)
        for user in (self.user,self.other_admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code,403)
            self.assertEqual(self.client.post(self.url, {'action':'preview','version':1}).status_code,403)
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'action':'category','version':1,'category-name':'測試類別','category-color':'#123456','category-order':20,'category-enabled':'on'})
        self.assertEqual(response.status_code,302)
        response = self.client.post(self.url, {'action':'preview','version':self.state().version})
        self.assertContains(response,'確認並發布分類')
        token = response.context['publish_token']
        self.assertEqual(self.client.post(self.url, {'action':'publish','version':self.state().version,'token':token}).status_code,400)
        self.assertEqual(self.client.post(self.url, {'action':'publish','version':self.state().version,'token':token,'confirm':'yes'}).status_code,302)
        self.assertEqual(self.state().published['categories'][-1]['name'],'測試類別')

    def test_database_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic(): ReportClassification.objects.create(pk=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportClassificationRevision.objects.create(classification=self.state(),version=1,action='initial',snapshot={})


class ClassificationConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_editors_cannot_overwrite_each_other(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.contrib.auth import get_user_model
        from django.db import close_old_connections
        user = get_user_model().objects.create_superuser('admin','test@example.invalid','Test-Only-123')
        ReportClassification.objects.update_or_create(pk=1, defaults={'version':1,'published_version':1,'draft':initial_snapshot(),'published':initial_snapshot()})
        barrier = Barrier(2)
        def edit(name):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                apply_change(1,'category',dict(name=name,color='#123456',order=20,enabled=True),user)
                return 'saved'
            except ValidationError:
                return 'stale'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit,['編輯甲','編輯乙']))
        self.assertCountEqual(results,['saved','stale'])
        self.assertEqual(ReportClassification.objects.get(pk=1).version,2)
