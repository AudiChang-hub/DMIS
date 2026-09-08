from django import forms
from django.forms import formset_factory

from sales.models import SalesOrder, SalesSource, VehicleModel
from .engine import CHARTS, DIMENSIONS, METRICS, NAVIGATION_GROUPS, SCOPE_LABELS, formula_tree, validate_scope
from .records import RECORD_COLUMNS, DEFAULT_RECORD_COLUMNS
from .source_compatibility import SOURCE_CLASSIFICATIONS, MODEL_PRESENCE, SOURCE_ENERGIES


class ScopeForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial = dict(self.initial)
        choices = {
            "brand": [(name, name) for name in VehicleModel.objects.order_by("brand").values_list("brand", flat=True).distinct()],
            "energy": VehicleModel.EnergyType.choices,
            "source_type": SalesOrder.SourceType.choices,
            "source": [(str(pk), name) for pk, name in SalesSource.objects.order_by("name", "pk").values_list("pk", "name")],
            "model": [(str(model.pk), str(model)) for model in VehicleModel.objects.order_by("brand", "name", "pk")],
            "legacy_source": [(label, label) for label in SOURCE_CLASSIFICATIONS],
            "model_presence": list(MODEL_PRESENCE.items()),
            "legacy_energy": [(label, label) for label in SOURCE_ENERGIES],
        }
        scope = self.initial.get("fixed_filters", {})
        validate_scope(scope)
        for key, label in SCOPE_LABELS.items():
            options = list(choices[key])
            known = {value for value, _ in options}
            # 保留已刪除主檔的固定限制；重新開啟儲存不可變成不限。
            options.extend((value, f"已移除項目 #{value}") for value in scope.get(key, []) if value not in known)
            self.fields["fixed_" + key] = forms.MultipleChoiceField(label=label, choices=options, required=False)
            self.initial["fixed_" + key] = scope.get(key, [])

    def primary_fields(self):
        return [field for field in self.visible_fields() if not field.name.startswith("fixed_")]

    def scope_fields(self):
        return [self["fixed_" + key] for key in SCOPE_LABELS]

    def scope_count(self):
        return sum(len(field.value() or []) for field in self.scope_fields())

    def scope_data(self):
        return {key: self.cleaned_data["fixed_" + key] for key in SCOPE_LABELS if self.cleaned_data.get("fixed_" + key)}


class ReportForm(ScopeForm):
    title = forms.CharField(label="報表名稱", max_length=100)
    description = forms.CharField(label="報表說明", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))
    audience = forms.ChoiceField(label="發布後可查看的人", choices=[("admin", "只有我（admin）"), ("team", "所有已登入的內部帳號")])
    date_basis = forms.ChoiceField(label="統計日期依據", choices=[("registration_date", "領牌日期"), ("order_date", "訂單日期")])
    include_undated = forms.BooleanField(label="未選期間時包含尚未領牌訂單", required=False,
        help_text="僅影響本報表分析；日期未填寫另列，不計入任何月份。指定期間或月份時仍排除未填日期。")
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    navigation_group = forms.ChoiceField(label="側欄分類", choices=NAVIGATION_GROUPS.items(), required=False)
    page_order = forms.IntegerField(label="側欄順序（小的在前）", min_value=0, max_value=999, required=False)
    include_records = forms.BooleanField(label="顯示來源訂單明細表", required=False)
    records_columns = forms.MultipleChoiceField(label="明細顯示欄位", choices=RECORD_COLUMNS.items(), initial=DEFAULT_RECORD_COLUMNS,
        required=False, widget=forms.CheckboxSelectMultiple)
    records_page_size = forms.TypedChoiceField(label="明細每頁筆數", choices=[(10, "10 筆"), (25, "25 筆"), (50, "50 筆")],
        coerce=int, initial=10, required=False, empty_value=10)

    def primary_fields(self):
        return [field for field in super().primary_fields() if field.name != "include_records" and not field.name.startswith("records_")]

    def clean_navigation_group(self):
        return self.cleaned_data["navigation_group"] or "custom"

    def clean_page_order(self):
        return self.cleaned_data["page_order"] or 0

    def clean_records_columns(self):
        # CheckboxSelectMultiple 會以選項清單順序送出；不可因預覽／儲存而打亂既有欄位順序。
        selected = self.cleaned_data["records_columns"]
        existing = self.initial.get("records_columns", [])
        return [key for key in existing if key in selected] + [key for key in selected if key not in existing]


