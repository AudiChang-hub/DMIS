from decimal import Decimal
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from sales.access.models import UserAccessState, ScreenAccessGrant
from sales.access.services import AccessPolicy
from sales.announcement_views import AnnouncementForm
from sales.models import SystemAnnouncement, AnnouncementImage, GiftDistribution, SalesOrder, AccessoryProduct, PaymentRecord
from sales.services.site_copy import catalog
from sales.tests import test_order_intake as fixtures


class SiteReviewFollowupTests(TestCase):
    setUp = fixtures.OrderIntakeTests.setUp
    image = fixtures.OrderIntakeTests.image
    complete_data = fixtures.OrderIntakeTests.complete_data

    def grant_pricing(self, user, enabled=True):
        UserAccessState.objects.update_or_create(user=user, defaults={"configured": True})
        ScreenAccessGrant.objects.update_or_create(user=user, screen_key="order_pricing", defaults={"view": enabled, "operate": enabled})

    def submit(self, **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        return self.client.post(reverse("order_start"), data)

    def test_pricing_is_explicit_and_dealer_does_not_gain_finance(self):
        self.assertFalse(AccessPolicy(self.user).screen("order_pricing", "operate"))
        self.grant_pricing(self.dealer_user)
        policy = AccessPolicy(self.dealer_user)
        self.assertTrue(policy.screen("order_pricing", "operate"))
        self.assertFalse(policy.screen("order_finance", "operate"))
        self.assertFalse(policy.screen("profit"))
        self.client.force_login(self.dealer_user)
        response = self.submit(vehicle_price="76000", vehicle_price_adjustment_reason="經授權議價")
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.vehicle_price, 76000)
        self.assertEqual(order.source, self.dealer)
        self.grant_pricing(self.dealer_user, False)
        response = self.submit(vehicle_price="1", vehicle_price_adjustment_reason="不得改價")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SalesOrder.objects.latest('pk').vehicle_price, 79800)

    def test_custom_installment_is_saved_without_wrong_plan_snapshot(self):
        from sales.models import InstallmentCompany, InstallmentPlanVersion, InstallmentPlanOption
        company = InstallmentCompany.objects.create(name="其他融資")
        plan = InstallmentPlanVersion.objects.create(vehicle_model=self.model, effective_from=timezone.localdate())
        InstallmentPlanOption.objects.create(version=plan, company=company, periods=17, monthly_amount=9999, opening_fee=999)
        self.grant_pricing(self.dealer_user)
        self.client.force_login(self.dealer_user)
        response = self.submit(payment_type="installment", installment_custom="on", installment_company="其他融資", installment_periods=17, installment_monthly=5100, installment_opening_fee=350)
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        order = SalesOrder.objects.get()
        self.assertTrue(order.installment_custom)
        self.assertEqual((order.installment_company, order.installment_periods, order.installment_monthly, order.installment_opening_fee), ('其他融資', 17, 5100, 350))
        self.assertIsNone(order.installment_plan_option_id)
        self.assertIsNone(order.installment_plan_snapshot['expected_disbursement_amount'])

    def test_admin_can_grant_pricing_to_legacy_dealer_and_revoke_it(self):
        self.client.force_login(self.root)
        UserAccessState.objects.filter(user=self.dealer_user).delete()
        url = reverse("dealer_account_edit", args=[self.dealer_user.pk])
        data = {"display_name": "甲車行人員", "username": self.dealer_user.username,
                "is_active": "on", "can_submit_orders": "on", "can_view_orders": "on",
                "can_browse_catalog": "on", "expected_revision": self.profile.revision,
                "can_adjust_pricing": "on", "order_scope": "own"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        self.assertTrue(AccessPolicy(self.dealer_user).screen("order_pricing", "operate"))
        self.assertFalse(AccessPolicy(self.dealer_user).screen("order_finance", "operate"))
        self.profile.refresh_from_db()
        data.update(expected_revision=self.profile.revision, can_adjust_pricing="")
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertFalse(AccessPolicy(self.dealer_user).screen("order_pricing", "operate"))

    def test_ungranted_custom_installment_is_rejected(self):
        self.client.force_login(self.dealer_user)
        response = self.submit(payment_type="installment", installment_custom="on", installment_company="任意公司", installment_periods=17, installment_monthly=1, installment_opening_fee=0)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SalesOrder.objects.exists())

    def test_pricing_draft_retains_authorized_values_but_not_financial_fields(self):
        from sales.models import OrderDraft
        self.grant_pricing(self.dealer_user)
        self.client.force_login(self.dealer_user)
        data = self.complete_data()
        data.update(vehicle_price="76000", vehicle_price_adjustment_reason="核准調價", installment_custom="on",
                    payment_type="installment", installment_company="其他融資", installment_periods="17",
                    installment_monthly="5100", installment_opening_fee="350", deposit_amount="9999",
                    **{"accessories-0-amount":"900", "accessories-0-labor_fee":"50"})
        response = self.client.post(reverse("intake_draft_save"), data)
        self.assertEqual(response.status_code, 200)
        draft = OrderDraft.objects.get()
        for key in ("vehicle_price", "installment_monthly", "installment_opening_fee", "installment_custom", "accessories-0-amount", "accessories-0-labor_fee"):
            self.assertEqual(draft.data[key], data[key])
        self.assertNotIn("deposit_amount", draft.data)
        page = self.client.get(reverse("order_start"), {"draft":draft.pk})
        self.assertEqual(page.context['form']['installment_monthly'].value(), "5100")
        self.assertEqual(page.context['form']['installment_opening_fee'].value(), "350")
        self.grant_pricing(self.dealer_user, False)
        self.client.post(reverse("intake_draft_save"), {**data, "_draft_id":draft.pk, "_draft_revision":draft.revision})
        draft.refresh_from_db()
        for key in ("vehicle_price", "installment_monthly", "installment_opening_fee", "installment_custom", "accessories-0-amount"):
            self.assertNotIn(key, draft.data)

    def test_authorized_gift_is_zero_and_attachment_after_accessory(self):
        self.client.force_login(self.root)
        product = AccessoryProduct.objects.create(name="後架", sale_price=1200, labor_fee=200)
        response = self.submit(**{"accessories-0-accessory_product":product.pk, "accessories-0-line_type":"gift", "accessories-0-amount":1200, "accessories-0-labor_fee":200})
        self.assertEqual(response.status_code, 302, response.context and response.context['formset'].errors)
        line = SalesOrder.objects.get().accessories.get()
        self.assertEqual((line.amount, line.labor_fee, line.line_total), (0,0,0))
        html = self.client.get(reverse('order_start')).content.decode()
        self.assertLess(html.index('id="accessory-forms"'), html.index('<h3>下訂附件'))

    def test_home_renders_two_panels_for_local_tabs(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'data-news-tabs')
        self.assertContains(response, 'id="news-announcements"')
        self.assertContains(response, 'id="news-releases"')

    def test_unlock_export_returns_finished_page(self):
        cache.clear()
        self.client.force_login(self.root)
        target = reverse('operations_report_export') + '?date_from=2026-09-01'
        response = self.client.post(reverse('profit_unlock'), {'password':'test-only', 'next':target})
        self.assertContains(response, '已解鎖淨利')
        self.assertContains(response, '下載檔案')
        self.assertNotContains(response, 'type="password"')

    def test_announcement_dealers_and_image_are_scoped(self):
        item = SystemAnnouncement.objects.create(title='甲專屬', body='圖文', published=True, audience='dealers')
        item.dealers.add(self.dealer)
        picture = AnnouncementImage.objects.create(announcement=item, image=self.image('news.png'))
        image_url = reverse('announcement_image', args=[picture.pk])
        self.assertEqual(self.client.get(image_url).status_code, 404)
        self.client.force_login(self.dealer_user)
        self.assertContains(self.client.get(reverse('announcement_detail', args=[item.pk])), image_url)
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        item.dealers.clear(); item.dealers.add(self.other_dealer)
        self.assertEqual(self.client.get(image_url).status_code, 404)
        self.client.force_login(self.root)
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        picture.removed = True; picture.save()
        self.assertEqual(self.client.get(image_url).status_code, 404)

    def test_announcement_upload_validation_and_revision(self):
        data = {'title':'圖片公告', 'body':'內容', 'audience':'dealers', 'dealers':[self.dealer.pk], 'starts_at':timezone.localtime().strftime('%Y-%m-%dT%H:%M'), 'expected_version':0, 'action':'publish'}
        self.client.force_login(self.root)
        response = self.client.post(reverse('announcement_manage'), {**data, 'uploads':self.image('news.png')})
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        item = SystemAnnouncement.objects.get()
        self.assertEqual(item.images.count(), 1)
        self.assertEqual(item.revisions.get().content['dealers'], [self.dealer.pk])
        invalid = SimpleUploadedFile('fake.png', b'<script>bad</script>', content_type='image/png')
        form = AnnouncementForm(data, {'uploads':[invalid]})
        self.assertFalse(form.is_valid())
        self.assertIn('uploads', form.errors)

    def test_gift_defaults_are_optional_and_delete_keeps_audit(self):
        self.dealer.holiday_gift = True; self.dealer.save()
        self.client.force_login(self.root)
        url = reverse('gift_distribution')
        self.client.post(url, {'title':'空白活動', 'action':'add'})
        self.assertEqual(GiftDistribution.objects.get().items.count(), 0)
        self.client.post(url, {'title':'中秋', 'action':'add', 'include_holiday_dealers':'on'})
        activity = GiftDistribution.objects.latest('pk')
        self.assertEqual(list(activity.items.values_list('source_id', flat=True)), [self.dealer.pk])
        detail = reverse('gift_distribution_detail', args=[activity.pk])
        self.client.post(detail, {'action':'delete'})
        activity.refresh_from_db(); self.assertIsNone(activity.deleted_at)
        self.client.post(detail, {'action':'delete', 'confirm_delete':'yes'})
        activity.refresh_from_db(); self.assertIsNotNone(activity.deleted_at)
        self.assertEqual(activity.items.count(), 1)
        self.assertEqual(activity.events.count(), 2)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertNotContains(self.client.get(url), '中秋')

    def test_copy_search_and_plate_label(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse('site_copy_manage'), {'scope':'print','q':'牌險'})
        self.assertContains(response, 'print.contract.plate_description')
        self.assertEqual(catalog()['print.contract.plate_description']['default'], '領牌＋強制險')

    def test_zero_difference_not_shown_as_paid(self):
        from sales.views import _decorate_reconciliation_record
        self.submit()
        order = SalesOrder.objects.get()
        record = PaymentRecord(order=order, system_key='balance', expected_amount=Decimal(0), received_amount=Decimal(0), confirmed=False)
        _decorate_reconciliation_record(record)
        self.assertEqual(record.reconciliation_state, '預計金額待核對')
