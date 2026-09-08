from django import forms
from django.forms import formset_factory

from sales.models import SalesOrder, SalesSource, VehicleModel
from .engine import CHARTS, DIMENSIONS, METRICS, NAVIGATION_GROUPS, formula_tree


class ReportForm(forms.Form):
    title = forms.CharField(label="報表名稱", max_length=100)
    description = forms.CharField(label="報表說明", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))
    audience = forms.ChoiceField(label="發布後可查看的人", choices=[("admin", "只有我（admin）"), ("team", "所有已登入的內部帳號")])
    date_basis = forms.ChoiceField(label="統計日期依據", choices=[("registration_date", "領牌日期（未領牌訂單不計入）"), ("order_date", "訂單日期")])
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    navigation_group = forms.ChoiceField(label="側欄分類", choices=NAVIGATION_GROUPS.items(), required=False)
    page_order = forms.IntegerField(label="側欄順序（小的在前）", min_value=0, max_value=999, required=False)

    def clean_navigation_group(self):
        return self.cleaned_data["navigation_group"] or "custom"

    def clean_page_order(self):
        return self.cleaned_data["page_order"] or 0


class CardForm(forms.Form):
    title = forms.CharField(label="圖表名稱", max_length=100)
    chart = forms.ChoiceField(label="呈現方式", choices=CHARTS.items())
    dimension = forms.ChoiceField(label="依什麼分類", choices=DIMENSIONS.items())
    metric = forms.ChoiceField(label="要看什麼數字", choices=METRICS.items())
    formula = forms.CharField(label="自訂試算公式", required=False, max_length=200,
                              help_text="僅自訂試算使用，例如 sale_total / count；支援 + − * / 與括號。")
    limit = forms.IntegerField(label="最多顯示幾群", min_value=1, max_value=200, initial=20)
    sort = forms.ChoiceField(label="排列方式", choices=[("key", "分類順序（月份由早到晚）"), ("value", "數值由高到低")])

    def clean_formula(self):
        expression = self.cleaned_data["formula"]
        if self.cleaned_data.get("metric") == "formula":
            formula_tree(expression)
        return expression


CardFormSet = formset_factory(CardForm, extra=0, min_num=1, max_num=8, absolute_max=8,
                              validate_min=True, validate_max=True, can_delete=True, can_order=True)


class FilterForm(forms.Form):
    start = forms.DateField(label="開始日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="結束日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    months = forms.MultipleChoiceField(label="月份（可複選）", required=False)
    brand = forms.MultipleChoiceField(label="品牌", required=False)
    energy = forms.MultipleChoiceField(label="能源別", required=False, choices=VehicleModel.EnergyType.choices)
    source_type = forms.MultipleChoiceField(label="來源類型", required=False, choices=SalesOrder.SourceType.choices)
    source = forms.MultipleChoiceField(label="車行／平台", required=False)

    def __init__(self, *args, **kwargs):
        self.date_basis = kwargs.pop("date_basis", "registration_date")
        super().__init__(*args, **kwargs)
        # 舊版單選空字串仍表示全部；QueryDict 保留多值，不轉成普通 dict。
        if self.is_bound and hasattr(self.data, "getlist"):
            self.data = self.data.copy()
            for key in ("months", "brand", "energy", "source_type", "source"):
                self.data.setlist(key, [value for value in self.data.getlist(key) if value])
        self.fields["brand"].choices = [(name, name) for name in VehicleModel.objects.order_by("brand").values_list("brand", flat=True).distinct()]
        self.fields["source"].choices = [(str(pk), name) for pk, name in SalesSource.objects.order_by("name", "pk").values_list("pk", "name")]
        self.fields["months"].choices = [(month.strftime("%Y-%m"), month.strftime("%Y 年 %m 月"))
            for month in SalesOrder.objects.dates(self.date_basis, "month", order="DESC")]

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("開始日期不可晚於結束日期。")
        if len(data.get("months", [])) > 120:
            raise forms.ValidationError("一次最多選擇 120 個月份；全部期間請清除月份選取。")
        return data