class CardForm(ScopeForm):
    title = forms.CharField(label="圖表名稱", max_length=100)
    chart = forms.ChoiceField(label="呈現方式", choices=CHARTS.items())
    dimension = forms.ChoiceField(label="依什麼分類", choices=DIMENSIONS.items())
    series = forms.ChoiceField(label="細分系列（堆疊圖使用）", choices=[("", "不細分"), *DIMENSIONS.items()], required=False)
    series_limit = forms.IntegerField(label="最多顯示幾個系列", min_value=1, max_value=200, initial=200, required=False,
        help_text="依下方系列排序取前 N 個；數值排名以目前顯示主分類中的合計計算。")
    series_sort = forms.ChoiceField(label="系列排列方式", choices=[("value", "系列合計由高到低"), ("key", "系列名稱由前到後"), ("key_desc", "系列名稱由後到前")], required=False)
    series_other = forms.BooleanField(label="其餘系列合併為其他", required=False)
    metric = forms.ChoiceField(label="要看什麼數字", choices=METRICS.items())
    formula = forms.CharField(label="自訂試算公式", required=False, max_length=200,
                              help_text="僅自訂試算使用，例如 sale_total / count；支援 + − * / 與括號。")
    limit = forms.IntegerField(label="最多顯示幾群", min_value=1, max_value=200, initial=20)
    sort = forms.ChoiceField(label="排列方式", choices=[("key", "分類順序（日期由早到晚）"), ("key_desc", "分類倒序（日期由近到遠）"), ("value", "數值由高到低")])

    def clean_formula(self):
        expression = self.cleaned_data["formula"]
        if self.cleaned_data.get("metric") == "formula":
            formula_tree(expression)
        return expression

    def clean_series_limit(self):
        return self.cleaned_data["series_limit"] or 200

    def clean_series_sort(self):
        return self.cleaned_data["series_sort"] or "value"


CardFormSet = formset_factory(CardForm, extra=0, min_num=0, max_num=8, absolute_max=8,
                              validate_min=True, validate_max=True, can_delete=True, can_order=True)


class FilterForm(forms.Form):
    focus = forms.CharField(required=False, max_length=6000, widget=forms.HiddenInput)
    grain = forms.ChoiceField(label="日期圖表層級", required=False, choices=[("", "依原設計"), ("year", "按年"), ("month", "按月"), ("day", "按日")])
    start = forms.DateField(label="開始日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="結束日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    months = forms.MultipleChoiceField(label="月份（可複選）", required=False)
    brand = forms.MultipleChoiceField(label="品牌", required=False)
    energy = forms.MultipleChoiceField(label="能源別", required=False, choices=VehicleModel.EnergyType.choices)
    source_type = forms.MultipleChoiceField(label="來源類型", required=False, choices=SalesOrder.SourceType.choices)
    source = forms.MultipleChoiceField(label="車行／平台", required=False)
    legacy_source = forms.MultipleChoiceField(label="原報表銷售來源（五分類）", required=False, choices=[(label, label) for label in SOURCE_CLASSIFICATIONS])
    legacy_energy = forms.MultipleChoiceField(label="原報表能源（比對用）", required=False, choices=[(label, label) for label in SOURCE_ENERGIES])

    def __init__(self, *args, **kwargs):
        self.date_basis = kwargs.pop("date_basis", "registration_date")
        super().__init__(*args, **kwargs)
        for index in range(8):
            self.fields[f"grain_{index}"] = forms.ChoiceField(required=False, widget=forms.HiddenInput,
                choices=[("", "依整頁設定"), ("year", "按年"), ("month", "按月"), ("day", "按日")])
            self.fields[f"sort_{index}"] = forms.ChoiceField(required=False, widget=forms.HiddenInput,
                choices=[("", "依原設計"), ("key", "分類順序"), ("key_desc", "分類倒序"), ("value", "數值遞減")])
        # 舊版單選空字串仍表示全部；QueryDict 保留多值，不轉成普通 dict。
        if self.is_bound and hasattr(self.data, "getlist"):
            self.data = self.data.copy()
            for key in ("months", "brand", "energy", "source_type", "source", "legacy_source"):
                self.data.setlist(key, [value for value in self.data.getlist(key) if value])
        self.fields["brand"].choices = [(name, name) for name in VehicleModel.objects.order_by("brand").values_list("brand", flat=True).distinct()]
        self.fields["source"].choices = [(str(pk), name) for pk, name in SalesSource.objects.order_by("name", "pk").values_list("pk", "name")]
        self.fields["months"].choices = [(month.strftime("%Y-%m"), month.strftime("%Y 年 %m 月"))
            for month in SalesOrder.objects.dates(self.date_basis, "month", order="DESC")]

    def clean(self):
        data = super().clean()
        from .cross_filter import selections
        selections(data.get("focus"))
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("開始日期不可晚於結束日期。")
        if len(data.get("months", [])) > 120:
            raise forms.ValidationError("一次最多選擇 120 個月份；全部期間請清除月份選取。")
        return data
