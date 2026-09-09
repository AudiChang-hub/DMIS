from django import forms
from django.forms import formset_factory

from sales.models import SalesOrder, SalesSource, VehicleModel
from .engine import CHARTS, DIMENSIONS, METRICS, NAVIGATION_GROUPS, SCOPE_LABELS, MODEL_TEXT_SCOPES, formula_tree, validate_scope
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
            "age_scope": [("adult_or_unknown", "20 歲以上，另列生日未填、生日異常及公司或其他")],
        }
        scope = self.initial.get("fixed_filters", {})
        validate_scope(scope)
        for key, label in SCOPE_LABELS.items():
            if key in MODEL_TEXT_SCOPES:
                self.fields["fixed_" + key] = forms.CharField(label=label, required=False, max_length=20200,
                    widget=forms.Textarea(attrs={"rows": 2}), help_text=("區分大小寫；任何一項完整符合即排除。" if key == "model_exclude"
                    else "區分大小寫；同欄任一項符合即可，不同欄取交集。"))
                self.initial["fixed_" + key] = "\n".join(scope.get(key, []))
                continue
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
        return sum(len((field.value() or "").splitlines()) if field.name.removeprefix("fixed_") in MODEL_TEXT_SCOPES
                   else len(field.value() or []) for field in self.scope_fields())

    def clean(self):
        cleaned = super().clean()
        for key in MODEL_TEXT_SCOPES:
            name = "fixed_" + key
            values = list(dict.fromkeys(line.strip() for line in cleaned.get(name, "").splitlines() if line.strip()))
            try:
                validate_scope({key: values})
            except forms.ValidationError as error:
                self.add_error(name, error)
            else:
                cleaned[name] = values
        return cleaned

    def scope_data(self):
        return {key: self.cleaned_data["fixed_" + key] for key in SCOPE_LABELS if self.cleaned_data.get("fixed_" + key)}


class ReportForm(ScopeForm):
    reader_layout = forms.ChoiceField(label="閱讀版型", required=False, choices=[("standard", "一般報表"), ("sales_overview", "銷售總覽（原報表緊湊版型）")])

    def clean_reader_layout(self):
        return self.cleaned_data["reader_layout"] or "standard"

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
    records_mode = forms.ChoiceField(label="附表方式", choices=[("orders", "逐筆訂單（自選欄位）"), ("population", "車色／車主／性別分組（遮罩證號，僅 admin）")], required=False)
    records_page_size = forms.TypedChoiceField(label="明細每頁筆數", choices=[(10, "10 筆"), (25, "25 筆"), (50, "50 筆"), (100, "100 筆")],
        coerce=int, initial=10, required=False, empty_value=10)

    def primary_fields(self):
        return [field for field in super().primary_fields() if field.name != "include_records" and not field.name.startswith("records_")]

    def clean_navigation_group(self):
        return self.cleaned_data["navigation_group"] or "custom"

    def clean_records_mode(self):
        return self.cleaned_data["records_mode"] or "orders"

    def clean_page_order(self):
        return self.cleaned_data["page_order"] or 0

    def clean_records_columns(self):
        # CheckboxSelectMultiple 會以選項清單順序送出；不可因預覽／儲存而打亂既有欄位順序。
        selected = self.cleaned_data["records_columns"]
        existing = self.initial.get("records_columns", [])
        return [key for key in existing if key in selected] + [key for key in selected if key not in existing]


class CardForm(ScopeForm):
    width = forms.TypedChoiceField(label="圖表寬度", choices=[(6, "半寬（並排）"), (12, "全寬")], coerce=int, required=False, empty_value=6, initial=6)
    height = forms.IntegerField(label="圖表高度（像素）", min_value=320, max_value=1200, required=False, initial=520)

    def clean_height(self):
        return self.cleaned_data.get("height") or 520

    title = forms.CharField(label="圖表名稱", max_length=100)
    chart = forms.ChoiceField(label="呈現方式", choices=CHARTS.items())
    dimension = forms.ChoiceField(label="依什麼分類", choices=DIMENSIONS.items())
    series = forms.ChoiceField(label="細分系列／第二分類", choices=[("", "不細分"), *DIMENSIONS.items()], required=False,
        help_text="堆疊圖作為系列；資料表作為第二個分組欄位，例如月份＋歸屬車行。")
    series_limit = forms.IntegerField(label="最多顯示幾個系列", min_value=1, max_value=200, initial=200, required=False,
        help_text="依下方系列排序取前 N 個；數值排名以目前顯示主分類中的合計計算。")
    series_sort = forms.ChoiceField(label="系列排列方式", choices=[("value", "系列合計由高到低"), ("key", "系列名稱由前到後"), ("key_desc", "系列名稱由後到前")], required=False)
    series_other = forms.BooleanField(label="其餘系列合併為其他", required=False)
    metric = forms.ChoiceField(label="要看什麼數字", choices=METRICS.items())
    additional_metrics = forms.MultipleChoiceField(label="同表附加指標", required=False,
        choices=[(key, value) for key, value in METRICS.items() if key != "formula"],
        help_text="資料表可同時顯示最多 4 個附加指標；不要重複選主要指標。")
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
    COMMON_FIELDS = ("start", "end", "months", "source")

    def common_fields(self):
        return [self[name] for name in self.COMMON_FIELDS]

    def advanced_fields(self):
        return [field for field in self.visible_fields() if field.name not in self.COMMON_FIELDS]

    def advanced_count(self):
        return sum(bool(field.value()) for field in self.advanced_fields())

    focus = forms.CharField(required=False, max_length=6000, widget=forms.HiddenInput)
    empty_months = forms.BooleanField(required=False, widget=forms.HiddenInput)
    empty_legacy_source = forms.BooleanField(required=False, widget=forms.HiddenInput)
    from .records import RECORD_SORTS
    records_sort = forms.ChoiceField(required=False, widget=forms.HiddenInput, choices=[('', '預設排序')] + [(prefix + key, RECORD_COLUMNS[key]) for key in RECORD_SORTS for prefix in ('', '-')])
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
        layout = kwargs.pop("reader_layout", "standard")
        super().__init__(*args, **kwargs)
        if layout == "sales_overview":
            self.COMMON_FIELDS = ("legacy_source", "months")
            self.fields["legacy_source"].label = "銷售來源"
            self.fields["months"].label = "領牌年月"
        for index in range(8):
            self.fields[f"grain_{index}"] = forms.ChoiceField(required=False, widget=forms.HiddenInput,
                choices=[("", "依整頁設定"), ("year", "按年"), ("month", "按月"), ("day", "按日")])
            self.fields[f"sort_{index}"] = forms.ChoiceField(required=False, widget=forms.HiddenInput,
                choices=[("", "依原設計"), ("key", "分類順序"), ("key_desc", "分類倒序"), ("value", "數值遞減"), ("value_asc", "數值遞增")])
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
