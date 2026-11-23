"""T-281 h（使用者 2026-11-21 選 B）：訂單頁、給付頁減少渲染量，畫面與送出的值都不變。

- widget 快速輸出：各種 widget 與刁鑽的值（跳脫、安全字串、布林屬性、lazy 字串、日期、數字、分組）和 Django 內建模板逐字相同。
- 訂單頁整頁 HTML：快速輸出開、關逐字相同；內建 widget 不會退回慢的模板。
"""
import re
from html.parser import HTMLParser
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django import forms
from django.contrib.auth import get_user_model
from django.forms.renderers import DjangoTemplates
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy

from sales import form_rendering
from django.db import connection
from django.forms.models import BaseInlineFormSet
from django.test.utils import CaptureQueriesContext

from sales.forms import BaseOrderPageAccessoryFormSet
from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct, OtherFeeLine, PaymentRecord
from sales.reporting import payouts
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_dealer_payouts_t150 import KEY, PayoutTestBase

SHARED_SELECT = re.compile(r'<select [^>]*data-shared-options="accessory-product"')
ROW_FORM = re.compile(r"payout-item__toggle|data-payout-note")
CSRF = re.compile(r'name="csrfmiddlewaretoken" value="[^"]+"|"[A-Za-z0-9]{64}"')  # CSRF token 每次重新遮罩


class WidgetEquivalenceTests(TestCase):
    def assert_same(self, widget, name, value, attrs=None):
        expected = widget.render(name, value, attrs=attrs, renderer=DjangoTemplates())
        actual = widget.render(name, value, attrs=attrs, renderer=form_rendering.FastWidgetRenderer())
        self.assertEqual(actual, expected)

    def test_renderer_verified_django_templates(self):
        self.assertTrue(form_rendering.FastWidgetRenderer()._suffix, "Django 內建 widget 模板與快速輸出照抄的內容不同")

    def test_inputs_textareas_and_selects_match_django(self):
        tricky = ['<b>"A&B"</b>', mark_safe("<i>safe</i>"), gettext_lazy("名稱"), "", "0", 0, 12, Decimal("1234.50"),
                  date(2026, 11, 21), datetime(2026, 11, 21, 9, 30, tzinfo=timezone.get_current_timezone()), None, True, False]
        attrs = [None, {"class": "form-control", "readonly": True, "disabled": False, "data-x": None, "data-n": 3,
                        "placeholder": '填 "名稱" & <備註>', "data-safe": mark_safe("<ok>"), "aria-label": gettext_lazy("配件")}]
        widgets = [forms.TextInput(), forms.NumberInput(attrs={"step": "1", "min": 0}), forms.HiddenInput(), forms.EmailInput(),
                   forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), forms.DateInput(), forms.CheckboxInput(),
                   forms.PasswordInput(render_value=True), forms.URLInput(), forms.Textarea(attrs={"rows": 3}),
                   forms.FileInput(), forms.ClearableFileInput()]
        for widget in widgets:
            for value in tricky:
                for extra in attrs:
                    with self.subTest(widget=type(widget).__name__, value=value, attrs=bool(extra)):
                        self.assert_same(widget, "f-0-name", value, extra)
        choices = [("", "---------"), ("a", '<A&"B">'), (1, 1), ("組一", [(2, "二"), ("3", gettext_lazy("三"))]),
                   (gettext_lazy("組二"), [("x", mark_safe("<b>X</b>"))]), ("other", "自行填寫名稱")]
        for widget in (forms.Select(choices=choices), forms.SelectMultiple(choices=choices),
                       forms.Select(choices=choices, attrs={"class": "form-control", "data-shared": True})):
            for value in ("", "a", 1, "2", "x", ["a", "x"], None, "missing"):
                for extra in attrs:
                    with self.subTest(widget=type(widget).__name__, value=value, attrs=bool(extra)):
                        self.assert_same(widget, "accessories-0-accessory_product", value, extra)

    def test_unusual_cases_fall_back_to_django(self):
        renderer = form_rendering.FastWidgetRenderer()
        callable_value = forms.TextInput()
        context = callable_value.get_context("f", "v", None)
        context["widget"]["value"] = lambda: "called"
        self.assertEqual(renderer.render(callable_value.template_name, context),
                         DjangoTemplates().render(callable_value.template_name, context))
        radio = forms.RadioSelect(choices=[("a", "A"), ("b", "B")])
        self.assert_same(radio, "r", "a")
        with mock.patch.object(form_rendering.FastWidgetRenderer, "_verified_suffixes", return_value={}):
            changed = form_rendering.FastWidgetRenderer()
        with mock.patch.object(DjangoTemplates, "render", return_value="slow") as slow:
            self.assertEqual(changed.render("django/forms/widgets/text.html", context), "slow")
        slow.assert_called_once()


