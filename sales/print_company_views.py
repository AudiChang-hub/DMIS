"""admin 專用開單公司設定及訂單更正；GET 不寫入資料。"""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from sales.access.views import root_required
from sales.models import PrintCompany, PrintCompanyChange, SalesOrder, SalesSource
from sales.services.print_company import FIELDS, company_data, correct_order_company


class CompanyForm(forms.ModelForm):
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    reason = forms.CharField(label="設定／修改原因", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = PrintCompany
        fields = FIELDS
        widgets = {key: forms.TextInput(attrs={"class": "form-control", "data-company-field": key}) for key in FIELDS}


@root_required
@require_http_methods(["GET", "POST"])
def company_settings(request, source_pk=None):
    source = get_object_or_404(SalesSource, pk=source_pk, source_type="dealer") if source_pk else None
    key = f"dealer:{source.pk}" if source else "home"
    company = PrintCompany.objects.filter(key=key).first()
    initial = {"expected_revision": company.revision if company else 0}
    if source and not company:
        initial.update(address=source.address, phone=source.phone)
    form = CompanyForm(request.POST or None, instance=company, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # 同一車行首次設定也序列化；home 由 migration 建立。
            if source:
                SalesSource.objects.select_for_update().get(pk=source.pk)
            current = PrintCompany.objects.select_for_update().filter(key=key).first()
            if (current.revision if current else 0) != form.cleaned_data["expected_revision"]:
                form.add_error(None, "公司資料已被其他人修改，請重新整理後再儲存。")
            else:
                before = company_data(current) if current else {}
                current = current or PrintCompany(key=key, source=source)
                for field in FIELDS:
                    setattr(current, field, form.cleaned_data[field])
                current.revision += 1
                current.full_clean()
                current.save()
                PrintCompanyChange.objects.create(company=current, actor=request.user,
                    reason=form.cleaned_data["reason"], before=before, after=company_data(current))
                messages.success(request, "公司資料已儲存。僅供新訂單帶入，舊訂單及已簽文件不會改變。")
                return redirect("dealer_print_company", source_pk=source.pk) if source else redirect("print_company_settings")
    dealers = SalesSource.objects.filter(source_type="dealer", active=True).select_related("print_company").order_by("name")
    query = request.GET.get("q", "").strip()[:80]
    if query:
        dealers = dealers.filter(Q(name__icontains=query) | Q(code__icontains=query))
    from django.core.paginator import Paginator
    page = Paginator(dealers, 20).get_page(request.GET.get("page"))
    pending = SalesOrder.objects.filter(print_company_snapshot={}).order_by("-established_on", "-pk")
    if source:
        pending = pending.filter(source=source)
    pending_page = Paginator(pending.only("pk", "number", "owner_name", "established_on"), 10).get_page(request.GET.get("pending_page"))
    changes = PrintCompanyChange.objects.filter(company=company, order_number="").select_related("actor").order_by("-pk")[:10] if company else []
    return render(request, "sales/print_company_settings.html", {
        "form": form, "source": source, "company": company, "page_obj": page, "query": query, "changes": changes, "pending_page": pending_page,
    })


class OrderCompanyForm(forms.Form):
    company = forms.ModelChoiceField(label="本張訂單的開單公司", queryset=PrintCompany.objects.none())
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    reason = forms.CharField(label="確認／更正原因", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    acknowledged = forms.BooleanField(label="我已確認銷售方；此變更只影響之後產生的訂購單，不覆寫已簽文件。")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = PrintCompany.objects.filter(Q(key="home") | Q(source__active=True)).order_by("legal_name")


@root_required
@require_http_methods(["GET", "POST"])
def order_company(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    form = OrderCompanyForm(request.POST or None, initial={"company": order.print_company_id, "expected_revision": order.revision})
    if request.method == "POST" and form.is_valid():
        try:
            correct_order_company(user=request.user, pk=order.pk, company_id=form.cleaned_data["company"].pk,
                revision=form.cleaned_data["expected_revision"], reason=form.cleaned_data["reason"],
                acknowledged=form.cleaned_data["acknowledged"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "已保留開單公司資料與修改紀錄，未變更訂單金額或已簽附件。")
            return redirect("order_print_company", pk=order.pk)
    changes = order.print_company_changes.select_related("actor").order_by("-pk")[:20]
    return render(request, "sales/order_print_company.html", {"order": order, "form": form, "changes": changes})


def print_company_missing(request, order):
    return render(request, "sales/print_company_missing.html", {"order": order}, status=409)
