from django import forms
from django.forms import formset_factory

from sales.models import VehicleModel
from .engine import CHARTS, DIMENSIONS, METRICS, formula_tree


class ReportForm(forms.Form):
    title = forms.CharField(label="報表名稱", max_length=100)
    description = forms.CharField(label="報表說明", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))
    audience = forms.ChoiceField(label="發布後可查看的人", choices=[("admin", "只有我（admin）"), ("team", "所有已登入的內部帳號")])
    date_basis = forms.ChoiceField(label="統計日期依據", choices=[("registration_date", "領牌日期（未領牌訂單不計入）"), ("order_date", "訂單日期")])
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


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
    brand = forms.ChoiceField(label="品牌", required=False)
    energy = forms.ChoiceField(label="能源別", required=False, choices=[("", "全部能源別"), *VehicleModel.EnergyType.choices])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["brand"].choices = [("", "全部品牌"), *[(name, name) for name in VehicleModel.objects.order_by("brand").values_list("brand", flat=True).distinct()]]

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("開始日期不可晚於結束日期。")
        return data
