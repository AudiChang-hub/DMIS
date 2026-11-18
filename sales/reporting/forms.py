import re

from django import forms
from django.forms import formset_factory

from sales.models import SalesOrder, SalesSource, VehicleModel
from .engine import CHARTS, DIMENSIONS, METRICS, NAVIGATION_GROUPS, SCOPE_LABELS, MODEL_TEXT_SCOPES, formula_tree, validate_scope
from .records import RECORD_COLUMNS, DEFAULT_RECORD_COLUMNS
from .source_compatibility import SOURCE_CLASSIFICATIONS, MODEL_PRESENCE, SOURCE_ENERGIES, source_type_to_classifications
from .tree_filter import TREE_FIELDS, per_model_slots, tree_chips

# T-164：沿用原 Excel 報表的比對條件與分類，只在設計器分組與改顯示名稱，鍵值與讀者頁不變。
# 銷售來源（T-183）已是主要來源條件，不再收在原 Excel 比對區。
LEGACY_SCOPES = {"model_presence", *MODEL_TEXT_SCOPES}
COMMON_DIMENSIONS = ("month", "year", "day", "brand", "family", "model", "color", "energy", "legacy_energy",
                     "legacy_motor_type", "source_type", "source", "recipient")
# T-189：設計器不知道最後的固定條件，車行／平台名稱一律顯示中性名稱。
DESIGNER_DIMENSION_LABELS = {"legacy_motor_type": "車種類別（白牌、綠牌、速克達…）", "legacy_dealer": "車行／平台"}


