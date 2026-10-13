"""管理者工具 › 配車規則：admin 隨時調整優先配車月數（使用者 2026-10-13）。"""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .access.views import root_required
from .models import SystemSettingChange, allocation_priority_cutoff
from .services.system_settings import (
    ALLOCATION_PRIORITY_AGE_KEY, ALLOCATION_PRIORITY_AGE_RANGE, allocation_priority_age_months,
    set_allocation_priority_age_months,
)


class AllocationRuleForm(forms.Form):
    months = forms.TypedChoiceField(
        label="出廠超過幾個月自動列為優先配車", coerce=int,
        choices=[(value, f"{value} 個月") for value in range(ALLOCATION_PRIORITY_AGE_RANGE[0], ALLOCATION_PRIORITY_AGE_RANGE[1] + 1)],
        widget=forms.Select(attrs={"class": "form-control"}),
    )


@root_required
@require_http_methods(["GET", "POST"])
def allocation_rules(request):
    current = allocation_priority_age_months()
    form = AllocationRuleForm(request.POST or None, initial={"months": current})
    if request.method == "POST" and form.is_valid():
        try:
            changed = set_allocation_priority_age_months(form.cleaned_data["months"], request.user.get_username())
        except ValidationError as exc:
            form.add_error("months", exc)
        else:
            months = form.cleaned_data["months"]
            if changed:
                messages.success(request, f"已改為出廠超過 {months} 個月自動優先配車，現在起生效（{allocation_priority_cutoff(months=months)} 以前出廠的車）。")
            else:
                messages.info(request, "規則沒有變更。")
            return redirect("allocation_rule_settings")
    previews = [
        {"months": value, "cutoff": allocation_priority_cutoff(months=value)}
        for value in range(ALLOCATION_PRIORITY_AGE_RANGE[0], ALLOCATION_PRIORITY_AGE_RANGE[1] + 1)
    ]
    return render(request, "sales/allocation_rule_settings.html", {
        "form": form, "current": current, "cutoff": allocation_priority_cutoff(months=current),
        "previews": previews,
        "changes": SystemSettingChange.objects.filter(key=ALLOCATION_PRIORITY_AGE_KEY)[:20],
    })
