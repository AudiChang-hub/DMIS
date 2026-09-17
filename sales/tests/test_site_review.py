from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import DiscountRequestForm, AccessoryLineForm
from sales.models import SystemAnnouncement, GiftDistribution, GiftDistributionItem, GiftDistributionEvent, SiteTextRevision, OrderDraft, AccessoryProduct, SalesOrder
from sales.services.site_copy import catalog
from sales.tests import test_order_intake as fixtures


class SiteReviewTests(TestCase):
    setUp = fixtures.OrderIntakeTests.setUp
    image = fixtures.OrderIntakeTests.image
    complete_data = fixtures.OrderIntakeTests.complete_data

    def test_all_templates_compile(self):
        for path in (settings.BASE_DIR / "templates").rglob("*.html"):
            with self.subTest(template=str(path)):
                get_template(path.relative_to(settings.BASE_DIR / "templates").as_posix())

    def test_announcement_audience_detail_and_expiry(self):
        item = SystemAnnouncement.objects.create(title="指定公告", body="https://example.com/ <script>alert(1)</script>", published=True, audience="selected")
        item.recipients.add(self.dealer_user)
        url = reverse("announcement_detail", args=[item.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.dealer_user)
        response = self.client.get(url)
        self.assertContains(response, 'href="https://example.com/"')
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(self.client.get(reverse("dashboard")), "指定公告")
        item.ends_at = timezone.now() - timedelta(seconds=1)
        item.starts_at = item.ends_at - timedelta(days=1)
        item.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.root)
        self.assertContains(self.client.get(reverse("dashboard")), "1 則公告已到期")

    def test_announcement_history_and_delete_require_admin_confirmation(self):
        item = SystemAnnouncement.objects.create(title="舊公告", body="歷史", published=True, starts_at=timezone.now()-timedelta(days=2), ends_at=timezone.now()-timedelta(days=1))
        url = reverse("announcement_action", args=[item.pk])
        self.assertEqual(self.client.post(url, {"action":"delete", "confirm":"yes", "expected_version":1}).status_code, 403)
        self.client.force_login(self.root)
        self.assertNotContains(self.client.get(reverse("announcement_manage")), "舊公告")
        self.assertContains(self.client.get(reverse("announcement_manage"), {"history":1}), "舊公告")
        self.client.post(url, {"action":"delete", "expected_version":1})
        item.refresh_from_db(); self.assertIsNone(item.deleted_at)
        self.assertEqual(self.client.post(url, {"action":"delete", "confirm":"yes", "expected_version":1}).status_code, 302)
        item.refresh_from_db(); self.assertIsNotNone(item.deleted_at)
        self.assertEqual(item.revisions.count(), 1)

    def test_home_news_pages_and_compact_versions(self):
        SystemAnnouncement.objects.bulk_create([SystemAnnouncement(title=f"公告{i}", body="內容", published=True) for i in range(12)])
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(len(response.context['page_obj']), 10)
        versions = self.client.get(reverse("dashboard"), {"news":"releases"})
        self.assertLessEqual(len(versions.context['release_history']), 2)
        self.assertContains(versions, "查看完整版本歷程")
        self.assertNotContains(versions, '<summary>技術資訊</summary>')
        self.assertEqual(self.client.get(reverse("release_history")).status_code, 200)

    def test_site_copy_admin_escape_restore_and_conflict(self):
        key = next(key for key in catalog() if key.startswith("dashboard.") and "版本更新" in catalog()[key]['default'])
        url = reverse("site_copy_manage") + "?key=" + key
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(url, {"version":0, "text":"<script>測試</script>", "action":"save"}).status_code, 302)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "&lt;script&gt;測試&lt;/script&gt;")
        self.assertNotContains(response, "<script>測試</script>")
        self.assertEqual(self.client.post(url, {"version":0,"text":"舊視窗"}).status_code, 409)
        self.assertEqual(self.client.post(url, {"version":1,"text":"placeholder","action":"reset"}).status_code, 302)
        self.assertEqual(SiteTextRevision.objects.filter(key=key).count(), 2)

    def test_gift_list_is_manual_scoped_and_audited(self):
        url = reverse("gift_distribution")
        self.client.force_login(self.dealer_user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(url, {"title":"中秋", "action":"add"}).status_code, 302)
        activity = GiftDistribution.objects.get()
        self.assertEqual(activity.items.count(), 0)
        detail = reverse("gift_distribution_detail", args=[activity.pk])
        self.assertEqual(self.client.post(detail, {"action":"add_sources", "sources":[self.dealer.pk]}).status_code, 302)
        item = activity.items.get()
        self.assertEqual(self.client.get(detail).status_code, 200)
        update = reverse("gift_distribution_update", args=[item.pk])
        self.client.post(update, {"action":"complete","version":1})
        item.refresh_from_db(); self.assertTrue(item.completed)
        self.assertEqual(item.completed_by, "admin")
        self.client.post(update, {"action":"reopen","version":1})
        item.refresh_from_db(); self.assertTrue(item.completed)
        self.client.post(update, {"action":"reopen","version":2})
        item.refresh_from_db(); self.assertFalse(item.completed)
        self.assertEqual(GiftDistributionEvent.objects.filter(distribution=activity).count(), 4)
        original_created_at = item.created_at
        self.client.post(update, {"action":"remove", "version":3})
        self.assertEqual(self.client.post(detail, {"action":"add", "recipient":item.recipient, "gift":"更換禮盒"}).status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.removed)
        self.assertEqual(item.created_at, original_created_at)
        self.assertEqual(item.gift, "更換禮盒")
        self.assertEqual(activity.items.count(), 1)
        self.client.post(detail, {"action":"archive","confirm":"yes"})
        self.client.post(update, {"action":"complete","version":5})
        item.refresh_from_db(); self.assertFalse(item.completed)
        from sales.access.models import UserAccessState, ScreenAccessGrant
        UserAccessState.objects.update_or_create(user=self.user, defaults={"configured":True})
        ScreenAccessGrant.objects.update_or_create(user=self.user, screen_key="gift_distribution", defaults={"view":True,"operate":False})
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.post(url, {"action":"add", "title":"不得建立"}).status_code, 403)
        self.assertEqual(self.client.post(update, {"action":"complete","version":5}).status_code, 403)

    def test_custom_total_discount_modes(self):
        rate = DiscountRequestForm({"mode":"rate", "rate":"9.25", "reason":"優惠"}, total=Decimal("10001"))
        self.assertTrue(rate.is_valid(), rate.errors)
        self.assertEqual(rate.cleaned_data['amount'], 750)
        amount = DiscountRequestForm({"mode":"amount", "amount":"1234", "reason":"抹零"}, total=Decimal("10001"))
        self.assertTrue(amount.is_valid(), amount.errors)
        for data in ({"mode":"amount","amount":"10002"}, {"mode":"rate","rate":"11"}):
            self.assertFalse(DiscountRequestForm({**data,"reason":"測試"}, total=Decimal("10001")).is_valid())

    def test_draft_status_search_returns_orderdraft_rows(self):
        draft = OrderDraft.objects.create(owner_account=self.user, data={"owner_name":"草稿車主", "vehicle_model":str(self.model.pk)})
        response = self.client.get(reverse("order_list"), {"status":"draft","q":"草稿車主"})
        self.assertContains(response, "草稿車主")
        self.assertEqual(response.context['draft_count'], 1)
        self.assertContains(response, f"?draft={draft.pk}")

    def test_reception_accessories_are_saved_at_server_prices(self):
        product = AccessoryProduct.objects.create(name="手機架", sale_price=1200, labor_fee=100)
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update({"accessories-TOTAL_FORMS":"1", "accessories-INITIAL_FORMS":"0", "accessories-0-accessory_product":str(product.pk), "accessories-0-quantity":"2", "accessories-0-line_type":"purchase", "accessories-0-amount":"1", "accessories-0-labor_fee":"1"})
        response = self.client.post(reverse("order_start"), data)
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        line = SalesOrder.objects.get().accessories.get()
        self.assertEqual((line.amount, line.labor_fee, line.quantity), (1200,100,2))

    def test_manual_accessory_requires_reason_and_preserves_entered_price(self):
        product = AccessoryProduct.objects.create(name="後架", sale_price=1200, labor_fee=100)
        data = {"accessory_product":product.pk,"quantity":1,"line_type":"purchase","amount":900,"labor_fee":50}
        form = AccessoryLineForm(data, allow_manual=True)
        self.assertFalse(form.is_valid())
        form = AccessoryLineForm({**data,"note":"活動優惠"}, allow_manual=True)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['amount'], 900)

    def test_release_publication_is_idempotent(self):
        from django.core.management import call_command
        from sales.models import ReleasePublication
        from config.release_notes import CURRENT_VERSION
        call_command("record_release", verbosity=0)
        original = ReleasePublication.objects.get(version=CURRENT_VERSION).published_at
        call_command("record_release", verbosity=0)
        self.assertEqual(ReleasePublication.objects.count(), 1)
        self.assertEqual(ReleasePublication.objects.get().published_at, original)
        self.assertContains(self.client.get(reverse('dashboard'), {'news':'releases'}), '（台北）')

    def test_reception_cannot_select_gift_or_override_registration(self):
        from sales.intake_forms import IntakeOrderForm
        form = IntakeOrderForm(user=self.root, reception=True)
        self.assertTrue(form.fields['registration_manual'].disabled)
        self.assertEqual(list(AccessoryLineForm(purchase_only=True).fields['line_type'].choices), [('purchase', '加購')])

    def test_print_copy_length_and_injection_guard(self):
        self.client.force_login(self.root)
        url = reverse('site_copy_manage') + '?key=print.contract.confirmation'
        response = self.client.post(url, {'text':'文'*91, 'version':0})
        self.assertContains(response, '最多 90 字')
        response = self.client.post(url, {'text':'<b>自訂確認文字</b>', 'version':0})
        self.assertEqual(response.status_code, 302)

    def test_manual_registration_amount_requires_reason_and_is_preserved(self):
        from sales.intake_forms import IntakeOrderForm
        from sales.forms import RegistrationStageForm
        data = self.complete_data()
        data.update(registration_manual='on', registration_plate_fee='999', compulsory_insurance_fee='1234')
        files = {'id_front':self.image('front.png'), 'id_back':self.image('back.png')}
        form = IntakeOrderForm(data, files, user=self.root)
        self.assertFalse(form.is_valid())
        self.assertIn('registration_adjustment_reason', form.errors)
        data['registration_adjustment_reason'] = '依實際單據核定'
        form = IntakeOrderForm(data, files, user=self.root)
        self.assertTrue(form.is_valid(), form.errors)
        order = form.save(commit=False)
        order.actual_balance = order.calculate_balance()
        order.save()
        self.assertEqual(order.plate_insurance_fee, 2233)
        operation = RegistrationStageForm(instance=order)
        operation.cleaned_data = {}
        saved = operation.save(commit=False)
        self.assertEqual(saved.registration_plate_fee, 999)
        from types import SimpleNamespace
        order.registration_date = timezone.localdate()
        operation._registration_result = SimpleNamespace(rate_class='qa', fixed_and_variable_total=Decimal('3000'))
        saved = operation.save(commit=False)
        self.assertEqual(saved.registration_calculated_total, 3000)
        self.assertEqual(saved.plate_insurance_fee, 2233)