class OrderPageRenderTests(TestCase):
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        self.setUp_base()
        self.admin = get_user_model().objects.create_superuser("t281-render", password="Test-Only-123")
        self.client.force_login(self.admin)
        helmet = AccessoryCategory.objects.get(name="安全帽")
        holder = AccessoryCategory.objects.get(name="手機架")
        self.light = AccessoryProduct.objects.create(name="輕便安全帽", category=helmet, sale_price=Decimal("800"))
        self.light.categories.add(helmet)
        self.five = AccessoryProduct.objects.create(name="五匹手機架 <特價>", category=holder, sale_price=Decimal("1200"))
        self.five.categories.add(holder, helmet)
        self.retired = AccessoryProduct.objects.create(name="停用的風鏡", sale_price=Decimal("300"), active=False)

    def rich_order(self):
        order, _vehicle = self.make_order()
        AccessoryLine.objects.create(order=order, accessory_product=self.light, name=self.light.name, amount=Decimal("800"))
        AccessoryLine.objects.create(order=order, accessory_product=self.five, name=self.five.name, amount=Decimal("1200"), quantity=2)
        AccessoryLine.objects.create(order=order, accessory_product=self.retired, name=self.retired.name, amount=Decimal("300"))
        AccessoryLine.objects.create(order=order, name='自填 "雨衣" & 手套', amount=Decimal("200"), line_type="gift", note="<備註>")
        OtherFeeLine.objects.create(order=order, name="代辦費", amount=Decimal("600"))
        PaymentRecord.objects.create(order=order, item_name="訂金", expected_amount=0, received_amount=5000)
        return order

    def page(self, order, *, original=False, params=None, route="order_detail"):
        """original=True：關掉 T-281 h 的三項（快速輸出、共用配件清單、既有列只帶已選項），等同修改前。"""
        patches = [
            mock.patch.object(form_rendering, "use_fast_widgets", side_effect=lambda context, **kwargs: context),
            mock.patch.object(BaseOrderPageAccessoryFormSet, "get_form_kwargs", BaseInlineFormSet.get_form_kwargs),
            mock.patch.object(BaseOrderPageAccessoryFormSet, "share_product_options", lambda formset: formset),
        ] if original else []
        for patch in patches:
            patch.start()
        try:
            response = self.client.get(reverse(route, args=[order.pk]), params or {})
        finally:
            for patch in patches:
                patch.stop()
        self.assertEqual(response.status_code, 200)
        return CSRF.sub("", response.content.decode())

    @staticmethod
    def restore_shared_options(html):
        """照 _order_form_scripts.html 的做法還原：清單換成新增列範本的，只標第一個值相同的選項，拿掉標記。"""
        template = re.search(r'<template id="empty-accessory">.*?<select name="accessories-__prefix__-accessory_product"[^>]*>(.*?)</select>',
                             html, re.S).group(1)
        template = template.replace(" selected>", ">")

        def restore(match):
            value = re.search(r'<option value="([^"]*)" selected>', match.group(2)).group(1)
            options = template.replace(f'<option value="{value}">', f'<option value="{value}" selected>', 1)
            return match.group(1).replace(' data-shared-options="accessory-product"', "") + options + "</select>"
        return re.sub(r'(<select name="accessories-\d+-accessory_product"[^>]*data-shared-options="accessory-product"[^>]*>)(.*?)</select>',
                      restore, html, flags=re.S)

    def test_order_page_matches_original_and_submits_same_values(self):
        plain, _vehicle = self.make_order()
        rich = self.rich_order()
        for order, params, route in [(plain, None, "order_detail"), (plain, {"tab": "finance"}, "order_detail"),
                                     (rich, None, "order_detail"), (rich, {"tab": "finance"}, "order_detail")]:
            if True:
                with self.subTest(order=order.pk, params=params, route=route):
                    original = self.page(order, original=True, params=params, route=route)
                    current = self.page(order, params=params, route=route)
                    shared = len(SHARED_SELECT.findall(current))
                    self.assertEqual(shared, 3 if order is rich else 0)  # 停用配件那列清單不同，維持完整
                    if order is rich:
                        self.assertIn("停用的風鏡", original)
                        self.assertLess(len(current), len(original))
                    self.assertEqual(self.restore_shared_options(current), original)

    def test_rows_with_different_choices_keep_full_list(self):
        order = self.rich_order()
        AccessoryProduct.objects.filter(pk=self.light.pk).update(active=False)
        current = self.page(order)
        self.assertEqual(len(SHARED_SELECT.findall(current)), 2, "停用配件那列清單多一項，維持完整清單")
        self.assertEqual(self.restore_shared_options(current), self.page(order, original=True))

    def test_accessory_choices_are_queried_once_per_page(self):
        order = self.rich_order()

        def product_lists(original):
            with CaptureQueriesContext(connection) as captured:
                self.page(order, original=original)
            # 各列配件名稱清單的查詢：啟用中或該列已選的配件
            return len([q for q in captured.captured_queries
                        if re.search(r'"sales_accessoryproduct"\."active" OR "sales_accessoryproduct"\."id"', q["sql"])])
        self.assertGreaterEqual(product_lists(original=True), 5, "原本每列與新增列各查一次")
        self.assertEqual(product_lists(original=False), 2, "一般清單一次＋停用配件那列一次")

    def test_builtin_widgets_do_not_fall_back(self):
        order = self.rich_order()
        fallbacks = []
        original = DjangoTemplates.render

        def spy(renderer, template_name, context, request=None):
            if isinstance(renderer, form_rendering.FastWidgetRenderer) and template_name.startswith("django/forms/widgets/"):
                fallbacks.append(template_name)
            return original(renderer, template_name, context, request)
        with mock.patch.object(DjangoTemplates, "render", spy):
            self.page(order)
        fast = {f"django/forms/widgets/{name}.html" for name in ("select", "textarea", *form_rendering.INPUT_FAMILY)}
        self.assertEqual([name for name in fallbacks if name in fast], [])


