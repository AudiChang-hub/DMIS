"""補助方案主檔：新增、編輯、停用；訂車時多選帶入訂單補助項目。"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from sales.forms import SubsidyProgramForm
from sales.models import SubsidyProgram
from sales.status_tabs import keep_status, queryset_status_counts, requested_status, status_tabs


@login_required
def subsidy_program_list(request):
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(SubsidyProgram, pk=request.GET["edit"])
    form = SubsidyProgramForm(request.POST or None, instance=editing)
    show_editor = bool(editing or request.GET.get("new") == "1" or request.method == "POST")
    if request.method == "POST" and form.is_valid():
        program = form.save()
        messages.success(request, f"已儲存補助方案：{program.name}。")
        return redirect(keep_status(reverse("subsidy_program_list"), request))
    status = requested_status(request.GET)
    return render(
        request,
        "sales/subsidy_program_list.html",
        {
            "programs": SubsidyProgram.objects.filter(active=status == "active").annotate(
                order_count=Count("items__order", distinct=True)),
            "status_tabs": status_tabs(request, status, queryset_status_counts(SubsidyProgram.objects.all())),
            "form": form,
            "editing": editing,
            "show_editor": show_editor,
        },
    )