def designer_dimension_choices():
    """設計器的「依什麼分」選單：常用在前，原報表分類另成一組；值與 DIMENSIONS 完全相同。"""
    label = lambda key: DESIGNER_DIMENSION_LABELS.get(key, DIMENSIONS[key].replace("（比對用）", ""))
    common = [key for key in COMMON_DIMENSIONS if key in DIMENSIONS]
    common += [key for key in DIMENSIONS if key not in common and "比對用" not in DIMENSIONS[key]]
    legacy = [key for key in DIMENSIONS if key not in common]
    return [("常用", [(key, label(key)) for key in common]), ("沿用原 Excel 報表的分類", [(key, label(key)) for key in legacy])]


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
            if key == "source_type" and not scope.get(key):
                # T-183：來源類型併入銷售來源；只有舊設定已用到時才顯示，避免重新儲存變成不限。
                continue
            if key in MODEL_TEXT_SCOPES:
                self.fields["fixed_" + key] = forms.CharField(label=label, required=False, max_length=20200,
                    widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}), help_text=("區分大小寫；任何一項完整符合即排除。" if key == "model_exclude"
                    else "區分大小寫；同欄任一項符合即可，不同欄取交集。"))
                self.initial["fixed_" + key] = "\n".join(scope.get(key, []))
                continue
            options = list(choices[key])
            known = {value for value, _ in options}
            # 保留已刪除主檔的固定限制；重新開啟儲存不可變成不限。
            options.extend((value, f"已移除項目 #{value}") for value in scope.get(key, []) if value not in known)
            self.fields["fixed_" + key] = forms.MultipleChoiceField(label=label, choices=options, required=False)
            self.initial["fixed_" + key] = scope.get(key, [])
        if "fixed_source" in self.fields:
            # T-235：「車行／平台」依網路平台、本店、縣市、未分區分組；只改顯示，值不變。
            from sales.services.dealer_regions import group_mixed_choices
            sources = {str(pk): (kind, city) for pk, kind, city in SalesSource.objects.values_list("pk", "source_type", "city")}
            self["fixed_source"].regions = group_mixed_choices(
                self.fields["fixed_source"].choices, lambda value: sources.get(value, ("", ""))[0],
                lambda value: sources.get(value, ("", ""))[1])

    def primary_fields(self):
        return [field for field in self.visible_fields() if not field.name.startswith("fixed_")]

    def scope_fields(self):
        return [self["fixed_" + key] for key in SCOPE_LABELS if "fixed_" + key in self.fields]

    # T-164 設計器分組顯示：常用條件在前，原 Excel 報表比對條件收進「進階」；不影響驗證與儲存格式。
    def common_scope_fields(self):
        return [field for field in self.scope_fields() if field.name.removeprefix("fixed_") not in LEGACY_SCOPES]

    def legacy_scope_fields(self):
        return [field for field in self.scope_fields() if field.name.removeprefix("fixed_") in LEGACY_SCOPES]

    def legacy_scope_used(self):
        return any(field.value() for field in self.legacy_scope_fields())

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
    from .reader_layouts import READER_LAYOUTS
    reader_layout = forms.ChoiceField(label="閱讀版型", required=False, choices=list(READER_LAYOUTS.items()))

    def clean_reader_layout(self):
        return self.cleaned_data["reader_layout"] or "standard"

    title = forms.CharField(label="報表名稱", max_length=100, widget=forms.TextInput(attrs={"class": "designer-title-input"}))
    description = forms.CharField(label="報表說明", required=False, max_length=1000, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))
    audience = forms.ChoiceField(label="開放給", choices=[("admin", "只有我（admin）"), ("team", "所有已登入的內部帳號")])
    date_basis = forms.ChoiceField(label="用哪個日期統計", choices=[("registration_date", "領牌日期"), ("established_on", "訂單成立日期"), ("order_date", "訂單版本日期")])
    include_undated = forms.BooleanField(label="未選期間時包含尚未領牌訂單", required=False,
        help_text="僅影響本報表分析；日期未填寫另列，不計入任何月份。指定期間或月份時仍排除未填日期。")
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    navigation_group = forms.ChoiceField(label="報表中心分組", choices=NAVIGATION_GROUPS.items(), required=False,
        initial="custom")  # T-165：未設定時讀取端視為自訂報表；不可預設停在第一項「銷售統計」，否則沒改就存檔會換組
    page_order = forms.IntegerField(label="分組內順序（小的在前）", min_value=0, max_value=999, required=False)
    include_records = forms.BooleanField(label="顯示來源訂單明細表", required=False)
    records_columns = forms.MultipleChoiceField(label="明細顯示欄位", choices=RECORD_COLUMNS.items(), initial=DEFAULT_RECORD_COLUMNS,
        required=False, widget=forms.CheckboxSelectMultiple)
    records_mode = forms.ChoiceField(label="附表方式", choices=[("orders", "逐筆訂單（自選欄位）"), ("population", "車色／車主／性別分組（含證號，僅 admin）")], required=False)
    records_page_size = forms.TypedChoiceField(label="明細每頁筆數", choices=[(10, "10 筆"), (25, "25 筆"), (50, "50 筆"), (100, "100 筆")],
        coerce=int, initial=10, required=False, empty_value=10)

    def primary_fields(self):
        return [field for field in super().primary_fields() if field.name != "include_records" and not field.name.startswith("records_")]

    HEAD_FIELDS = ("title", "audience", "navigation_group", "date_basis")

    def settings_fields(self):
        """設計器頂列以外、收在「其他報表設定」的欄位。"""
        return [field for field in self.primary_fields() if field.name not in self.HEAD_FIELDS]

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
    font_size = forms.TypedChoiceField(label="圖表文字大小", choices=[(0, "依原版型"), (16, "16 px"), (18, "18 px"), (20, "20 px"), (24, "24 px")], coerce=int, required=False, empty_value=0)
    title_align = forms.ChoiceField(label="標題對齊", choices=[("", "依原版型"), ("left", "靠左"), ("center", "置中"), ("right", "靠右")], required=False)
    palette = forms.ChoiceField(label="分類配色", choices=[("", "原報表配色"), ("accessible", "高辨識對比色")], required=False,
        help_text="同一分類在圖形、圖例與滑入提示保持同色；不更動原始資料。")
    show_legend = forms.ChoiceField(label="圖例", choices=[("", "顯示（依原版型）"), ("hide", "隱藏")], required=False,
        help_text="適用圓餅與堆疊圖。隱藏圖例仍可滑入查看分類與數字。")
    show_tooltip = forms.ChoiceField(label="滑入提示", choices=[("", "顯示數字與分類"), ("hide", "不顯示浮動提示")], required=False)
    per_model = forms.BooleanField(label="依勾選車型各一張圖（大數據分析）", required=False,
        help_text="只用於大數據分析群組、且報表只有這一張圖：依讀者在「車型篩選」勾選的車型，每款一張圖，依品牌、車型名稱排列，勾幾款就出幾張。")
    cross_filter = forms.ChoiceField(label="點選圖形", choices=[("", "依報表既有方式連動"), ("off", "僅查看，不連動")], required=False,
        help_text="互動預覽可實際試選；關閉連動不影響其他圖表或來源明細入口。")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        explanations = {
            "width": "半寬可與下一張並排；全寬獨占一列。窄螢幕依正式版型調整。",
            "height": "320–1200 px，設定最小高度；文字或資料較多會自然延伸，不裁切內容。",
            "chart": "長條比數量、圓環看占比、折線看趨勢、堆疊看組成、資料表看數字。",
            "dimension": "每一根長條（或每一列）代表什麼，例如月份、品牌、車行。",
            "metric": "傭金與獎金沿用 DMIS 既有結果，這裡不會重新計算。",
            "limit": "1–200。只限制顯示幾項，超出時圖上會提示。",
            "sort": "看趨勢選日期順序；看排行選數值由高到低。",
            "font_size": "只調整此圖文字；畫布縮放則是整頁等比例縮放，兩者不同。",
            "title_align": "覆寫此圖標題位置；選依原版型即可維持原報表習慣。",
        }
        for name, explanation in explanations.items():
            self.fields[name].help_text = explanation
        self.fields["title"].help_text = ""
        self.fields["dimension"].choices = designer_dimension_choices()
        self.fields["series"].choices = [("", "不細分"), *designer_dimension_choices()]

    BASIC_FIELDS = ("title", "chart", "metric", "formula", "dimension", "series", "sort", "limit")

    def basic_fields(self):
        """右側面板常用設定：依「圖表類型 → 看什麼 → 依什麼分 → 排序」的問句順序。"""
        return [self[name] for name in self.BASIC_FIELDS]

    def advanced_fields(self):
        return [field for field in self.primary_fields() if field.name not in self.BASIC_FIELDS and field.name not in ("DELETE", "ORDER")]

    width = forms.TypedChoiceField(label="圖表寬度", choices=[(6, "半寬（並排）"), (12, "全寬")], coerce=int, required=False, empty_value=6, initial=6)
    height = forms.IntegerField(label="圖表高度（像素）", min_value=320, max_value=1200, required=False, initial=520)

    def clean_height(self):
        return self.cleaned_data.get("height") or 520

    title = forms.CharField(label="圖表名稱", max_length=100)
    chart = forms.ChoiceField(label="圖表類型", choices=CHARTS.items())
    dimension = forms.ChoiceField(label="依什麼分", choices=DIMENSIONS.items())
    series = forms.ChoiceField(label="再細分", choices=[("", "不細分"), *DIMENSIONS.items()], required=False,
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
    limit = forms.IntegerField(label="最多顯示幾項", min_value=1, max_value=200, initial=20)
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

    def clean_additional_metrics(self):
        # T-165 根因：多選清單依選單順序送出（count、sale_total…、dealer_commission、dealer_bonus），
        # 存回時會把台數統計的「台數獎金、傭金」重排成「傭金、台數獎金」，表格兩欄因此對調。
        # 與 records_columns 相同：保留已存的順序，新勾選的依選單順序接在後面。
        selected = self.cleaned_data["additional_metrics"]
        existing = self.initial.get("additional_metrics") or []
        return [key for key in existing if key in selected] + [key for key in selected if key not in existing]


class ModelSelectionField(forms.MultipleChoiceField):
    """樹狀篩選的車型主檔 pk（T-151）；已不在範圍的舊網址值只會查不到，不讓整份報表出錯。"""
    def valid_value(self, value):
        return str(value).isdigit()


CardFormSet = formset_factory(CardForm, extra=0, min_num=0, max_num=8, absolute_max=8,
                              validate_min=True, validate_max=True, can_delete=True, can_order=True)


class FilterForm(forms.Form):
    COMMON_FIELDS = ("start", "end", "months", "source")

    def common_fields(self):
        return [self[name] for name in self.COMMON_FIELDS]

    def advanced_fields(self):
        return [field for field in self.visible_fields() if field.name not in self.COMMON_FIELDS and field.name not in TREE_FIELDS]

    def advanced_count(self):
        return sum(bool(field.value()) for field in self.advanced_fields())

    def month_tree(self):
        """領牌年月樹狀（T-212）：年 → 月，最新年份在上；月份仍是 name="months" 的勾選框，送出參數不變。"""
        if "months" not in self.fields:
            return []
        selected = {str(value) for value in (self["months"].value() or [])}
        years = {}
        for value, label in self.fields["months"].choices:
            years.setdefault(str(value)[:4], []).append({
                "value": value, "label": label, "month": str(label).split("年", 1)[-1].strip(), "checked": value in selected,
            })
        tree = []
        for year, months in years.items():
            checked = sum(month["checked"] for month in months)
            state = "true" if checked == len(months) else "mixed" if checked else "false"
            tree.append({"year": year, "months": months, "checked": checked, "state": state})
        return tree

    def month_chip_values(self, values):
        """已選月份的標籤文字（T-212）：某年可選的月份全勾就寫「2026 全年」，其餘照原本逐月 2026/09。"""
        by_year = {}
        for choice, _label in self.fields["months"].choices:
            by_year.setdefault(str(choice)[:4], set()).add(str(choice))
        chosen = {str(value) for value in values}
        result, done = [], set()
        for value in map(str, values):
            year = value[:4]
            if by_year.get(year) and by_year[year] <= chosen:
                if year not in done:
                    result.append(f"{year} 全年")
                    done.add(year)
                continue
            result.append(value.replace("-", "/"))
        return result

    def active_filters(self, extra=None, tree=None):
        """目前套用的讀者篩選（T-142）：每項附移除網址，其餘條件與圖表連動保留。

        網址即狀態；移除後仍走同一報表網址，重新整理或分享都一致。只列讀者可調整的欄位，
        報表固定範圍與圖表點選（focus）各有自己的顯示與移除方式。
        """
        if not self.is_valid():
            return [], ""
        from urllib.parse import urlencode
        data = self.cleaned_data
        extra_query = urlencode(extra) if extra else ""

        def query(*names, **overrides):
            kept = urlencode({key: value for key, value in {**data, **overrides}.items()
                              if key not in names and value and not key.startswith("_")}, doseq=True)
            return "&".join(part for part in (kept, extra_query) if part)

        def label(name):
            return re.sub(r"（[^（）]*）$", "", str(self.fields[name].label or name))

        def summary(values):
            values = [str(value) for value in values]
            return "、".join(values) if len(values) <= 3 else "、".join(values[:3]) + f" 等 {len(values)} 項"

        items, removable = [], []
        for field in [*self.common_fields(), *self.advanced_fields()]:
            name = field.name
            if name in ("start", "end"):
                if "start" in removable:
                    continue
                start, end = data.get("start"), data.get("end")
                if not (start or end):
                    removable.append("start")
                    continue
                text = (f"{start:%Y/%m/%d}～{end:%Y/%m/%d}" if start and end
                        else f"{start:%Y/%m/%d} 起" if start else f"至 {end:%Y/%m/%d}")
                items.append({"label": "期間", "value": text, "title": text, "remove_query": query("start", "end")})
                removable += ["start", "end"]
                continue
            value = data.get(name)
            empty_flag = f"empty_{name}"
            if empty_flag in self.fields and data.get(empty_flag):
                text = "未選取（不顯示資料）"
                items.append({"label": label(name), "value": text, "title": text, "remove_query": query(name, empty_flag)})
                removable += [name, empty_flag]
                continue
            if not value:
                continue
            choices = dict((str(key), text) for key, text in getattr(self.fields[name], "choices", []))
            if name == "months":
                values = self.month_chip_values(value)
            elif isinstance(value, (list, tuple)):
                values = [choices.get(str(item), str(item)) for item in value]
            else:
                values = [choices.get(str(value), str(value))]
            items.append({"label": label(name), "value": summary(values), "title": "、".join(values),
                          "remove_query": query(name, empty_flag)})
            removable += [name, empty_flag]
        if "model" in self.fields:
            # 樹狀篩選（T-151）：每個有限制的品牌一個標籤，移除＝該品牌恢復全選。
            for chip in tree_chips(tree, data) if tree else []:
                items.append({"label": chip["label"], "value": chip["value"], "title": chip["title"],
                              "remove_query": query("empty_model", model=chip["model"])})
            removable += list(TREE_FIELDS)
        return items, query(*removable)

    focus = forms.CharField(required=False, max_length=6000, widget=forms.HiddenInput)
    empty_months = forms.BooleanField(required=False, widget=forms.HiddenInput)
    empty_legacy_source = forms.BooleanField(required=False, widget=forms.HiddenInput)
    empty_legacy_dealer = forms.BooleanField(required=False, widget=forms.HiddenInput)
    from .records import RECORD_SORTS
    records_sort = forms.ChoiceField(required=False, widget=forms.HiddenInput, choices=[('', '預設排序')] + [(prefix + key, RECORD_COLUMNS[key]) for key in RECORD_SORTS for prefix in ('', '-')])
    grain = forms.ChoiceField(label="日期圖表層級", required=False, choices=[("", "依原設計"), ("year", "按年"), ("month", "按月"), ("day", "按日")])
    start = forms.DateField(label="開始日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="結束日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    months = forms.MultipleChoiceField(label="月份（可複選）", required=False)
    brand = forms.MultipleChoiceField(label="品牌", required=False)
    energy = forms.MultipleChoiceField(label="能源別", required=False, choices=VehicleModel.EnergyType.choices)
    # T-183：來源類型併入銷售來源；舊網址的 source_type 在 __init__ 換算，不再提供勾選。
    source = forms.MultipleChoiceField(label="車行／平台", required=False)
    legacy_source = forms.MultipleChoiceField(label="銷售來源", required=False, choices=[(label, label) for label in SOURCE_CLASSIFICATIONS])
    # T-191：進階篩選固定叫「車行／平台」，不依固定條件改名，避免和上方「車行」「平台」選單同名。
    legacy_dealer = forms.MultipleChoiceField(label="車行／平台", required=False)
    legacy_energy = forms.MultipleChoiceField(label="油車／電車", required=False, choices=[(label, label) for label in SOURCE_ENERGIES])

    def __init__(self, *args, **kwargs):
        self.date_basis = kwargs.pop("date_basis", "registration_date")
        layout = kwargs.pop("reader_layout", None)
        config = kwargs.pop('config', None)
        tree_filter = kwargs.pop('tree_filter', False)
        layout = layout or (config or {}).get('reader_layout', 'standard')
        super().__init__(*args, **kwargs)
        if tree_filter:
            # 大數據分析群組（T-151）：品牌、能源別由樹狀篩選取代，改用車型主檔勾選。
            self.fields.pop("brand")
            self.fields.pop("energy")
            self.fields["model"] = ModelSelectionField(label="車型", required=False)
            self.fields["empty_model"] = forms.BooleanField(required=False, widget=forms.HiddenInput)
        if layout in ("sales_overview", "electric_overview", "gasoline_overview"):
            self.COMMON_FIELDS = ("legacy_source", "months")
            self.fields["months"].label = "領牌年月"
        if layout in ('platform_overview', 'dealer_overview', 'count_overview'):
            self.COMMON_FIELDS = ('legacy_dealer', 'months')
            self.fields['months'].label = '領牌年月'
        if layout == 'analysis_overview':
            self.COMMON_FIELDS = ('months',)
            self.fields['months'].label = '領牌年月'
        # 每圖的日期層級／排序；依車種展開的報表（T-240）圖卡可超過 8 張。
        for index in range(per_model_slots(config)):
            self.fields[f"grain_{index}"] = forms.ChoiceField(required=False, widget=forms.HiddenInput,
                choices=[("", "依整頁設定"), ("year", "按年"), ("month", "按月"), ("day", "按日")])
            self.fields[f"sort_{index}"] = forms.ChoiceField(required=False, widget=forms.HiddenInput,
                choices=[("", "依原設計"), ("key", "分類順序"), ("key_desc", "分類倒序"), ("value", "數值遞減"), ("value_asc", "數值遞增")])
        # 舊版單選空字串仍表示全部；QueryDict 保留多值，不轉成普通 dict。
        if self.is_bound and hasattr(self.data, "getlist"):
            self.data = self.data.copy()
            for key in ("months", "brand", "energy", "source_type", "source", "legacy_source", "legacy_dealer", "model"):
                self.data.setlist(key, [value for value in self.data.getlist(key) if value])
            self._convert_source_type()
        if "brand" in self.fields:
            self.fields["brand"].choices = [(name, name) for name in VehicleModel.objects.order_by("brand").values_list("brand", flat=True).distinct()]
        sources = list(SalesSource.objects.order_by("name", "pk").values_list("pk", "name", "source_type"))
        self.fields["source"].choices = [(str(pk), name) for pk, name, _ in sources]
        from .engine import base_query
        from .source_compatibility import source_dealer_query
        choice_config = config or {'date_basis': self.date_basis, 'include_undated': True}
        dealer_pairs = list(source_dealer_query(base_query(choice_config, {})).order_by('report_dealer_label')
            .values_list('report_dealer_label', 'source_type').distinct())
        self.fields['legacy_dealer'].choices = [(name, name) for name in dict.fromkeys(name for name, _ in dealer_pairs)]
        self.fields["months"].choices = [(month.strftime("%Y-%m"), month.strftime("%Y 年 %m 月"))
            for month in SalesOrder.objects.dates(self.date_basis, "month", order="DESC")]
        # 固定能源範圍仍由 engine 套用；移除讀者控制項與舊網址殘留限制。
        self.fields.pop('legacy_energy')
        if layout != 'standard':
            self.fields.pop('source')
            self.fields['legacy_dealer'].label = '車行／平台'
            self._split_legacy_dealer(dealer_pairs)
        else:
            self._split_source(sources)
            self._group_mixed_legacy_dealer(dealer_pairs)

    def _convert_source_type(self):
        """舊網址的來源類型（T-183）換算成銷售來源；與已選的銷售來源取交集，結果與原條件相同。"""
        types = [value for value in self.data.getlist("source_type") if value in SalesOrder.SourceType.values]
        self.data.setlist("source_type", [])
        if not types:
            return
        mapped = source_type_to_classifications(types)
        current = self.data.getlist("legacy_source")
        selected = [label for label in mapped if label in current] if current else mapped
        self.data.setlist("legacy_source", selected)
        if not selected:
            self.data["empty_legacy_source"] = "1"

    def _attach_split(self, name, groups):
        """車行／平台拆成兩個選擇器（T-184）：同一個網址參數，兩邊都選取聯集；沒有選項的一邊不顯示。"""
        groups = [(label, suffix, choices) for label, suffix, choices in groups if choices]
        listed = {value for _, _, choices in groups for value, _ in choices}
        selected = set(self.data.getlist(name) if hasattr(self.data, "getlist") else self.data.get(name) or [])
        # 已選但不屬於任一邊的舊值（例如本店來源）放進第一個選擇器，避免下次送出時默默遺失。
        extra = [(value, text) for value, text in self.fields[name].choices if value in selected and value not in listed]
        if groups and extra:
            # 放進第一個非「本店」的選擇器（T-230），本店組只列馭盛、永湛。
            index = next((i for i, group in enumerate(groups) if group[1] != "store"), 0)
            label, suffix, choices = groups[index]
            groups[index] = (label, suffix, [*choices, *extra])
        if groups:
            self[name].split_groups = [{"label": label, "id": f"id_{name}_{suffix}", "choices": choices}
                                      for label, suffix, choices in groups]

    def _split_source(self, sources):
        from sales.services.home_stores import home_store_labels
        home = home_store_labels()
        # 本店（T-230）：馭盛、永湛固定放最上面一組，和車行分開；只是篩選，不牽動任何計算。
        home_choices = sorted(((str(pk), name) for pk, name, kind in sources
                               if kind == SalesSource.SourceType.STORE and name in home), key=lambda item: home.index(item[1]))
        self._attach_split("source", [
            ("本店", "store", home_choices),
            ("車行", "dealer", [(str(pk), name) for pk, name, kind in sources if kind == SalesSource.SourceType.DEALER]),
            ("平台", "platform", [(str(pk), name) for pk, name, kind in sources if kind == SalesSource.SourceType.PLATFORM]),
        ])
        from sales.services.dealer_regions import dealer_city_by_pk
        cities = dealer_city_by_pk()
        self._group_dealer_regions("source", lambda value: cities.get(int(value)) if str(value).isdigit() else "")

    def _split_legacy_dealer(self, pairs):
        kinds = {}
        for label, source_type in pairs:
            kinds.setdefault(label, set()).add(source_type)
        # 同一標籤橫跨多種來源時，平台優先、其次車行；只出現在本店單的標籤用「銷售來源」篩。
        group = {label: "platform" if "platform" in types else "dealer" if "dealer" in types else "store" for label, types in kinds.items()}
        choices = self.fields["legacy_dealer"].choices
        from sales.services.home_stores import home_store_labels
        home = home_store_labels()
        # 本店（T-230）：只出現在本店單的「馭盛」「永湛」固定放最上面一組，和車行分開。
        home_choices = sorted(((value, text) for value, text in choices if group.get(value) == "store" and value in home),
                              key=lambda item: home.index(item[0]))
        self._attach_split("legacy_dealer", [
            ("本店", "store", home_choices),
            ("車行", "dealer", [(value, text) for value, text in choices if group.get(value) == "dealer"]),
            ("平台", "platform", [(value, text) for value, text in choices if group.get(value) == "platform"]),
        ])
        from sales.services.dealer_regions import dealer_city_by_report_label, report_label_key
        cities = dealer_city_by_report_label()
        self._group_dealer_regions("legacy_dealer", lambda value: cities.get(report_label_key(value), ""))

    def _group_mixed_legacy_dealer(self, pairs):
        """標準版型進階篩選的「車行／平台」混合清單分組（T-235）：網路平台、本店在上，車行依縣市，其餘未分區。
        同一標籤橫跨多種來源時與總覽版型相同：平台優先、其次車行。"""
        from sales.services.dealer_regions import dealer_city_by_report_label, group_mixed_choices, report_label_key
        kinds = {}
        for label, source_type in pairs:
            kinds.setdefault(label, set()).add(source_type)
        kind = {label: "platform" if "platform" in types else "dealer" if "dealer" in types else "store"
                for label, types in kinds.items()}
        cities = dealer_city_by_report_label()
        self["legacy_dealer"].regions = group_mixed_choices(
            self.fields["legacy_dealer"].choices, kind.get, lambda value: cities.get(report_label_key(value), ""))

    def _group_dealer_regions(self, name, city_of):
        """「車行」選擇器依區域分組（T-234）：沿用車行聯絡資料的縣市順序，對不到車行主檔的歸「未分區」。只改顯示，值不變。"""
        from sales.services.dealer_regions import group_choices
        for group in getattr(self[name], "split_groups", None) or []:
            if group["id"].endswith("_dealer"):
                group["regions"] = group_choices(group["choices"], city_of)

    def clean(self):
        data = super().clean()
        from .cross_filter import selections
        selections(data.get("focus"))
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("開始日期不可晚於結束日期。")
        if len(data.get("months", [])) > 120:
            raise forms.ValidationError("一次最多選擇 120 個月份；全部期間請清除月份選取。")
        if len(data.get("model") or []) > 500:
            raise forms.ValidationError("一次最多勾選 500 個車型；全部車型請勾選「總計」。")
        if len(data.get('legacy_dealer', [])) > 200:
            raise forms.ValidationError('一次最多選擇 200 個車行／平台。')
        return data