class _FormFields(HTMLParser):
    """各張表單送出的欄位：script=True 時 noscript 內容當純文字（瀏覽器有 JavaScript 時的行為）。"""

    def __init__(self, script):
        super().__init__()
        self.script, self.forms, self.form, self.noscript = script, [], None, 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "noscript":
            self.noscript += 1
        elif tag == "form":
            self.form = {"attrs": attrs, "fields": []}
            self.forms.append(self.form)
        elif tag == "input" and self.form is not None and not (self.script and self.noscript):
            if attrs.get("type") == "checkbox" and ("checked" not in attrs or "disabled" in attrs):
                return
            if attrs.get("name") and "disabled" not in attrs:
                self.form["fields"].append((attrs["name"], attrs.get("value", "on" if attrs.get("type") == "checkbox" else "")))

    def handle_endtag(self, tag):
        if tag == "noscript":
            self.noscript -= 1
        elif tag == "form":
            self.form = None


def form_fields(html, script):
    parser = _FormFields(script)
    parser.feed(html)
    return parser.forms


class PayoutPageRenderTests(PayoutTestBase):
    """給付頁（T-281 h）：每列只留勾選框、備註與辨識用的 key／action；csrf、next 整頁共用，送出的欄位與以前相同。"""

    def setUp(self):
        self.client.force_login(self.admin)
        self.unpaid = self.registered()
        self.paid = self.registered()
        payouts.set_paid([KEY.format(self.paid.pk)], True, "staff")

    def html(self):
        response = self.client.get(reverse("dealer_payout_list"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_js_and_noscript_submissions_match_the_original_fields(self):
        html = self.html()
        shared = next(form for form in form_fields(html, script=True) if form["attrs"].get("id") == "payout-shared")
        self.assertEqual([name for name, _ in shared["fields"]], ["csrfmiddlewaretoken", "next"])
        rows_js = [form for form in form_fields(html, script=True) if ROW_FORM.search(form["attrs"].get("class", "") + " " + " ".join(form["attrs"]))]
        rows_plain = [form for form in form_fields(html, script=False) if ROW_FORM.search(form["attrs"].get("class", "") + " " + " ".join(form["attrs"]))]
        self.assertEqual(len(rows_js), 4, "兩列各有勾選與備註表單")
        expected = {
            (KEY.format(self.unpaid.pk), "paid"): [],
            (KEY.format(self.paid.pk), "unpaid"): [("paid_toggle", "on")],
            (KEY.format(self.unpaid.pk), "note"): [("note", "")],
            (KEY.format(self.paid.pk), "note"): [("note", "")],
        }
        for js, plain in zip(rows_js, rows_plain):
            # dealer-payouts.js：共用的 csrf、next 放最前面，其餘照表單原本的順序
            submitted = shared["fields"] + js["fields"]
            names = [name for name, _ in submitted]
            key, action = dict(submitted)["key"], dict(submitted)["action"]
            self.assertEqual(names[:4], ["csrfmiddlewaretoken", "next", "key", "action"], "與修改前的欄位順序相同")
            self.assertEqual(submitted[4:], expected[(key, action)])
            self.assertEqual(sorted(name for name, _ in plain["fields"]), sorted(names), "沒有 JavaScript 時 noscript 補齊同樣的欄位")
            self.assertEqual(dict(plain["fields"])["next"], dict(submitted)["next"])
        for form in rows_js:
            self.assertNotIn("csrfmiddlewaretoken", dict(form["fields"]), "各列不再各放一組 csrf 與 next")
            self.assertNotIn("next", dict(form["fields"]))

    def test_server_accepts_the_reconstructed_fields(self):
        html = self.html()
        shared = dict(next(form for form in form_fields(html, script=True) if form["attrs"].get("id") == "payout-shared")["fields"])
        toggle = next(form for form in form_fields(html, script=True)
                      if ROW_FORM.search(form["attrs"].get("class", "") + " " + " ".join(form["attrs"])) and dict(form["fields"]).get("action") == "paid")
        self.client.handler.enforce_csrf_checks = True
        response = self.client.post(toggle["attrs"]["action"], {**shared, **dict(toggle["fields"])})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(payouts.current_item(KEY.format(self.unpaid.pk)).paid)