class DiscountInvariantTests(TestCase):
    from sales.tests.test_order_flow import OrderOperationsTests as _fixtures
    setUp = _fixtures.setUp

    def test_approval_changes_receivable_not_payout_commission_or_cost(self):
        self.order.payment_type = 'installment'
        self.order.installment_amount = 80000
        self.order.installment_company = '測試分期'
        self.order.installment_periods = 24
        self.order.save()
        profile = self.order.operations
        profile.actual_disbursement = Decimal('72000')
        profile.vehicle_cost = Decimal('60000')
        profile.save()
        before = {f.name: getattr(profile, f.name) for f in profile._meta.concrete_fields if any(w in f.name for w in ('commission','cost','disbursement'))}
        request_url = reverse('order_discount_request', args=[self.order.pk])
        decision_url = reverse('order_discount_decide', args=[self.order.pk])
        self.assertEqual(self.client.post(request_url, {'mode':'rate','rate':'9.25','reason':'客戶優惠'}).status_code, 302)
        self.assertEqual(self.client.post(decision_url, {'decision':'approve'}).status_code, 302)
        self.order.refresh_from_db(); profile.refresh_from_db()
        self.assertEqual(self.order.approved_discount_amount, 6000)
        self.assertEqual(self.order.discounted_total, 74000)
        self.assertEqual(self.order.actual_balance, 69000)
        self.assertEqual(before, {key:getattr(profile,key) for key in before})
        self.client.post(request_url, {'mode':'amount','amount':'1234','reason':'改採減少總價'})
        self.client.post(decision_url, {'decision':'approve'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.approved_discount_amount, 1234)
        self.assertEqual(self.order.discounted_total, 78766)

    def test_changed_total_requires_new_discount_request(self):
        self.client.post(reverse('order_discount_request', args=[self.order.pk]), {'mode':'rate','rate':'9','reason':'測試'})
        self.order.refresh_from_db()
        self.order.vehicle_price = 81000
        self.order.actual_balance = 76000
        self.order.save()
        self.client.post(reverse('order_discount_decide', args=[self.order.pk]), {'decision':'approve'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.discount_status, 'pending')
        self.assertEqual(self.order.approved_discount_amount, 0)
