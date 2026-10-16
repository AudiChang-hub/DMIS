"""admin 專用本店開單公司設定；GET 不寫入資料。系統只有本店人員使用，訂購單一律用本店公司（使用者 2026-10-16）。"""
from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from sales.access.views import root_required
from sales.models import PrintCompany, PrintCompanyChange
from sales.services.print_company import FIELDS, company_data


class CompanyForm(forms.ModelForm):
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    reason = forms.CharField(label="設定／修改原因", max_length=500, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))

    class Meta:
        model = PrintCompany
        fields = FIELDS
        widgets = {key: forms.TextInput(attrs={"class": "form-control", "data-company-field": key}) for key in FIELDS}


@root_required
@require_http_methods(["GET", "POST"])
def company_settings(request):
    company = PrintCompany.objects.filter(key="home").first()
    form = CompanyForm(request.POST or None, instance=company, initial={"expected_revision": company.revision if company else 0})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            current = PrintCompany.objects.select_for_update().filter(key="home").first()
            if (current.revision if current else 0) != form.cleaned_data["expected_revision"]:
                form.add_error(None, "公司資料已被其他人修改，請重新整理後再儲存。")
            else:
                before = company_data(current) if current else {}
                current = current or PrintCompany(key="home")
                for field in FIELDS:
                    setattr(current, field, form.cleaned_data[field])
                current.revision += 1
                current.full_clean()
                current.save()
                PrintCompanyChange.objects.create(company=current, actor=request.user,
                    reason=form.cleaned_data["reason"], before=before, after=company_data(current))
                messages.success(request, "公司資料已儲存。僅供之後產生的訂購單帶入，已保留公司資料的訂單及已簽文件不會改變。")
                return redirect("print_company_settings")
    changes = PrintCompanyChange.objects.filter(company=company, order_number="").select_related("actor").order_by("-pk")[:10] if company else []
    return render(request, "sales/print_company_settings.html", {"form": form, "company": company, "changes": changes})


def print_company_missing(request, order):
    return render(request, "sales/print_company_missing.html", {"order": order}, status=409)
