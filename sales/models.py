import uuid
import re
import unicodedata
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from .themes import DEFAULT_THEME, THEME_CHOICES


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新時間")

    class Meta:
        abstract = True


def normalize_vehicle_identifier(value):
    """建立比對鍵；畫面仍保留使用者輸入的原始號碼。"""
    return re.sub(r"[\s-]+", "", value or "").upper() or None


def normalize_legacy_master_value(value):
    """歷史 Excel 主檔文字的穩定比對鍵；原始文字仍完整保留。"""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def _is_dr_z4sm_value(value):
    """辨識已確認為同一機種／型號的 DR-Z4SM 歷史寫法。"""
    key = normalize_legacy_master_value(value).replace("（", "(").replace("）", ")")
    compact = re.sub(r"[-_]", "", key)
    return compact in {"drz4sm", "drz4sm(滑胎版)"}


def _is_dr_z4s_model_number(value):
    """辨識 DR-Z4S 越野版原廠型號的歷史連字號寫法。"""
    key = normalize_legacy_master_value(value)
    compact = re.sub(r"[-_]", "", key)
    return compact == "drz4s"


def _is_gsx250f_model_number(value):
    """辨識 GIXXER SF 250 已確認為同一型號的歷史冗長寫法。"""
    key = normalize_legacy_master_value(value)
    compact = re.sub(r"[-_]", "", key)
    return compact in {"gsx250f", "gsx250fgixxersf250"}


def canonical_vehicle_model_name(value):
    """將已確認為同一機種的歷史名稱收斂成日常使用名稱。"""
    name = str(value or "").strip()
    if _is_dr_z4sm_value(name):
        return "DR-Z4SM (滑胎版)"
    return name


def canonical_vehicle_model_number(value):
    """統一已確認為同一原廠型號的連字號寫法。"""
    number = str(value or "").strip()
    if _is_dr_z4sm_value(number):
        return "DR-Z4SM"
    if _is_dr_z4s_model_number(number):
        return "DR-Z4S"
    if _is_gsx250f_model_number(number):
        return "GSX250F"
    return number


def normalize_vehicle_model_master_value(value):
    """車型主檔與歷史匯入共用比對鍵。"""
    if _is_dr_z4sm_value(value):
        return normalize_legacy_master_value("DR-Z4SM")
    if _is_dr_z4s_model_number(value):
        return normalize_legacy_master_value("DR-Z4S")
    if _is_gsx250f_model_number(value):
        return normalize_legacy_master_value("GSX250F")
    return normalize_legacy_master_value(value)


class TaiwanCounty(models.TextChoices):
    TAIPEI = "臺北市", "臺北市"
    NEW_TAIPEI = "新北市", "新北市"
    TAOYUAN = "桃園市", "桃園市"
    TAICHUNG = "臺中市", "臺中市"
    TAINAN = "臺南市", "臺南市"
    KAOHSIUNG = "高雄市", "高雄市"
    KEELUNG = "基隆市", "基隆市"
    HSINCHU_CITY = "新竹市", "新竹市"
    CHIAYI_CITY = "嘉義市", "嘉義市"
    HSINCHU_COUNTY = "新竹縣", "新竹縣"
    MIAOLI = "苗栗縣", "苗栗縣"
    CHANGHUA = "彰化縣", "彰化縣"
    NANTOU = "南投縣", "南投縣"
    YUNLIN = "雲林縣", "雲林縣"
    CHIAYI_COUNTY = "嘉義縣", "嘉義縣"
    PINGTUNG = "屏東縣", "屏東縣"
    YILAN = "宜蘭縣", "宜蘭縣"
    HUALIEN = "花蓮縣", "花蓮縣"
    TAITUNG = "臺東縣", "臺東縣"
    PENGHU = "澎湖縣", "澎湖縣"
    KINMEN = "金門縣", "金門縣"
    LIENCHIANG = "連江縣", "連江縣"


class Store(TimeStampedModel):
    name = models.CharField("門市名稱", max_length=100, unique=True)
    code = models.CharField("門市代碼", max_length=20, unique=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "門市"
        verbose_name_plural = "門市"

    def __str__(self):
        return self.name


class InstallmentCompany(TimeStampedModel):
    name = models.CharField("分期公司", max_length=120, unique=True)
    customer_service_phone = models.CharField("客服電話", max_length=50, blank=True)
    active = models.BooleanField("啟用中", default=True)
    note = models.TextField("內部備註", blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "分期公司"
        verbose_name_plural = "分期公司"

    def __str__(self):
        return self.name


class SalesSourceCategory(TimeStampedModel):
    class SystemBehavior(models.TextChoices):
        STORE = "store", "本店來源"
        DEALER = "dealer", "合作車行"
        PLATFORM = "platform", "網路平台"

    name = models.CharField("分類名稱", max_length=80, unique=True)
    system_behavior = models.CharField(
        "系統處理方式",
        max_length=20,
        choices=SystemBehavior.choices,
        default=SystemBehavior.STORE,
        help_text="決定是否套用車行傭金、平台對帳或視為本店來源。",
    )
    active = models.BooleanField("啟用中", default=True)
    note = models.CharField("內部備註", max_length=250, blank=True)

    class Meta:
        ordering = ["system_behavior", "name", "id"]
        verbose_name = "通路分類"
        verbose_name_plural = "通路分類"

    def __str__(self):
        return self.name


class VehicleBrand(TimeStampedModel):
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="sub_brands",
        verbose_name="所屬主品牌",
        blank=True,
        null=True,
        help_text="例如 eMOVING 所屬主品牌為 SUZUKI；交易仍保留 eMOVING 品牌名稱。",
    )
    name = models.CharField("品牌名稱", max_length=80)
    aliases = models.TextField(
        "別名／原廠寫法",
        blank=True,
        help_text="可用逗號、頓號或換行分隔，例如：台鈴、台鈴 Suzuki。",
    )
    display_order = models.PositiveSmallIntegerField("顯示順序", default=100)
    active = models.BooleanField("啟用中", default=True)
    note = models.CharField("內部備註", max_length=250, blank=True)
    logo = models.ImageField(
        "品牌 LOGO",
        upload_to="brands/logos/%Y/%m/",
        blank=True,
        help_text="品牌識別與列印文件使用；建議透明背景 PNG 或清晰橫式圖片。",
    )
    logo_original = models.ImageField(
        "品牌 LOGO 原圖",
        upload_to="brands/logo-originals/%Y/%m/",
        blank=True,
        editable=False,
    )
    logo_crop_data = models.JSONField(
        "品牌 LOGO 裁切設定",
        default=dict,
        blank=True,
        editable=False,
    )

    class Meta:
        ordering = ["display_order", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), name="unique_vehicle_brand_name_ci"
            )
        ]
        verbose_name = "車輛品牌"
        verbose_name_plural = "車輛品牌"

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if self.parent_id == self.pk and self.pk:
            errors["parent"] = "品牌不能隸屬於自己。"
        elif self.parent_id:
            parent = VehicleBrand.objects.filter(pk=self.parent_id).first()
            if parent and parent.parent_id:
                errors["parent"] = "所屬品牌必須是主品牌，不能建立三層品牌。"
        if self.pk and self.parent_id and self.sub_brands.exists():
            errors["parent"] = "此品牌已有子品牌，不能再改為其他品牌的子品牌。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def hierarchy_label(self):
        if self.parent_id:
            return f"{self.parent.name}｜{self.name}"
        return self.name


class SalesSource(TimeStampedModel):
    class SourceType(models.TextChoices):
        STORE = "store", "本店來源"
        DEALER = "dealer", "合作車行"
        PLATFORM = "platform", "網路平台"

    class StaffStore(models.TextChoices):
        YONGZHAN = "yongzhan", "永湛"
        YUSHENG = "yusheng", "馭盛"

    name = models.CharField("來源名稱", max_length=120)
    source_type = models.CharField(
        "系統處理方式", max_length=20, choices=SourceType.choices
    )
    category = models.ForeignKey(
        SalesSourceCategory,
        on_delete=models.PROTECT,
        related_name="sources",
        verbose_name="通路分類",
        blank=True,
        null=True,
    )
    code = models.CharField("來源代碼", max_length=40, blank=True)
    responsible_person = models.CharField("負責人", max_length=80, blank=True)
    phone = models.CharField("電話一", max_length=50, blank=True)
    phone_secondary = models.CharField("電話二", max_length=50, blank=True)
    mobile = models.CharField("手機", max_length=50, blank=True)
    staff_stores = models.JSONField(
        "所在店",
        default=list,
        blank=True,
        help_text="本店人員可同時隸屬永湛與馭盛。",
    )
    staff_commission = models.DecimalField(
        "傭金",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="每筆歸屬此銷售人員的基礎傭金；供後續人員傭金結算引用。",
    )
    other_contact = models.CharField("其他聯絡方式", max_length=250, blank=True)
    fax = models.CharField("傳真", max_length=50, blank=True)
    address = models.CharField("地址", max_length=250, blank=True)
    city = models.CharField(
        "縣市", max_length=20, choices=TaiwanCounty.choices, blank=True
    )
    district = models.CharField("行政區", max_length=20, blank=True)
    sym_vehicle_capacity = models.PositiveSmallIntegerField(
        "三陽排車容量", blank=True, null=True
    )
    suzuki_vehicle_capacity = models.PositiveSmallIntegerField(
        "台鈴油電共用排車容量", blank=True, null=True
    )
    holiday_gift = models.BooleanField(
        "列入年節送禮名單",
        default=False,
        help_text="勾選後可在車行列表一鍵篩選。",
    )
    has_line_group = models.BooleanField(
        "有 LINE 群組",
        default=False,
        help_text="只記錄是否有車行 LINE 群組；不會影響價格表提供對象。",
    )
    note = models.TextField("備註", blank=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["source_type", "name"]
        indexes = [
            models.Index(
                fields=["source_type", "city", "district", "active"],
                name="sales_src_region_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "name"], name="unique_sales_source_name"
            )
        ]
        verbose_name = "訂單來源"
        verbose_name_plural = "訂單來源"

    def __str__(self):
        return self.name

    @classmethod
    def next_general_source_code(cls, *, code_date=None):
        """依既有 N + 日期 + 兩碼序號規則產生下一個一般來源代碼。"""
        code_date = code_date or timezone.localdate()
        stem = f"N{code_date:%y%m%d}"
        used_suffixes = []
        for code in cls.objects.filter(code__startswith=stem).values_list(
            "code", flat=True
        ):
            match = re.fullmatch(rf"{re.escape(stem)}(\d{{2}})", code or "")
            if match:
                used_suffixes.append(int(match.group(1)))
        for suffix in range(max(used_suffixes, default=0) + 1, 100):
            return f"{stem}{suffix:02d}"
        raise ValidationError({"code": f"{stem} 當日來源代碼已用盡。"})

    @property
    def staff_store_labels(self):
        labels = dict(self.StaffStore.choices)
        return [labels[value] for value in self.staff_stores if value in labels]

    def clean(self):
        super().clean()
        from sales.services.taiwan_address import infer_taiwan_region, is_valid_district

        invalid_staff_stores = set(self.staff_stores or []) - set(self.StaffStore.values)
        if invalid_staff_stores:
            raise ValidationError({"staff_stores": "所在店包含無效選項。"})

        if self.category_id and self.source_type != self.category.system_behavior:
            self.source_type = self.category.system_behavior
        if self.source_type != self.SourceType.DEALER:
            self.has_line_group = False
        if self.source_type == self.SourceType.DEALER:
            self.city, self.district = infer_taiwan_region(self.address)
        if self.district and not self.city:
            raise ValidationError({"city": "填寫行政區前，請先選擇縣市。"})
        if self.city and not is_valid_district(self.city, self.district):
            raise ValidationError({"district": "行政區與所選縣市不一致。"})

    def save(self, *args, **kwargs):
        from sales.services.taiwan_address import infer_taiwan_region

        if self.category_id:
            self.source_type = self.category.system_behavior
        assigned_code = False
        if self.source_type == self.SourceType.PLATFORM and not self.code:
            self.code = self.next_general_source_code()
            assigned_code = True
        if self.source_type != self.SourceType.DEALER:
            self.has_line_group = False
        else:
            self.city, self.district = infer_taiwan_region(self.address)
        if assigned_code and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"code"}
        return super().save(*args, **kwargs)


class SalesSourcePlatformContact(TimeStampedModel):
    source = models.ForeignKey(
        SalesSource,
        on_delete=models.CASCADE,
        related_name="platform_contacts",
        verbose_name="網路平台",
    )
    contact_person = models.CharField("聯絡人", max_length=250)
    phone = models.CharField("電話", max_length=100, blank=True)
    extension = models.CharField("分機", max_length=50, blank=True)
    mobile = models.CharField("手機", max_length=100, blank=True)
    email = models.CharField("信箱", max_length=500, blank=True)
    note = models.TextField("補充資料", blank=True)
    active = models.BooleanField("啟用中", default=True)
    display_order = models.PositiveIntegerField("顯示順序", default=0)

    class Meta:
        ordering = ["source", "display_order", "id"]
        verbose_name = "網路平台聯絡窗口"
        verbose_name_plural = "網路平台聯絡窗口"

    def __str__(self):
        return f"{self.source.name}／{self.contact_person}"

    def clean(self):
        super().clean()
        if self.source_id and self.source.source_type != SalesSource.SourceType.PLATFORM:
            raise ValidationError({"source": "聯絡窗口只能設定在網路平台。"})


class VehicleModelFamily(TimeStampedModel):
    """市場上辨識的一個機種；年份、規格與原廠型號另行維護。"""

    brand = models.CharField("品牌", max_length=80)
    name = models.CharField("機種", max_length=120)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["brand", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("brand"),
                Lower("name"),
                name="unique_vehicle_model_family_ci",
            )
        ]
        verbose_name = "機種主檔"
        verbose_name_plural = "機種主檔"

    def __str__(self):
        return f"{self.brand}／{self.name}"

    def save(self, *args, **kwargs):
        self.brand = self.brand.strip()
        self.name = canonical_vehicle_model_name(self.name)
        return super().save(*args, **kwargs)


class VehicleModel(TimeStampedModel):
    class EnergyType(models.TextChoices):
        GAS = "gas", "油車"
        ELECTRIC = "electric", "電動車"
        LIGHT_ELECTRIC = "light_electric", "輕型電動車"
        MICRO_ELECTRIC = "micro_electric", "微型電動二輪車"

    class ModelType(models.TextChoices):
        DRUM = "drum", "鼓"
        HUB_FRONT_DRUM = "hub_front_drum", "輪轂前鼓"
        HUB_FRONT_DISC = "hub_front_disc", "輪轂前碟"
        FRONT_DISC_REAR_DRUM = "front_disc_rear_drum", "前碟後鼓"
        CBS_DRUM = "cbs_drum", "CBS鼓"
        CBS_DISC = "cbs_disc", "CBS碟"
        ABS_DISC = "abs_disc", "ABS碟"
        CBS_DUAL_DISC = "cbs_dual_disc", "CBS雙碟"
        ABS_DUAL_DISC = "abs_dual_disc", "ABS雙碟"
        DISC = "disc", "碟"
        ABS_TRIPLE_DISC = "abs_triple_disc", "ABS三碟"

    class ElectricRegistrationClass(models.TextChoices):
        LIGHT = "light", "輕型電動機車"
        HEAVY = "heavy", "重型電動機車"

    brand = models.CharField("廠牌", max_length=80)
    name = models.CharField("車型", max_length=120)
    family = models.ForeignKey(
        VehicleModelFamily,
        on_delete=models.PROTECT,
        related_name="versions",
        verbose_name="所屬機種",
        blank=True,
        null=True,
        editable=False,
    )
    model_number = models.CharField(
        "型號",
        max_length=120,
        blank=True,
        help_text="原廠型號或版本代碼；既有資料可暫時留空。",
    )
    energy_type = models.CharField("動力類型", max_length=20, choices=EnergyType.choices)
    model_year = models.PositiveSmallIntegerField(
        "年份",
        blank=True,
        null=True,
        help_text="既有車型可暫時留空；新建車型請填西元年份。",
    )
    model_code = models.CharField(
        "型式",
        max_length=40,
        choices=ModelType.choices,
        blank=True,
    )
    displacement_cc = models.PositiveSmallIntegerField(
        "排氣量（c.c.）",
        blank=True,
        null=True,
        help_text="油車領牌試算使用；電動車、輕型電動車與微型電動二輪車可留空。",
    )
    motor_power_kw = models.DecimalField(
        "馬達功率（kW）",
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="電動車、輕型電動車或微型電動二輪車選填；不會自動換算馬力。",
    )
    horsepower_hp = models.DecimalField(
        "馬力（HP）",
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="電動車、輕型電動車或微型電動二輪車選填；不會由 kW 自動換算。",
    )
    electric_registration_class = models.CharField(
        "電動車領牌級別",
        max_length=20,
        choices=ElectricRegistrationClass.choices,
        blank=True,
        help_text="電動車使用；輕型電動車會自動套用輕型級別，不會由馬達功率推算。",
    )
    base_dealer_commission = models.DecimalField(
        "基礎車行佣金",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    active = models.BooleanField("啟用中", default=True)
    factory_model_codes = models.ManyToManyField(
        "VehicleFactoryModelCode",
        related_name="versions",
        verbose_name="適用原廠型號",
        blank=True,
    )

    class Meta:
        ordering = ["brand", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "brand",
                    "name",
                    "model_number",
                    "model_year",
                    "model_code",
                ],
                name="unique_vehicle_model_variant",
            )
        ]
        verbose_name = "車型"
        verbose_name_plural = "車型"

    def __str__(self):
        details = [self.brand, self.name]
        if self.model_number:
            details.append(self.model_number)
        if self.model_year:
            details.append(str(self.model_year))
        if self.model_code:
            details.append(self.get_model_code_display())
        return "／".join(details)

    def clean(self):
        if self.energy_type == self.EnergyType.GAS and not self.displacement_cc:
            raise ValidationError(
                {"displacement_cc": "油車必須設定排氣量，才能自動試算領牌費用。"}
            )
        if self.energy_type == self.EnergyType.LIGHT_ELECTRIC:
            self.electric_registration_class = self.ElectricRegistrationClass.LIGHT
        elif self.energy_type != self.EnergyType.ELECTRIC:
            self.electric_registration_class = ""

    def save(self, *args, **kwargs):
        if self.energy_type == self.EnergyType.LIGHT_ELECTRIC:
            self.electric_registration_class = self.ElectricRegistrationClass.LIGHT
        elif self.energy_type != self.EnergyType.ELECTRIC:
            self.electric_registration_class = ""
        if self.brand and self.name:
            self.brand = self.brand.strip()
            self.name = canonical_vehicle_model_name(self.name)
            self.model_number = canonical_vehicle_model_number(self.model_number)
            family = VehicleModelFamily.objects.filter(
                brand__iexact=self.brand,
                name__iexact=self.name.strip(),
            ).first()
            if family is None:
                family = VehicleModelFamily.objects.create(
                    brand=self.brand,
                    name=self.name.strip(),
                    active=self.active,
                )
            self.family = family
        super().save(*args, **kwargs)
        if self.family_id and self.model_number:
            normalized_code = normalize_legacy_master_value(self.model_number)
            factory_code, created = VehicleFactoryModelCode.objects.get_or_create(
                family_id=self.family_id,
                normalized_code=normalized_code,
                defaults={"code": self.model_number.strip(), "active": True},
            )
            if not created and not factory_code.active:
                factory_code.active = True
                factory_code.save(update_fields=["active", "updated_at"])
            self.factory_model_codes.add(factory_code)


class VehicleFactoryModelCode(TimeStampedModel):
    family = models.ForeignKey(
        VehicleModelFamily,
        on_delete=models.PROTECT,
        related_name="factory_model_codes",
        verbose_name="機種",
    )
    code = models.CharField("原廠型號", max_length=120)
    normalized_code = models.CharField(
        "標準化原廠型號",
        max_length=160,
        editable=False,
    )
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["family", "code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["family", "normalized_code"],
                name="unique_factory_model_code_in_family",
            )
        ]
        verbose_name = "原廠型號"
        verbose_name_plural = "原廠型號"

    def save(self, *args, **kwargs):
        self.code = canonical_vehicle_model_number(self.code)
        self.normalized_code = normalize_vehicle_model_master_value(self.code)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.family}／{self.code}"


class VehiclePriceVersion(TimeStampedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="price_versions",
        verbose_name="車型",
    )
    suggested_price = models.DecimalField(
        "建議售價", max_digits=12, decimal_places=0, blank=True, null=True
    )
    suggested_price_includes_registration = models.BooleanField(
        "建議售價包含牌險",
        default=True,
        help_text="勾選表示此版本的建議售價已包含牌險；未勾選則依正式單據另收。",
    )
    cash_price = models.DecimalField(
        "現金價", max_digits=12, decimal_places=0, blank=True, null=True
    )
    announced_on = models.DateField("公告日期", default=timezone.localdate)
    effective_from = models.DateField("生效日期")
    effective_to = models.DateField("結束日期", blank=True, null=True)
    source_note = models.CharField("來源文件／說明", max_length=250, blank=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["vehicle_model", "-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle_model", "effective_from"],
                name="unique_vehicle_price_version_start",
            )
        ]
        indexes = [
            models.Index(
                fields=["vehicle_model", "effective_from"],
                name="vehicle_price_lookup",
            )
        ]
        verbose_name = "車型價格版本"
        verbose_name_plural = "車型價格版本"

    def clean(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "結束日期不可早於生效日期。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vehicle_model}／{self.effective_from:%Y/%m/%d}"


class InstallmentPlanVersion(TimeStampedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="installment_plan_versions",
        verbose_name="車型",
    )
    announced_on = models.DateField("公告日期", default=timezone.localdate)
    effective_from = models.DateField("生效日期")
    effective_to = models.DateField(
        "結束日期",
        blank=True,
        null=True,
        help_text="可留空，代表持續有效；訂單依訂單日期選用版本。",
    )
    note = models.TextField("備註", blank=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["vehicle_model", "-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle_model", "effective_from"],
                name="unique_installment_plan_version_start",
            )
        ]
        indexes = [
            models.Index(
                fields=["vehicle_model", "effective_from"],
                name="installment_plan_lookup",
            )
        ]
        verbose_name = "分期方案版本"
        verbose_name_plural = "分期方案版本"

    def clean(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "結束日期不可早於生效日期。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vehicle_model}／{self.effective_from:%Y/%m/%d}"


class InstallmentPlanOption(TimeStampedModel):
    class ExpectedDisbursementMethod(models.TextChoices):
        RATE = "rate", "按比例試算"
        FIXED = "fixed", "固定金額"
        MANUAL = "manual", "本單另填"

    version = models.ForeignKey(
        InstallmentPlanVersion,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="分期方案版本",
    )
    periods = models.PositiveSmallIntegerField(
        "期數", validators=[MinValueValidator(1)]
    )
    monthly_amount = models.DecimalField(
        "每期金額", max_digits=12, decimal_places=0, validators=[MinValueValidator(0)]
    )
    company = models.ForeignKey(
        InstallmentCompany,
        on_delete=models.PROTECT,
        related_name="plan_options",
        verbose_name="分期公司",
    )
    opening_fee = models.DecimalField(
        "開辦費", max_digits=12, decimal_places=0, default=0,
        validators=[MinValueValidator(0)]
    )
    expected_disbursement_rate = models.DecimalField(
        "預估撥款比例（%）",
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    expected_disbursement_method = models.CharField(
        "預估撥款方式",
        max_length=20,
        choices=ExpectedDisbursementMethod.choices,
        default=ExpectedDisbursementMethod.RATE,
        help_text="按比例以車款售價試算；固定金額直接帶入；特殊案件可選本單另填。",
    )
    expected_disbursement_fixed_amount = models.DecimalField(
        "固定預估撥款金額",
        max_digits=12,
        decimal_places=0,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )
    extra_disbursement_bonus = models.DecimalField(
        "額外撥款獎金",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="分期公司在基礎撥款外另給的獎金；會加進預估撥款總額。",
    )

    class Meta:
        ordering = ["periods", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "periods"],
                name="unique_installment_plan_periods",
            )
        ]
        verbose_name = "分期方案期數"
        verbose_name_plural = "分期方案期數"

    def __str__(self):
        return f"{self.version.vehicle_model}／{self.periods} 期／{self.company}"


class AccessoryProduct(TimeStampedModel):
    name = models.CharField("配件名稱", max_length=160, unique=True)
    sale_price = models.DecimalField(
        "配件售價", max_digits=12, decimal_places=0, default=0
    )
    labor_fee = models.DecimalField(
        "安裝工資", max_digits=12, decimal_places=0, default=0
    )
    cost = models.DecimalField(
        "參考成本",
        max_digits=12,
        decimal_places=0,
        blank=True,
        null=True,
        help_text="無法固定維護時可留空；此欄位不會顯示在客戶訂單。",
    )
    active = models.BooleanField("啟用中", default=True)
    note = models.CharField("內部備註", max_length=250, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "配件主檔"
        verbose_name_plural = "配件主檔"

    def __str__(self):
        return self.name


class SalesSourceBrandPolicy(TimeStampedModel):
    class CooperationScope(models.TextChoices):
        SYM = "sym", "三陽 SYM"
        SUZUKI_GAS = "suzuki_gas", "台鈴油車"
        SUZUKI_ELECTRIC = "suzuki_electric", "台鈴電車"

    SCOPE_LEGACY_BRANDS = {
        CooperationScope.SYM: "SYM",
        CooperationScope.SUZUKI_GAS: "SUZUKI／油車",
        CooperationScope.SUZUKI_ELECTRIC: "SUZUKI／電車",
    }

    source = models.ForeignKey(
        SalesSource,
        on_delete=models.CASCADE,
        related_name="brand_policies",
        verbose_name="來源",
    )
    brand = models.CharField(
        "歷史品牌值",
        max_length=80,
        help_text="保留舊資料相容；新設定請使用合作類別。",
    )
    cooperation_scope = models.CharField(
        "合作類別",
        max_length=30,
        choices=CooperationScope.choices,
        blank=True,
        null=True,
        help_text="目前只區分三陽、台鈴油車與台鈴電車。",
    )
    cooperates = models.BooleanField("有配合", default=True)
    commission_adjustment = models.DecimalField(
        "佣金加減額",
        max_digits=12,
        decimal_places=0,
        default=0,
        help_text="加碼請填正數，減少請填負數。",
    )
    effective_from = models.DateField("生效日期", default=timezone.localdate)
    effective_to = models.DateField("結束日期", blank=True, null=True)
    note = models.CharField("品牌合作備註", max_length=250, blank=True)

    class Meta:
        ordering = ["source", "brand", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "brand", "effective_from"],
                name="unique_source_brand_policy_start",
            ),
            models.UniqueConstraint(
                fields=["source", "cooperation_scope", "effective_from"],
                condition=Q(cooperation_scope__isnull=False),
                name="unique_source_scope_policy_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source", "brand", "effective_from"],
                name="source_brand_policy_lookup",
            ),
            models.Index(
                fields=["source", "cooperation_scope", "effective_from"],
                name="source_scope_policy_lookup",
            ),
        ]
        verbose_name = "通路品牌合作規則"
        verbose_name_plural = "通路品牌合作規則"

    def clean(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "結束日期不可早於生效日期。"})

    def save(self, *args, **kwargs):
        if self.cooperation_scope:
            self.brand = self.SCOPE_LEGACY_BRANDS[self.cooperation_scope]
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        label = self.get_cooperation_scope_display() if self.cooperation_scope else self.brand
        return f"{self.source}／{label}／{self.effective_from:%Y/%m/%d}"

    @property
    def price_list_label(self):
        if not self.cooperation_scope:
            return ""
        return f"{self.get_cooperation_scope_display()}價格表"


class SalesSourceCooperationProfile(TimeStampedModel):
    """車行目前的合作關係；與按日期生效的傭金版本分開保存。"""

    class RelationshipType(models.TextChoices):
        GENERAL = "general", "一般"
        EXCLUSIVE = "exclusive", "專銷"

    source = models.ForeignKey(
        SalesSource,
        on_delete=models.CASCADE,
        related_name="cooperation_profiles",
        verbose_name="合作車行",
    )
    cooperation_scope = models.CharField(
        "合作類別",
        max_length=30,
        choices=SalesSourceBrandPolicy.CooperationScope.choices,
    )
    cooperates = models.BooleanField("提供價格表／有合作", default=False)
    relationship_type = models.CharField(
        "關係類型",
        max_length=20,
        choices=RelationshipType.choices,
        default=RelationshipType.GENERAL,
    )
    note = models.TextField("合作備註", blank=True)

    class Meta:
        ordering = ["source", "cooperation_scope"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "cooperation_scope"],
                name="unique_source_cooperation_profile",
            )
        ]
        verbose_name = "車行合作資料"
        verbose_name_plural = "車行合作資料"

    def __str__(self):
        return f"{self.source}／{self.get_cooperation_scope_display()}"


class DealerVolumeBonusRule(TimeStampedModel):
    dealer = models.ForeignKey(
        SalesSource,
        on_delete=models.PROTECT,
        related_name="volume_bonus_rules",
        limit_choices_to={"source_type": SalesSource.SourceType.DEALER},
        verbose_name="合作車行",
    )
    brand = models.CharField("品牌", max_length=80)
    starts_on = models.DateField("統計開始日")
    ends_on = models.DateField("統計結束日")
    note = models.TextField("備註", blank=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["-starts_on", "dealer", "brand"]
        constraints = [
            models.UniqueConstraint(
                fields=["dealer", "brand", "starts_on", "ends_on"],
                name="unique_dealer_volume_bonus_period",
            )
        ]
        verbose_name = "車行台數獎金規則"
        verbose_name_plural = "車行台數獎金規則"

    def clean(self):
        if self.ends_on < self.starts_on:
            raise ValidationError({"ends_on": "統計結束日不可早於開始日。"})
        if self.dealer_id and self.dealer.source_type != SalesSource.SourceType.DEALER:
            raise ValidationError({"dealer": "台數獎金只能設定合作車行。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.dealer}／{self.brand}／{self.starts_on:%Y/%m/%d}"


class DealerVolumeBonusTier(TimeStampedModel):
    rule = models.ForeignKey(
        DealerVolumeBonusRule,
        on_delete=models.CASCADE,
        related_name="tiers",
        verbose_name="台數獎金規則",
    )
    minimum_quantity = models.PositiveSmallIntegerField(
        "最低台數", validators=[MinValueValidator(1)]
    )
    bonus_per_vehicle = models.DecimalField(
        "每台獎金",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ["minimum_quantity"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "minimum_quantity"],
                name="unique_volume_bonus_tier_quantity",
            )
        ]
        verbose_name = "台數獎金門檻"
        verbose_name_plural = "台數獎金門檻"

    def __str__(self):
        return f"{self.minimum_quantity} 台／每台 {self.bonus_per_vehicle:.0f} 元"


class DealerVolumeBonusSettlement(TimeStampedModel):
    rule = models.OneToOneField(
        DealerVolumeBonusRule,
        on_delete=models.PROTECT,
        related_name="settlement",
        verbose_name="台數獎金規則",
    )
    qualified_quantity = models.PositiveSmallIntegerField("符合台數", default=0)
    bonus_per_vehicle = models.DecimalField(
        "採用每台獎金", max_digits=12, decimal_places=0, default=0
    )
    expected_amount = models.DecimalField(
        "預計金額", max_digits=12, decimal_places=0, default=0
    )
    actual_amount = models.DecimalField(
        "實際金額", max_digits=12, decimal_places=0, default=0
    )
    adjustment_reason = models.TextField("金額調整原因", blank=True)
    settled_on = models.DateField("結算日期", default=timezone.localdate)
    settled_by = models.CharField("結算人員", max_length=150, blank=True)

    class Meta:
        ordering = ["-settled_on", "-id"]
        verbose_name = "車行台數獎金結算"
        verbose_name_plural = "車行台數獎金結算"

    def clean(self):
        if self.actual_amount != self.expected_amount and not self.adjustment_reason.strip():
            raise ValidationError({"adjustment_reason": "實際金額不同時必須填寫原因。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class DealerVolumeBonusAllocation(TimeStampedModel):
    settlement = models.ForeignKey(
        DealerVolumeBonusSettlement,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name="台數獎金結算",
    )
    order = models.ForeignKey(
        "SalesOrder",
        on_delete=models.PROTECT,
        related_name="dealer_volume_bonus_allocations",
        verbose_name="訂單",
    )
    amount = models.DecimalField(
        "分配金額", max_digits=12, decimal_places=0, default=0
    )

    class Meta:
        ordering = ["order__registration_date", "order_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["settlement", "order"],
                name="unique_volume_bonus_settlement_order",
            )
        ]
        verbose_name = "台數獎金逐單明細"
        verbose_name_plural = "台數獎金逐單明細"


class DealerVolumeBonusAdjustment(TimeStampedModel):
    settlement = models.ForeignKey(
        DealerVolumeBonusSettlement,
        on_delete=models.PROTECT,
        related_name="adjustments",
        verbose_name="台數獎金結算",
    )
    previous_amount = models.DecimalField(
        "調整前金額", max_digits=12, decimal_places=0
    )
    revised_amount = models.DecimalField(
        "調整後金額", max_digits=12, decimal_places=0
    )
    reason = models.TextField("調整原因")
    adjusted_by = models.CharField("調整人員", max_length=150)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "車行台數獎金調整紀錄"
        verbose_name_plural = "車行台數獎金調整紀錄"


class LegacyImportBatch(TimeStampedModel):
    class ImportType(models.TextChoices):
        OPERATIONS = "operations", "車輛進銷貨庫存表"
        CHANNELS = "channels", "車行／網路平台名冊"

    class Status(models.TextChoices):
        PREVIEW = "preview", "待確認"
        PROCESSING = "processing", "匯入中"
        COMPLETED = "completed", "已匯入"
        FAILED = "failed", "處理失敗"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_type = models.CharField("匯入類型", max_length=30, choices=ImportType.choices)
    status = models.CharField(
        "批次狀態", max_length=20, choices=Status.choices, default=Status.PREVIEW
    )
    source_file = models.FileField("來源檔案", upload_to="imports/%Y/%m/")
    original_filename = models.CharField("原始檔名", max_length=255)
    file_sha256 = models.CharField("SHA-256", max_length=64, db_index=True)
    file_size = models.PositiveBigIntegerField("檔案大小")
    source_sheets = models.JSONField("來源工作表", default=list)
    preview_summary = models.JSONField("預覽摘要", default=dict)
    result_summary = models.JSONField("匯入結果", default=dict)
    uploaded_by = models.CharField("上傳人員", max_length=150)
    confirmed_by = models.CharField("確認人員", max_length=150, blank=True)
    confirmed_at = models.DateTimeField("確認時間", blank=True, null=True)
    processing_job_id = models.CharField("背景工作編號", max_length=80, blank=True)
    processing_total = models.PositiveIntegerField("預計處理筆數", default=0)
    processing_completed = models.PositiveIntegerField("已處理筆數", default=0)
    processing_started_at = models.DateTimeField("開始匯入時間", blank=True, null=True)
    processing_finished_at = models.DateTimeField("結束匯入時間", blank=True, null=True)
    processing_heartbeat_at = models.DateTimeField("最後進度時間", blank=True, null=True)
    processing_error = models.TextField("背景匯入錯誤", blank=True)
    archived_by = models.CharField("封存人員", max_length=150, blank=True)
    archived_at = models.DateTimeField("封存時間", blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "歷史資料匯入批次"
        verbose_name_plural = "歷史資料匯入批次"


class LegacyImportRow(TimeStampedModel):
    class Action(models.TextChoices):
        CREATE = "create", "新增"
        UPDATE = "update", "更新"
        SKIP = "skip", "略過"
        EXCLUDE = "exclude", "不匯入"
        CONFLICT = "conflict", "衝突"
        ERROR = "error", "錯誤"

    batch = models.ForeignKey(
        LegacyImportBatch,
        on_delete=models.CASCADE,
        related_name="rows",
        verbose_name="匯入批次",
    )
    sheet_name = models.CharField("工作表", max_length=120)
    source_row = models.PositiveIntegerField("來源列號")
    fingerprint = models.CharField("內容指紋", max_length=64, db_index=True)
    natural_key = models.CharField("比對鍵", max_length=255, blank=True, db_index=True)
    action = models.CharField("預計動作", max_length=20, choices=Action.choices)
    raw_data = models.JSONField("來源原始資料", default=dict)
    mapped_data = models.JSONField("欄位映射結果", default=dict)
    messages = models.JSONField("檢核訊息", default=list)
    excluded = models.BooleanField("人工排除", default=False)
    manually_corrected = models.BooleanField("已人工修正", default=False)
    corrected_by = models.CharField("最後修正人員", max_length=150, blank=True)
    corrected_at = models.DateTimeField("最後修正時間", blank=True, null=True)
    committed_model = models.CharField("建立資料類型", max_length=80, blank=True)
    committed_pk = models.CharField("建立資料編號", max_length=80, blank=True)

    class Meta:
        ordering = ["sheet_name", "source_row"]
        indexes = [
            models.Index(fields=["batch", "action"], name="legacy_row_batch_action_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "sheet_name", "source_row"],
                name="unique_legacy_import_source_row",
            )
        ]
        verbose_name = "歷史資料匯入列"
        verbose_name_plural = "歷史資料匯入列"


class LegacyImportCorrection(TimeStampedModel):
    class Decision(models.TextChoices):
        CORRECT = "correct", "修正後匯入"
        EXCLUDE = "exclude", "排除此列"
        RESTORE = "restore", "恢復匯入"

    row = models.ForeignKey(
        LegacyImportRow,
        on_delete=models.CASCADE,
        related_name="corrections",
        verbose_name="匯入資料列",
    )
    decision = models.CharField("處理方式", max_length=20, choices=Decision.choices)
    before_data = models.JSONField("處理前資料", default=dict)
    after_data = models.JSONField("處理後資料", default=dict)
    reason = models.TextField("處理原因")
    corrected_by = models.CharField("處理人員", max_length=150)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "歷史匯入人工修正紀錄"
        verbose_name_plural = "歷史匯入人工修正紀錄"


class LegacyImportMasterMapping(TimeStampedModel):
    class MappingType(models.TextChoices):
        VEHICLE_MODEL = "vehicle_model", "車型"
        SALES_SOURCE = "sales_source", "通路"

    source_value = models.CharField("Excel 原始名稱", max_length=200)
    normalized_source_value = models.CharField(
        "標準化名稱", max_length=200, editable=False
    )
    mapping_type = models.CharField(
        "主檔類型", max_length=30, choices=MappingType.choices
    )
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="legacy_import_mappings",
        verbose_name="對應車型",
        blank=True,
        null=True,
    )
    sales_source = models.ForeignKey(
        SalesSource,
        on_delete=models.PROTECT,
        related_name="legacy_import_mappings",
        verbose_name="對應通路",
        blank=True,
        null=True,
    )
    ignored = models.BooleanField(
        "保留歷史文字",
        default=False,
        help_text="不建立或對應主檔；匯入時仍保留 Excel 原始文字。",
    )
    note = models.CharField("處理說明", max_length=250, blank=True)
    updated_by = models.CharField("最後處理人員", max_length=150)

    class Meta:
        ordering = ["mapping_type", "source_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["mapping_type", "normalized_source_value"],
                name="unique_legacy_master_mapping",
            )
        ]
        indexes = [
            models.Index(
                fields=["mapping_type", "normalized_source_value"],
                name="legacy_master_mapping_lookup",
            )
        ]
        verbose_name = "歷史匯入主檔對應"
        verbose_name_plural = "歷史匯入主檔對應"

    def clean(self):
        errors = {}
        if self.ignored:
            if self.vehicle_model_id or self.sales_source_id:
                errors["ignored"] = "保留歷史文字時不可同時指定主檔。"
        elif self.mapping_type == self.MappingType.VEHICLE_MODEL:
            if not self.vehicle_model_id:
                errors["vehicle_model"] = "請選擇要對應的車型。"
            if self.sales_source_id:
                errors["sales_source"] = "車型對應不可指定通路。"
        elif self.mapping_type == self.MappingType.SALES_SOURCE:
            if not self.sales_source_id:
                errors["sales_source"] = "請選擇要對應的通路。"
            if self.vehicle_model_id:
                errors["vehicle_model"] = "通路對應不可指定車型。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.source_value = self.source_value.strip()
        if self.mapping_type == self.MappingType.VEHICLE_MODEL:
            self.normalized_source_value = normalize_vehicle_model_master_value(
                self.source_value
            )
        else:
            self.normalized_source_value = normalize_legacy_master_value(
                self.source_value
            )
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        if self.ignored:
            target = "保留歷史文字"
        else:
            target = self.vehicle_model or self.sales_source
        return f"{self.get_mapping_type_display()}：{self.source_value} → {target}"


class LegacySalesSnapshot(TimeStampedModel):
    order = models.OneToOneField(
        "SalesOrder",
        on_delete=models.CASCADE,
        related_name="legacy_snapshot",
        verbose_name="歷史訂單",
    )
    import_row = models.OneToOneField(
        LegacyImportRow,
        on_delete=models.PROTECT,
        related_name="sales_snapshot",
        verbose_name="匯入來源列",
    )
    historical_received_price = models.DecimalField(
        "歷史收款價", max_digits=12, decimal_places=0, default=0
    )
    cash_received = models.DecimalField("歷史現金收款", max_digits=12, decimal_places=0, default=0)
    card_received = models.DecimalField("歷史刷卡收款", max_digits=12, decimal_places=0, default=0)
    vehicle_identifier = models.CharField(
        "歷史引擎／車身號碼",
        max_length=80,
        blank=True,
        db_index=True,
    )
    sales_category = models.CharField("銷售方案分類", max_length=160, blank=True)
    raw_financials = models.JSONField("歷史收支原值", default=dict)

    class Meta:
        verbose_name = "歷史銷貨快照"
        verbose_name_plural = "歷史銷貨快照"


class SubsidyItem(TimeStampedModel):
    class Category(models.TextChoices):
        INDUSTRY = "industry", "工業局"
        ENVIRONMENT = "environment", "環境部"
        LOCAL = "local", "地方政府"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        NOT_SUBMITTED = "not_submitted", "未申請"
        SUBMITTED = "submitted", "已送出申請"
        COMPLETED = "completed", "已申請完成"

    order = models.ForeignKey(
        "SalesOrder", on_delete=models.CASCADE, related_name="subsidy_items", verbose_name="訂單"
    )
    category = models.CharField("類別", max_length=20, choices=Category.choices)
    item_name = models.CharField("補助項目", max_length=160)
    expected_amount = models.DecimalField("預計金額", max_digits=12, decimal_places=0, default=0)
    applied_on = models.DateField("申請日期", blank=True, null=True)
    status = models.CharField("狀態", max_length=20, choices=Status.choices, default=Status.NOT_SUBMITTED)
    note = models.CharField("備註", max_length=250, blank=True)

    class Meta:
        ordering = ["category", "id"]
        verbose_name = "補助項目"
        verbose_name_plural = "補助項目"


class BusinessHoliday(TimeStampedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", "人工設定"
        DGPA = "dgpa", "人事行政總處同步"

    date = models.DateField("日期", unique=True, db_index=True)
    name = models.CharField("假日名稱", max_length=120)
    active = models.BooleanField("排除工作日計算", default=True)
    source = models.CharField(
        "資料來源",
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
        db_index=True,
    )

    class Meta:
        ordering = ["date"]
        verbose_name = "國定假日"
        verbose_name_plural = "國定假日"

    def __str__(self):
        return f"{self.date}／{self.name}"


class BrandRegistrationFeeRule(TimeStampedModel):
    class CalculationType(models.TextChoices):
        FORMULA = "formula", "公式計算"
        FIXED_BUNDLE = "fixed_bundle", "固定整包金額"
        FIXED_COMPONENTS = "fixed_components", "固定分項金額"
        MANUAL = "manual", "人工輸入"

    brand = models.CharField("品牌", max_length=80)
    energy_type = models.CharField(
        "能源別",
        max_length=20,
        choices=VehicleModel.EnergyType.choices,
        default=VehicleModel.EnergyType.GAS,
    )
    electric_registration_class = models.CharField(
        "電動車領牌級別",
        max_length=20,
        choices=VehicleModel.ElectricRegistrationClass.choices,
        blank=True,
    )
    calculation_type = models.CharField("計算方式", max_length=20, choices=CalculationType.choices)
    min_cc = models.PositiveSmallIntegerField("最低排氣量", blank=True, null=True)
    max_cc = models.PositiveSmallIntegerField("最高排氣量", blank=True, null=True)
    fixed_total = models.DecimalField("固定牌險總額", max_digits=12, decimal_places=0, default=0)
    fixed_registration_fee = models.DecimalField(
        "固定領牌規費", max_digits=12, decimal_places=0, default=0
    )
    fixed_compulsory_insurance_fee = models.DecimalField(
        "固定強制險", max_digits=12, decimal_places=0, default=0
    )
    insurance_period_years = models.PositiveSmallIntegerField("強制險年期", default=1)
    effective_from = models.DateField("生效日期")
    effective_to = models.DateField("結束日期", blank=True, null=True)
    active = models.BooleanField("啟用中", default=True)
    note = models.TextField("備註", blank=True)

    class Meta:
        ordering = ["brand", "min_cc", "-effective_from"]
        constraints = [models.UniqueConstraint(fields=["brand", "energy_type", "electric_registration_class", "min_cc", "max_cc", "effective_from"], name="unique_brand_registration_fee_version")]
        indexes = [models.Index(fields=["brand", "energy_type", "effective_from"], name="brand_reg_fee_lookup")]
        verbose_name = "品牌牌險規則"
        verbose_name_plural = "品牌牌險規則"

    def clean(self):
        errors = {}
        if self.effective_to and self.effective_to < self.effective_from:
            errors["effective_to"] = "結束日期不可早於生效日期。"
        if self.min_cc and self.max_cc and self.max_cc < self.min_cc:
            errors["max_cc"] = "最高排氣量不可低於最低排氣量。"
        if self.energy_type == VehicleModel.EnergyType.ELECTRIC:
            if not self.electric_registration_class:
                errors["electric_registration_class"] = "電動車規則必須選擇輕型或重型。"
            if self.calculation_type == self.CalculationType.FORMULA:
                errors["calculation_type"] = "公式計算僅適用油車；電動車請使用固定金額或人工輸入。"
        elif self.energy_type == VehicleModel.EnergyType.LIGHT_ELECTRIC:
            self.electric_registration_class = (
                VehicleModel.ElectricRegistrationClass.LIGHT
            )
            if self.calculation_type == self.CalculationType.FORMULA:
                errors["calculation_type"] = "公式計算僅適用油車；輕型電動車請使用固定金額或人工輸入。"
        elif self.energy_type == VehicleModel.EnergyType.GAS:
            self.electric_registration_class = ""
        else:
            self.electric_registration_class = ""
            if self.calculation_type == self.CalculationType.FORMULA:
                errors["calculation_type"] = "公式計算僅適用油車；微型電動二輪車請使用固定金額或人工輸入。"
        if (
            self.calculation_type == self.CalculationType.FIXED_BUNDLE
            and not self.fixed_total
        ):
            errors["fixed_total"] = "固定整包金額必須填寫固定牌險總額。"
        if self.calculation_type == self.CalculationType.FIXED_COMPONENTS:
            if not self.fixed_registration_fee:
                errors["fixed_registration_fee"] = "固定分項金額必須填寫領牌規費。"
            if not self.fixed_compulsory_insurance_fee:
                errors["fixed_compulsory_insurance_fee"] = "固定分項金額必須填寫強制險。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.calculation_type == self.CalculationType.FIXED_COMPONENTS:
            self.fixed_total = (
                self.fixed_registration_fee
                + self.fixed_compulsory_insurance_fee
            )
        elif self.calculation_type == self.CalculationType.FIXED_BUNDLE:
            self.fixed_registration_fee = 0
            self.fixed_compulsory_insurance_fee = 0
        else:
            self.fixed_total = 0
            self.fixed_registration_fee = 0
            self.fixed_compulsory_insurance_fee = 0
        self.full_clean()
        return super().save(*args, **kwargs)


class PositionedPrintTemplate(TimeStampedModel):
    class DocumentType(models.TextChoices):
        ENVELOPE = "envelope", "信封"
        SUBMISSION = "submission", "報件單"
        TAX_DECLARATION = "tax_declaration", "減徵貨物稅聲明書"
        TAX_CONSENT = "tax_consent", "退稅同意書"
        EREADY_CHECKLIST = "eready_checklist", "eReady 交車點檢表"

    class PaperSize(models.TextChoices):
        A4 = "a4", "A4"
        A5 = "a5", "A5"
        CUSTOM = "custom", "自訂尺寸"

    class Orientation(models.TextChoices):
        PORTRAIT = "portrait", "直式"
        LANDSCAPE = "landscape", "橫式"

    name = models.CharField("範本名稱", max_length=160)
    document_type = models.CharField("文件類型", max_length=30, choices=DocumentType.choices)
    version = models.PositiveSmallIntegerField("版本", default=1)
    paper_size = models.CharField("紙張", max_length=20, choices=PaperSize.choices, default=PaperSize.A4)
    orientation = models.CharField("方向", max_length=20, choices=Orientation.choices, default=Orientation.PORTRAIT)
    width_mm = models.DecimalField("自訂寬度 mm", max_digits=7, decimal_places=2, blank=True, null=True)
    height_mm = models.DecimalField("自訂高度 mm", max_digits=7, decimal_places=2, blank=True, null=True)
    background_file = models.FileField("背景檔案", upload_to="print_templates/%Y/%m/", blank=True)
    printer_offset_x_mm = models.DecimalField("印表機水平偏移 mm", max_digits=6, decimal_places=2, default=0)
    printer_offset_y_mm = models.DecimalField("印表機垂直偏移 mm", max_digits=6, decimal_places=2, default=0)
    active = models.BooleanField("啟用中", default=True)
    note = models.TextField("備註", blank=True)

    class Meta:
        ordering = ["document_type", "-version", "name"]
        constraints = [
            models.UniqueConstraint(fields=["document_type", "version"], name="unique_positioned_template_version")
        ]
        verbose_name = "定位列印範本"
        verbose_name_plural = "定位列印範本"

    def __str__(self):
        return f"{self.get_document_type_display()}／{self.name}（v{self.version}）"

    def clean(self):
        errors = {}
        if self.paper_size == self.PaperSize.CUSTOM and (not self.width_mm or not self.height_mm):
            errors["width_mm"] = "自訂紙張必須填寫寬度與高度。"
        if errors:
            raise ValidationError(errors)


class PositionedPrintField(TimeStampedModel):
    class Alignment(models.TextChoices):
        LEFT = "left", "靠左"
        CENTER = "center", "置中"
        RIGHT = "right", "靠右"

    template = models.ForeignKey(
        PositionedPrintTemplate,
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name="範本",
    )
    field_key = models.CharField("資料欄位", max_length=80)
    label = models.CharField("內部標籤", max_length=120, blank=True)
    x_mm = models.DecimalField("左側位置 mm", max_digits=7, decimal_places=2, default=10)
    y_mm = models.DecimalField("頂端位置 mm", max_digits=7, decimal_places=2, default=10)
    width_mm = models.DecimalField("欄位寬度 mm", max_digits=7, decimal_places=2, default=60)
    font_size = models.DecimalField("字級", max_digits=5, decimal_places=1, default=10)
    alignment = models.CharField("對齊", max_length=10, choices=Alignment.choices, default=Alignment.LEFT)
    prefix = models.CharField("前置文字", max_length=100, blank=True)
    suffix = models.CharField("後置文字", max_length=100, blank=True)
    sort_order = models.PositiveSmallIntegerField("排序", default=0)
    active = models.BooleanField("顯示", default=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "定位列印欄位"
        verbose_name_plural = "定位列印欄位"


class VehicleSettlementCostRule(TimeStampedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="settlement_cost_rules",
        verbose_name="車型",
    )
    amount = models.DecimalField(
        "代銷結算成本",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )
    announced_on = models.DateField("公告日期", default=timezone.localdate)
    effective_from = models.DateField("生效日期")
    effective_to = models.DateField(
        "結束日期",
        blank=True,
        null=True,
        help_text="可留空；建立下一版本時，系統會依生效日選用最新規則。",
    )
    note = models.TextField("備註", blank=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = [
            "vehicle_model",
            "-effective_from",
            "-id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "vehicle_model",
                    "effective_from",
                ],
                name="unique_settlement_cost_rule_start",
            )
        ]
        indexes = [
            models.Index(
                fields=[
                    "vehicle_model",
                    "effective_from",
                ],
                name="settlement_cost_lookup",
            )
        ]
        verbose_name = "代銷結算成本規則"
        verbose_name_plural = "代銷結算成本規則"

    @property
    def lifecycle_status(self):
        today = timezone.localdate()
        if not self.active:
            return "inactive", "已停用"
        if self.effective_from > today:
            return "scheduled", "預定生效"
        if self.effective_to and self.effective_to < today:
            return "expired", "已失效"
        return "active", "生效中"

    def clean(self):
        errors = {}
        if self.effective_to and self.effective_to < self.effective_from:
            errors["effective_to"] = "結束日期不可早於生效日期。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.vehicle_model}／{self.effective_from:%Y/%m/%d}／"
            f"{self.amount:.0f} 元"
        )


class VehicleIncentiveRule(TimeStampedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="incentive_rules",
        verbose_name="車型",
    )
    sales_bonus = models.DecimalField(
        "實銷獎勵金",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    promotion_subsidy = models.DecimalField(
        "促銷補助金",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    installment_interest_subsidy = models.DecimalField(
        "分期補貼息",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    announced_on = models.DateField("公告日期", default=timezone.localdate)
    effective_from = models.DateField("生效日期")
    effective_to = models.DateField(
        "結束日期",
        blank=True,
        null=True,
        help_text="可留空，代表持續有效；有較新版本時會優先採用新版本。",
    )
    note = models.TextField("備註", blank=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["vehicle_model", "-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle_model", "effective_from"],
                name="unique_incentive_rule_start",
            )
        ]
        indexes = [
            models.Index(
                fields=["vehicle_model", "effective_from"],
                name="incentive_rule_lookup",
            )
        ]
        verbose_name = "車型獎勵補助規則"
        verbose_name_plural = "車型獎勵補助規則"

    @property
    def lifecycle_status(self):
        today = timezone.localdate()
        if not self.active:
            return "inactive", "已停用"
        if self.effective_from > today:
            return "scheduled", "預定生效"
        if self.effective_to and self.effective_to < today:
            return "expired", "已失效"
        return "active", "生效中"

    def clean(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "結束日期不可早於生效日期。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vehicle_model}／{self.effective_from:%Y/%m/%d}"


class VehicleColor(TimeStampedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="colors",
        verbose_name="車型",
    )
    name = models.CharField("車色", max_length=80)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["vehicle_model", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle_model", "name"], name="unique_model_color"
            )
        ]
        verbose_name = "車色"
        verbose_name_plural = "車色"

    def __str__(self):
        return f"{self.vehicle_model}／{self.name}"


class VehicleInventory(TimeStampedModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "可銷售"
        RESERVED = "reserved", "已預留"
        TRANSFER_PENDING = "transfer_pending", "待調車"
        IN_TRANSFER = "in_transfer", "調車中"
        DELIVERY_PENDING = "delivery_pending", "待交車"
        DELIVERED = "delivered", "已交車"
        CONDITION_ISSUE = "condition_issue", "車況異常"
        SOLD = "sold", "已售出"
        INACTIVE = "inactive", "停用"

    vehicle_model = models.ForeignKey(
        VehicleModel, on_delete=models.PROTECT, verbose_name="車型"
    )
    color = models.ForeignKey(
        VehicleColor, on_delete=models.PROTECT, verbose_name="車色"
    )
    engine_number = models.CharField(
        "引擎號碼", max_length=80, blank=True, null=True, unique=True
    )
    frame_number = models.CharField(
        "車身號碼", max_length=80, blank=True, null=True, unique=True
    )
    normalized_engine_number = models.CharField(
        "標準化引擎號碼",
        max_length=80,
        blank=True,
        null=True,
        unique=True,
        editable=False,
    )
    normalized_frame_number = models.CharField(
        "標準化車身號碼",
        max_length=80,
        blank=True,
        null=True,
        unique=True,
        editable=False,
    )
    ownership_store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="owned_vehicles",
        verbose_name="庫存歸屬門市",
    )
    location_store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="located_vehicles",
        verbose_name="實際存放門市",
    )
    current_dealer = models.ForeignKey(
        SalesSource,
        on_delete=models.PROTECT,
        related_name="located_vehicles",
        verbose_name="實際位置",
        blank=True,
        null=True,
        limit_choices_to={"source_type": SalesSource.SourceType.DEALER},
        help_text="未選擇代表車輛位於本店；放在車行時請選擇車行名稱。",
    )
    received_on = models.DateField("進車日期", default=timezone.localdate)
    manufactured_year_month = models.CharField(
        "出廠年月",
        max_length=7,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^\d{4}/(0[1-9]|1[0-2])$",
                message="請使用 YYYY/MM，例如 2026/08。",
            )
        ],
        help_text="供車輛年份顯示與庫存先進先出判斷。",
    )
    status = models.CharField(
        "庫存狀態", max_length=30, choices=Status.choices, default=Status.AVAILABLE
    )
    condition_note = models.TextField("車況說明", blank=True)
    condition_photo = models.ImageField(
        "車況照片", upload_to="inventory/condition/%Y/%m/", blank=True
    )
    condition_resolution = models.TextField("處理結果", blank=True)
    class Meta:
        ordering = ["-received_on", "-id"]
        verbose_name = "庫存車輛"
        verbose_name_plural = "庫存車輛"

    @property
    def identifier(self):
        return self.engine_number or self.frame_number or "尚未填寫"

    @property
    def actual_location_label(self):
        return self.current_dealer.name if self.current_dealer_id else "本店"

    def clean(self):
        errors = {}
        if self.color_id and self.vehicle_model_id:
            if self.color.vehicle_model_id != self.vehicle_model_id:
                errors["color"] = "此車色不屬於選定車型。"
        if self.vehicle_model_id:
            if self.vehicle_model.energy_type == VehicleModel.EnergyType.GAS:
                if not self.engine_number:
                    errors["engine_number"] = "油車必須填寫引擎號碼。"
                if self.frame_number:
                    errors["frame_number"] = "油車第一階段不使用車身號碼。"
            else:
                if not self.frame_number:
                    errors["frame_number"] = "電動車必須填寫車身號碼。"
                if self.engine_number:
                    errors["engine_number"] = "電動車第一階段不使用引擎號碼。"
        if (
            self.current_dealer_id
            and self.current_dealer.source_type != SalesSource.SourceType.DEALER
        ):
            errors["current_dealer"] = "實際位置只能選擇車行。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.engine_number = self.engine_number.strip().upper() if self.engine_number else None
        self.frame_number = self.frame_number.strip().upper() if self.frame_number else None
        self.normalized_engine_number = normalize_vehicle_identifier(self.engine_number)
        self.normalized_frame_number = normalize_vehicle_identifier(self.frame_number)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vehicle_model} {self.color.name}／{self.identifier}"


class VehicleInventoryHistory(TimeStampedModel):
    class EventType(models.TextChoices):
        CREATED = "created", "建立庫存"
        UPDATED = "updated", "更新資料"
        TRANSFERRED = "transferred", "調度車輛"

    vehicle = models.ForeignKey(
        VehicleInventory,
        on_delete=models.CASCADE,
        related_name="history_entries",
        verbose_name="庫存車輛",
    )
    event_type = models.CharField(
        "異動類型", max_length=20, choices=EventType.choices
    )
    actor_name = models.CharField("異動人員", max_length=150, blank=True)
    reason = models.TextField("異動原因", blank=True)
    changes = models.JSONField("異動內容", default=dict, blank=True)
    status_snapshot = models.CharField(
        "當下狀態", max_length=30, choices=VehicleInventory.Status.choices
    )
    location_store_snapshot = models.ForeignKey(
        Store,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="當下位置",
    )
    location_label_snapshot = models.CharField("當下實際位置", max_length=120, blank=True)
    condition_note_snapshot = models.TextField("當下車況", blank=True)
    condition_resolution_snapshot = models.TextField("當下處理結果", blank=True)
    condition_photo_snapshot = models.ImageField(
        "當下車況照片",
        upload_to="inventory/history/%Y/%m/",
        blank=True,
    )
    from_location = models.ForeignKey(
        Store,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="調出位置",
    )
    from_location_label = models.CharField("調出實際位置", max_length=120, blank=True)
    to_location = models.ForeignKey(
        Store,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="調入位置",
    )
    to_location_label = models.CharField("調入實際位置", max_length=120, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "庫存異動紀錄"
        verbose_name_plural = "庫存異動紀錄"

    def __str__(self):
        return f"{self.vehicle.identifier}／{self.get_event_type_display()}"


class SalesOrder(TimeStampedModel):
    class VehicleCategory(models.TextChoices):
        NEW = "new", "新車"
        USED = "used", "中古車"

    class TransactionType(models.TextChoices):
        REGULAR_NEW = "regular_new", "一般新車"
        REGISTERED = "registered", "領牌車"
        TEST_RIDE = "test_ride", "試乘車"
        PRIZE = "prize", "中獎車"
        USED = "used", "中古車交易"
        OTHER = "other", "其他"

    class SourceType(models.TextChoices):
        STORE = "store", "本店"
        DEALER = "dealer", "合作車行"
        PLATFORM = "platform", "網路平台"

    class OwnerType(models.TextChoices):
        LOCAL = "local", "本國自然人"
        FOREIGN = "foreign", "外籍／居留者"
        COMPANY = "company", "法人"

    class PaymentType(models.TextChoices):
        CASH = "cash", "現金"
        INSTALLMENT = "installment", "分期"
        CARD = "card", "刷卡"

    class DiscountStatus(models.TextChoices):
        NONE = "", "未申請"
        PENDING = "pending", "待確認"
        APPROVED = "approved", "已核准"
        REJECTED = "rejected", "未採用"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "現金"
        TRANSFER = "transfer", "匯款"
        CARD = "card", "刷卡"
        OTHER = "other", "其他"

    class CompulsoryInsurancePeriod(models.IntegerChoices):
        ONE_YEAR = 1, "一年"
        TWO_YEARS = 2, "兩年"

    class PlateChoice(models.TextChoices):
        NONE = "none", "不選號"
        WATCH = "watch", "指定號碼監控"
        PREFERENCE = "preference", "一般領牌偏好"

    class DeliveryMethod(models.TextChoices):
        STORE_PICKUP = "store_pickup", "客人來店取車"
        DEALER_PICKUP = "dealer_pickup", "合作車行領車"
        DIRECT_DELIVERY = "direct_delivery", "送至指定地點"
        CARRIER = "carrier", "委託託運公司"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ALLOCATION_PENDING = "allocation_pending", "待配車"
        ALLOCATED = "allocated", "已配車"
        TRANSFER_PENDING = "transfer_pending", "待調車"
        IN_TRANSFER = "in_transfer", "調車中"
        DELIVERY_PENDING = "delivery_pending", "待交車"
        DELIVERED_DOCS_PENDING = "delivered_docs_pending", "已交車／待補文件"
        COMPLETED = "completed", "已完成"
        CANCEL_REFUND_PENDING = "cancel_refund_pending", "取消待退款"
        CANCELLED = "cancelled", "已取消／已退款"

    number = models.CharField("訂單編號", max_length=24, unique=True, editable=False)
    order_date = models.DateField("訂單日期", default=timezone.localdate)
    source_type = models.CharField(
        "訂單來源", max_length=20, choices=SourceType.choices, default=SourceType.STORE
    )
    source = models.ForeignKey(
        SalesSource,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name="來源名稱",
    )
    status = models.CharField(
        "訂單狀態",
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    owner_type = models.CharField(
        "車主類型", max_length=20, choices=OwnerType.choices, default=OwnerType.LOCAL
    )
    owner_name = models.CharField("車主姓名／公司名稱", max_length=160)
    owner_name_en = models.CharField("英文姓名", max_length=160, blank=True)
    owner_phone = models.CharField("電話", max_length=30)
    owner_email = models.EmailField("Email", blank=True)
    owner_birth_date = models.DateField("生日", blank=True, null=True)
    owner_nationality = models.CharField("國籍", max_length=80, blank=True)
    owner_address = models.TextField("戶籍／公司地址")
    owner_id_number = models.CharField("證件號碼／統一編號", max_length=40)
    residence_expiry = models.DateField("居留期限", blank=True, null=True)
    id_front = models.ImageField("證件正面", upload_to="orders/id/%Y/%m/", blank=True)
    id_back = models.ImageField("證件反面", upload_to="orders/id/%Y/%m/", blank=True)
    id_verified = models.BooleanField("已人工核對證件", default=False)
    id_verified_at = models.DateTimeField("證件核對時間", blank=True, null=True)

    vehicle_model = models.ForeignKey(
        VehicleModel, on_delete=models.PROTECT, verbose_name="車型"
    )
    color = models.ForeignKey(
        VehicleColor, on_delete=models.PROTECT, verbose_name="車色"
    )
    allocated_vehicle = models.OneToOneField(
        VehicleInventory,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="active_order",
        verbose_name="已配車輛",
    )
    vehicle_category = models.CharField(
        "車輛類別",
        max_length=10,
        choices=VehicleCategory.choices,
        default=VehicleCategory.NEW,
    )
    transaction_type = models.CharField(
        "交易類型",
        max_length=20,
        choices=TransactionType.choices,
        default=TransactionType.REGULAR_NEW,
        db_index=True,
        help_text="用來區分一般新車、領牌車、試乘車、中獎車或中古車交易。",
    )
    registration_date = models.DateField("實際領牌日期", blank=True, null=True)
    registration_county = models.CharField(
        "領牌縣市",
        max_length=10,
        choices=TaiwanCounty.choices,
        blank=True,
    )
    compulsory_insurance_period = models.PositiveSmallIntegerField(
        "強制險期間",
        choices=CompulsoryInsurancePeriod.choices,
        default=CompulsoryInsurancePeriod.ONE_YEAR,
    )
    registration_rate_class = models.CharField(
        "領牌費率級距", max_length=10, blank=True
    )
    registration_plate_fee = models.DecimalField(
        "號牌費", max_digits=12, decimal_places=0, default=0
    )
    registration_license_fee = models.DecimalField(
        "行照費", max_digits=12, decimal_places=0, default=0
    )
    registration_inspection_fee = models.DecimalField(
        "檢驗費", max_digits=12, decimal_places=0, default=0
    )
    road_maintenance_fee = models.DecimalField(
        "公路養管費", max_digits=12, decimal_places=0, default=0
    )
    license_tax_fee = models.DecimalField(
        "使用牌照稅", max_digits=12, decimal_places=0, default=0
    )
    compulsory_insurance_fee = models.DecimalField(
        "強制險", max_digits=12, decimal_places=0, default=0
    )
    plate_selection_fee = models.DecimalField(
        "選號費", max_digits=12, decimal_places=0, default=0
    )
    lien_registration_fee = models.DecimalField(
        "動保設定費", max_digits=12, decimal_places=0, default=0
    )
    registration_calculated_total = models.DecimalField(
        "系統試算牌險合計",
        max_digits=12,
        decimal_places=0,
        default=0,
    )
    registration_fee_variance_confirmed_at = models.DateTimeField(
        "牌險差額確認時間", blank=True, null=True, editable=False
    )
    registration_fee_variance_confirmed_by = models.CharField(
        "牌險差額確認人員", max_length=150, blank=True, editable=False
    )
    registration_fee_variance_confirmed_calculated_total = models.DecimalField(
        "已確認系統牌險金額",
        max_digits=12,
        decimal_places=0,
        blank=True,
        null=True,
        editable=False,
    )
    registration_fee_variance_confirmed_actual_total = models.DecimalField(
        "已確認實際牌險金額",
        max_digits=12,
        decimal_places=0,
        blank=True,
        null=True,
        editable=False,
    )

    payment_type = models.CharField(
        "主要付款方式",
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.CASH,
    )
    vehicle_price = models.DecimalField(
        "車價", max_digits=12, decimal_places=0, default=0
    )
    vehicle_price_adjustment_reason = models.TextField(
        "車價調整原因",
        blank=True,
        help_text="成交車價與售價版本不同時，記錄本次人工調整原因。",
    )
    price_version = models.ForeignKey(
        VehiclePriceVersion,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="訂單售價版本",
        blank=True,
        null=True,
        editable=False,
    )
    price_snapshot = models.JSONField(
        "訂單售價快照",
        default=dict,
        blank=True,
        editable=False,
    )
    price_snapshot_locked_at = models.DateTimeField(
        "售價快照保存時間",
        blank=True,
        null=True,
        editable=False,
    )
    plate_insurance_fee = models.DecimalField(
        "實際牌險合計", max_digits=12, decimal_places=0, default=0
    )
    installment_opening_fee = models.DecimalField(
        "分期開辦費", max_digits=12, decimal_places=0, default=0
    )
    deposit_amount = models.DecimalField(
        "訂金", max_digits=12, decimal_places=0, default=0
    )
    deposit_date = models.DateField(
        "訂金日期", default=timezone.localdate, blank=True, null=True
    )
    deposit_method = models.CharField(
        "訂金付款方式",
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
    )
    calculated_balance = models.DecimalField(
        "系統試算尾款", max_digits=12, decimal_places=0, default=0, editable=False
    )
    actual_balance = models.DecimalField(
        "實際尾款", max_digits=12, decimal_places=0, default=0
    )
    balance_adjustment_reason = models.TextField("尾款調整原因", blank=True)

    installment_company = models.CharField("分期公司", max_length=100, blank=True)
    installment_company_master = models.ForeignKey(
        InstallmentCompany,
        on_delete=models.SET_NULL,
        related_name="orders",
        verbose_name="分期公司主檔",
        blank=True,
        null=True,
        editable=False,
    )
    approved_discount_amount = models.DecimalField(
        "內部核准折扣", max_digits=12, decimal_places=0, default=0, editable=False
    )
    discount_requested_amount = models.DecimalField(
        "申請折扣金額", max_digits=12, decimal_places=0, default=0, editable=False
    )
    discount_reason = models.CharField("折扣原因", max_length=250, blank=True, editable=False)
    discount_status = models.CharField(
        "折扣狀態", max_length=20, choices=DiscountStatus.choices, blank=True, editable=False
    )
    discount_requested_at = models.DateTimeField("折扣申請時間", blank=True, null=True, editable=False)
    discount_requested_by = models.CharField("折扣申請人", max_length=150, blank=True, editable=False)
    discount_decided_at = models.DateTimeField("折扣確認時間", blank=True, null=True, editable=False)
    discount_decided_by = models.CharField("折扣確認人", max_length=150, blank=True, editable=False)
    discount_decision_note = models.CharField("折扣確認備註", max_length=250, blank=True, editable=False)
    installment_plan_option = models.ForeignKey(
        InstallmentPlanOption,
        on_delete=models.SET_NULL,
        related_name="orders",
        verbose_name="套用分期方案",
        blank=True,
        null=True,
        editable=False,
    )
    installment_plan_snapshot = models.JSONField(
        "分期方案快照", default=dict, blank=True, editable=False
    )
    installment_amount = models.DecimalField(
        "分期申請金額", max_digits=12, decimal_places=0, default=0
    )
    installment_periods = models.PositiveSmallIntegerField("分期期數", default=0)
    installment_monthly = models.DecimalField(
        "每期金額", max_digits=12, decimal_places=0, default=0
    )
    installment_applied_on = models.DateField("分期申請日期", blank=True, null=True)
    installment_status = models.CharField("分期狀態", max_length=30, blank=True)
    installment_decided_on = models.DateField("核准／拒絕日期", blank=True, null=True)

    is_trade_in_subsidy = models.BooleanField("申請汰舊／政府補助", default=False)
    old_owner_same_as_owner = models.BooleanField(
        "新舊車主為同一人", default=True
    )
    trade_in_plate = models.CharField("舊車車牌", max_length=20, blank=True)
    old_owner_name = models.CharField("舊車主姓名", max_length=160, blank=True)
    old_owner_id_number = models.CharField(
        "舊車主身分證字號", max_length=40, blank=True
    )
    old_owner_ocr_name = models.CharField(
        "OCR 辨識舊車主姓名", max_length=160, blank=True
    )
    old_owner_ocr_id_number = models.CharField(
        "OCR 辨識舊車主身分證字號", max_length=40, blank=True
    )
    subsidy_type = models.CharField("補助類型", max_length=120, blank=True)
    old_vehicle_valuation = models.DecimalField(
        "舊車估價", max_digits=12, decimal_places=0, default=0
    )
    old_vehicle_tax = models.DecimalField(
        "舊車未繳稅金", max_digits=12, decimal_places=0, default=0
    )

    plate_choice = models.CharField(
        "選號方式",
        max_length=20,
        choices=PlateChoice.choices,
        default=PlateChoice.NONE,
    )
    watched_numbers = models.TextField("指定號碼與志願序", blank=True)
    plate_preference_note = models.TextField("領牌偏好備註", blank=True)
    final_plate_number = models.CharField("最終車牌號碼", max_length=20, blank=True)
    registration_completed_at = models.DateTimeField(
        "領牌完成時間", blank=True, null=True
    )
    registration_completed_by = models.CharField(
        "領牌完成人員", max_length=150, blank=True
    )

    delivery_method = models.CharField(
        "交車方式", max_length=30, choices=DeliveryMethod.choices, blank=True
    )
    delivery_destination = models.CharField(
        "送達地點／託運目的地", max_length=250, blank=True
    )
    delivered_at = models.DateTimeField(
        "實際交車時間", blank=True, null=True, db_index=True
    )
    delivered_by = models.CharField("交車完成人員", max_length=150, blank=True)
    cancellation_requested_at = models.DateTimeField(
        "取消申請時間", blank=True, null=True
    )
    cancellation_requested_by = models.CharField(
        "取消登記人員", max_length=150, blank=True
    )
    cancellation_reason = models.CharField("取消原因", max_length=250, blank=True)
    cancellation_note = models.TextField("取消說明", blank=True)
    refund_amount = models.DecimalField(
        "退款金額", max_digits=12, decimal_places=0, default=0
    )
    refund_completed_on = models.DateField("退款完成日期", blank=True, null=True)
    refund_method = models.CharField(
        "退款方式", max_length=20, choices=PaymentMethod.choices, blank=True
    )
    refund_reference = models.CharField("退款帳號／交易資訊", max_length=250, blank=True)
    refund_proof = models.FileField(
        "退款證明", upload_to="orders/refunds/%Y/%m/", blank=True
    )
    cancellation_completed_at = models.DateTimeField(
        "取消完成時間", blank=True, null=True
    )
    cancellation_completed_by = models.CharField(
        "取消完成人員", max_length=150, blank=True
    )
    note = models.TextField("備註", blank=True)
    signed_contract = models.FileField(
        "已簽署合約", upload_to="orders/contracts/%Y/%m/", blank=True
    )
    signed_contract_uploaded_at = models.DateTimeField(
        "合約上傳時間", blank=True, null=True
    )
    privacy_consent = models.FileField(
        "已簽署個資同意書",
        upload_to="orders/privacy-consents/%Y/%m/",
        blank=True,
    )
    privacy_consent_uploaded_at = models.DateTimeField(
        "個資同意書上傳時間", blank=True, null=True
    )
    revision = models.PositiveIntegerField("資料版本", default=1)
    editing_session = models.CharField("編輯工作階段", max_length=40, blank=True)
    editing_by = models.CharField("目前編輯人員", max_length=150, blank=True)
    editing_at = models.DateTimeField("最後編輯心跳", blank=True, null=True)

    class Meta:
        ordering = ["-order_date", "-id"]
        verbose_name = "銷售訂單"
        verbose_name_plural = "銷售訂單"
        indexes = [
            models.Index(fields=["number"]),
            models.Index(fields=["owner_name"]),
            models.Index(fields=["owner_phone"]),
            models.Index(fields=["owner_id_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["order_date"], name="sales_order_date_idx"),
            models.Index(
                fields=["registration_date"], name="sales_registration_date_idx"
            ),
        ]

    @property
    def masked_id_number(self):
        value = self.owner_id_number or ""
        if len(value) <= 4:
            return "＊" * len(value)
        return f"{value[:2]}{'＊' * (len(value) - 4)}{value[-2:]}"

    @property
    def has_signed_contract(self):
        return bool(self.signed_contract)

    @property
    def has_privacy_consent(self):
        return bool(self.privacy_consent)

    @property
    def is_editable(self):
        return self.status not in {
            self.Status.DELIVERED_DOCS_PENDING,
            self.Status.COMPLETED,
            self.Status.CANCELLED,
        }

    @property
    def can_manage_subsidy(self):
        """補助可能在交付後才申請或補件，僅正式取消後鎖定。"""
        return self.status != self.Status.CANCELLED

    @property
    def accessory_total(self):
        return (
            sum(line.line_total for line in self.accessories.all())
            if self.pk
            else 0
        )

    @property
    def other_fee_total(self):
        return (
            sum(line.amount for line in self.other_fees.all())
            if self.pk
            else 0
        )

    @property
    def effective_installment_fee(self):
        return (
            self.installment_opening_fee
            if self.payment_type == self.PaymentType.INSTALLMENT
            else 0
        )

    @property
    def balance_adjustment_amount(self):
        return self.actual_balance - self.calculated_balance

    @property
    def is_registration_complete(self):
        return bool(self.registration_completed_at)

    @property
    def is_delivered(self):
        return self.status in {
            self.Status.DELIVERED_DOCS_PENDING,
            self.Status.COMPLETED,
        }

    @property
    def can_deliver(self):
        return (
            self.is_registration_complete
            or self.source_type == self.SourceType.DEALER
        )

    def required_registration_document_types(self):
        required = set(RegistrationDocument.active_fixed_document_types())
        required.discard(RegistrationDocument.DocumentType.PLATE_SELECTION)
        if self.plate_choice != self.PlateChoice.NONE:
            required.add(RegistrationDocument.DocumentType.PLATE_SELECTION)
        return required

    def subsidy_document_types_when_enabled(self):
        required = {
            SubsidyDocument.DocumentType.OLD_OWNER_ID_FRONT,
            SubsidyDocument.DocumentType.OLD_OWNER_ID_BACK,
            SubsidyDocument.DocumentType.OLD_VEHICLE_REGISTRATION,
            SubsidyDocument.DocumentType.SCRAP_CERTIFICATE,
            SubsidyDocument.DocumentType.RECYCLING_RECEIPT,
            SubsidyDocument.DocumentType.NEW_OWNER_BANKBOOK,
        }
        if not self.old_owner_same_as_owner:
            required.add(SubsidyDocument.DocumentType.OWNER_DECLARATION)
            required.add(SubsidyDocument.DocumentType.OLD_OWNER_BANKBOOK)
        return required

    def required_subsidy_document_types(self):
        if not self.is_trade_in_subsidy:
            return set()
        return self.subsidy_document_types_when_enabled()

    def missing_subsidy_requirements(self):
        if not self.is_trade_in_subsidy:
            return []
        missing = []
        if not self.trade_in_plate:
            missing.append("舊車車牌")
        if not self.subsidy_type:
            missing.append("補助類型")
        if not self.old_owner_same_as_owner and not self.old_owner_name:
            missing.append("舊車主姓名")
        if not self.old_owner_same_as_owner and not self.old_owner_id_number:
            missing.append("舊車主身分證字號")
        uploaded = set(
            self.subsidy_documents.values_list("document_type", flat=True)
        )
        labels = dict(SubsidyDocument.DocumentType.choices)
        for document_type in self.required_subsidy_document_types():
            if document_type not in uploaded:
                missing.append(labels[document_type])
        return missing

    @property
    def subsidy_required_count(self):
        if not self.is_trade_in_subsidy:
            return 0
        different_owner = not self.old_owner_same_as_owner
        return (
            2
            + (2 * int(different_owner))
            + len(self.required_subsidy_document_types())
        )

    @property
    def subsidy_completed_count(self):
        if not self.is_trade_in_subsidy:
            return 0
        return self.subsidy_required_count - len(self.missing_subsidy_requirements())

    @property
    def is_subsidy_ready(self):
        return self.is_trade_in_subsidy and not self.missing_subsidy_requirements()

    @property
    def subsidy_total(self):
        if not self.pk:
            return Decimal("0")
        return self.subsidy_items.aggregate(total=models.Sum("expected_amount"))["total"] or Decimal("0")

    @property
    def subsidy_last_applied_on(self):
        if not self.pk:
            return None
        return self.subsidy_items.exclude(applied_on__isnull=True).aggregate(last=models.Max("applied_on"))["last"]

    def missing_registration_requirements(self):
        missing = []
        if not self.allocated_vehicle_id:
            missing.append("完成配車")
        if not self.registration_date:
            missing.append("實際領牌日期")
        if not self.final_plate_number:
            missing.append("車牌號碼")
        uploaded = set(
            self.registration_documents.values_list("document_type", flat=True)
        )
        labels = dict(RegistrationDocument.DocumentType.choices)
        for document_type in self.required_registration_document_types():
            if document_type not in uploaded:
                missing.append(labels[document_type])
        return missing

    def complete_registration(self, actor_name):
        missing = self.missing_registration_requirements()
        if missing:
            raise ValidationError("尚缺：" + "、".join(missing))
        self.registration_completed_at = timezone.now()
        self.registration_completed_by = actor_name
        if self.is_delivered:
            self.status = self.Status.COMPLETED
        else:
            self.status = self.Status.DELIVERY_PENDING
        self.save(
            update_fields=[
                "registration_completed_at",
                "registration_completed_by",
                "status",
                "updated_at",
            ]
        )

    @transaction.atomic
    def complete_delivery(self, delivered_at, actor_name):
        if self.is_delivered:
            raise ValidationError("此訂單已完成交付。")
        if self.status in {
            self.Status.CANCEL_REFUND_PENDING,
            self.Status.CANCELLED,
        }:
            raise ValidationError("已進入取消流程，不能交付車輛。")
        if not self.allocated_vehicle_id:
            raise ValidationError("尚未配車，不能完成交付。")
        if not self.can_deliver:
            raise ValidationError("一般訂單必須先完成領牌才能交付。")
        if self.source_type != self.SourceType.DEALER:
            required_balance = (
                max(
                    (self.actual_balance or Decimal("0"))
                    - (self.installment_amount or Decimal("0")),
                    Decimal("0"),
                )
                if self.payment_type == self.PaymentType.INSTALLMENT
                else (self.actual_balance or Decimal("0"))
            )
            balance_payment = self.payment_records.filter(system_key="balance").first()
            received = (
                balance_payment.received_amount
                if balance_payment is not None
                else Decimal("0")
            ) or Decimal("0")
            settled = bool(
                required_balance <= 0
                or (
                    balance_payment is not None
                    and balance_payment.confirmed
                    and received >= required_balance
                )
            )
            if not settled:
                shortage = max(required_balance - received, Decimal("0"))
                raise ValidationError(
                    f"尾款尚未收清，仍差 {shortage:,.0f} 元；"
                    "請先在交付頁保存並確認收款。"
                )

        vehicle = VehicleInventory.objects.select_for_update().get(
            pk=self.allocated_vehicle_id
        )
        vehicle.status = VehicleInventory.Status.DELIVERED
        vehicle.save(update_fields=["status", "updated_at"])
        self.delivered_at = delivered_at
        self.delivered_by = actor_name
        self.status = (
            self.Status.COMPLETED
            if self.is_registration_complete
            else self.Status.DELIVERED_DOCS_PENDING
        )
        self.save(
            update_fields=["delivered_at", "delivered_by", "status", "updated_at"]
        )

    @transaction.atomic
    def request_cancellation(self, actor_name, reason, note=""):
        if self.is_delivered or self.status == self.Status.COMPLETED:
            raise ValidationError("車輛已交付，不能取消訂單。")
        if self.is_registration_complete:
            raise ValidationError("車輛已領牌，不再是新車，不能取消訂單。")
        if self.status == self.Status.CANCELLED:
            raise ValidationError("此訂單已取消。")
        if self.allocated_vehicle_id:
            vehicle = VehicleInventory.objects.select_for_update().get(
                pk=self.allocated_vehicle_id
            )
            vehicle.status = VehicleInventory.Status.AVAILABLE
            vehicle.save(update_fields=["status", "updated_at"])
            VehicleInventoryHistory.objects.create(
                vehicle=vehicle,
                event_type=VehicleInventoryHistory.EventType.UPDATED,
                actor_name=actor_name,
                reason=f"訂單 {self.number} 取消，解除配車",
                changes={"訂單狀態": {"before": "已配車", "after": "取消"}},
                status_snapshot=vehicle.status,
                location_store_snapshot=vehicle.location_store,
                location_label_snapshot=vehicle.actual_location_label,
                condition_note_snapshot=vehicle.condition_note,
                condition_resolution_snapshot=vehicle.condition_resolution,
            )
            self.allocated_vehicle = None
        self.cancellation_requested_at = timezone.now()
        self.cancellation_requested_by = actor_name
        self.cancellation_reason = reason
        self.cancellation_note = note
        if self.deposit_amount:
            self.status = self.Status.CANCEL_REFUND_PENDING
        else:
            self.status = self.Status.CANCELLED
            self.refund_amount = 0
            self.cancellation_completed_at = timezone.now()
            self.cancellation_completed_by = actor_name
        self.save(
            update_fields=[
                "allocated_vehicle",
                "cancellation_requested_at",
                "cancellation_requested_by",
                "cancellation_reason",
                "cancellation_note",
                "status",
                "refund_amount",
                "cancellation_completed_at",
                "cancellation_completed_by",
                "updated_at",
            ]
        )

    def complete_refund(
        self, actor_name, amount, completed_on, method, reference="", proof=None
    ):
        if self.status != self.Status.CANCEL_REFUND_PENDING:
            raise ValidationError("此訂單目前不在取消待退款狀態。")
        if amount != self.deposit_amount:
            raise ValidationError(
                f"訂金必須全數退還，退款金額應為 {self.deposit_amount:,.0f} 元。"
            )
        self.refund_amount = amount
        self.refund_completed_on = completed_on
        self.refund_method = method
        self.refund_reference = reference
        if proof is not None:
            self.refund_proof = proof
        self.cancellation_completed_at = timezone.now()
        self.cancellation_completed_by = actor_name
        self.status = self.Status.CANCELLED
        self.save(
            update_fields=[
                "refund_amount",
                "refund_completed_on",
                "refund_method",
                "refund_reference",
                "refund_proof",
                "cancellation_completed_at",
                "cancellation_completed_by",
                "status",
                "updated_at",
            ]
        )

    def calculate_balance(self):
        return (
            self.vehicle_price
            + self.plate_insurance_fee
            + self.effective_installment_fee
            + self.other_fee_total
            + self.old_vehicle_tax
            + self.accessory_total
            - self.deposit_amount
            - self.old_vehicle_valuation
            - self.approved_discount_amount
        )

    def clear_installment_details(self):
        self.installment_company = ""
        self.installment_amount = 0
        self.installment_periods = 0
        self.installment_opening_fee = 0
        self.installment_monthly = 0
        self.installment_applied_on = None
        self.installment_status = ""
        self.installment_decided_on = None

    def clean(self):
        if self.payment_type != self.PaymentType.INSTALLMENT:
            self.clear_installment_details()
        errors = {}
        if self.source_type != self.SourceType.STORE and not self.source_id:
            errors["source"] = "合作車行或網路平台訂單必須選擇來源名稱。"
        if self.source_id and self.source.source_type != self.source_type:
            errors["source"] = "來源名稱與訂單來源類型不一致。"
        if self.vehicle_category == self.VehicleCategory.USED:
            self.transaction_type = self.TransactionType.USED
        elif self.transaction_type == self.TransactionType.USED:
            errors["transaction_type"] = "中古車交易的車輛類別也必須選擇中古車。"
        if self.color_id and self.vehicle_model_id:
            if self.color.vehicle_model_id != self.vehicle_model_id:
                errors["color"] = "此車色不屬於選定車型。"
        if (
            self.pk
            and self.actual_balance != self.calculated_balance
            and not self.balance_adjustment_reason
        ):
            errors["balance_adjustment_reason"] = "修改系統試算尾款時必須填寫原因。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"SO{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        if self.id_verified and not self.id_verified_at:
            self.id_verified_at = timezone.now()
        if self.signed_contract and not self.signed_contract_uploaded_at:
            self.signed_contract_uploaded_at = timezone.now()
        if self.privacy_consent and not self.privacy_consent_uploaded_at:
            self.privacy_consent_uploaded_at = timezone.now()
        if self.pk:
            self.calculated_balance = self.calculate_balance()
        if self.status == self.Status.DRAFT:
            self.status = self.Status.ALLOCATION_PENDING
        if self.is_delivered and not self.delivered_at:
            self.delivered_at = timezone.now()
            if not self.delivered_by:
                self.delivered_by = "系統狀態同步"
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                    "delivered_at",
                    "delivered_by",
                }
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def allocate(self, vehicle):
        locked_order = type(self).objects.select_for_update().get(pk=self.pk)
        locked = VehicleInventory.objects.select_for_update().get(pk=vehicle.pk)
        if locked_order.allocated_vehicle_id:
            raise ValidationError("此訂單已配車，請先解除原配車。")
        if locked.status != VehicleInventory.Status.AVAILABLE:
            raise ValidationError("此車輛目前不可配車。")
        if (
            locked.vehicle_model_id != locked_order.vehicle_model_id
            or locked.color_id != locked_order.color_id
        ):
            raise ValidationError("實體車輛的車型或車色與訂單不一致。")
        locked.status = VehicleInventory.Status.RESERVED
        locked.save(update_fields=["status", "updated_at"])
        locked_order.allocated_vehicle = locked
        locked_order.status = self.Status.ALLOCATED
        locked_order.save(update_fields=["allocated_vehicle", "status", "updated_at"])
        self.allocated_vehicle = locked
        self.allocated_vehicle_id = locked.pk
        self.status = self.Status.ALLOCATED

    @property
    def has_registration_started(self):
        active_documents_exist = self.registration_documents.exclude(
            document_type__in=RegistrationDocument.retired_document_types()
        ).exists()
        return bool(
            self.final_plate_number
            or self.registration_completed_at
            or active_documents_exist
        )

    @transaction.atomic
    def reallocate(self, vehicle):
        if not self.allocated_vehicle_id:
            raise ValidationError("此訂單尚未配車。")
        if not self.is_editable:
            raise ValidationError("此訂單已鎖定，無法改配。")
        if self.has_registration_started:
            raise ValidationError("已開始領牌作業，無法直接改配。")
        if vehicle.pk == self.allocated_vehicle_id:
            raise ValidationError("新配車輛不可與原車相同。")

        vehicle_ids = sorted([self.allocated_vehicle_id, vehicle.pk])
        locked_vehicles = {
            item.pk: item
            for item in VehicleInventory.objects.select_for_update().filter(
                pk__in=vehicle_ids
            )
        }
        original = locked_vehicles[self.allocated_vehicle_id]
        replacement = locked_vehicles.get(vehicle.pk)
        if not replacement or replacement.status != VehicleInventory.Status.AVAILABLE:
            raise ValidationError("新車輛目前不可配車。")
        if (
            replacement.vehicle_model_id != self.vehicle_model_id
            or replacement.color_id != self.color_id
        ):
            raise ValidationError("新車輛的車型或車色與訂單不一致。")

        original.status = VehicleInventory.Status.AVAILABLE
        replacement.status = VehicleInventory.Status.RESERVED
        original.save(update_fields=["status", "updated_at"])
        replacement.save(update_fields=["status", "updated_at"])
        self.allocated_vehicle = replacement
        self.status = self.Status.ALLOCATED
        self.save(update_fields=["allocated_vehicle", "status", "updated_at"])
        return original, replacement

    def __str__(self):
        return f"{self.number}／{self.owner_name}"


class DeliveryRecord(TimeStampedModel):
    order = models.OneToOneField(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="delivery_record",
        verbose_name="訂單",
    )
    recipient_name = models.CharField("實際收車人", max_length=160)
    recipient_phone = models.CharField("收車人電話", max_length=30)
    carrier_name = models.CharField("託運公司", max_length=160, blank=True)
    handover_location = models.CharField("實際交付地點", max_length=250)
    vehicle_condition_note = models.TextField("交付車況")
    condition_checked = models.BooleanField("已核對車況", default=False)
    documents_checked = models.BooleanField("已核對交付文件", default=False)
    keys_checked = models.BooleanField("已核對鑰匙", default=False)
    accessories_checked = models.BooleanField("已核對配件與贈品", default=False)
    payment_checked = models.BooleanField("已核對收款狀態", default=False)
    damage_found = models.BooleanField("發現刮傷或損壞", default=False)
    damage_note = models.TextField("刮傷／損壞說明", blank=True)
    handover_photo = models.ImageField(
        "交付照片", upload_to="orders/delivery/%Y/%m/", blank=True
    )
    note = models.TextField("交付備註", blank=True)
    completed_by = models.CharField("交付登記人員", max_length=150)

    class Meta:
        verbose_name = "交付紀錄"
        verbose_name_plural = "交付紀錄"

    def clean(self):
        errors = {}
        for field_name, label in (
            ("condition_checked", "車況"),
            ("documents_checked", "交付文件"),
            ("keys_checked", "鑰匙"),
            ("accessories_checked", "配件與贈品"),
            ("payment_checked", "收款狀態"),
        ):
            if not getattr(self, field_name):
                errors[field_name] = f"必須完成{label}核對。"
        if self.damage_found and not self.damage_note.strip():
            errors["damage_note"] = "發現刮傷或損壞時必須填寫說明。"
        if (
            self.order_id
            and self.order.delivery_method == SalesOrder.DeliveryMethod.CARRIER
            and not self.carrier_name.strip()
        ):
            errors["carrier_name"] = "委託託運時必須填寫託運公司。"
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.order.number}／{self.recipient_name}"


class OrderOperationsProfile(TimeStampedModel):
    MANUAL_PROTECTABLE_FINANCIAL_FIELDS = (
        "registration_tax_expense",
        "compulsory_insurance_expense",
        "plate_selection_expense",
        "registration_tax_income",
        "compulsory_insurance_income",
        "plate_selection_income",
        "sales_bonus",
        "promotion_subsidy",
        "installment_interest_subsidy",
        "actual_disbursement",
        "dealer_commission_expense",
    )

    class AgencyStatus(models.TextChoices):
        NOT_SUBMITTED = "not_submitted", "未送件"
        SUBMITTED = "submitted", "已送件"
        SUPPLEMENT = "supplement", "待補件"
        REVIEWING = "reviewing", "審核中"
        APPROVED = "approved", "已核准"
        PAID = "paid", "已撥款"
        NOT_APPLICABLE = "not_applicable", "不適用"

    order = models.OneToOneField(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="operations",
        verbose_name="訂單",
    )
    dealer_name = models.CharField("車行", max_length=160, blank=True)
    actual_disbursement = models.DecimalField("實際撥款", max_digits=12, decimal_places=0, default=0)
    vehicle_cost = models.DecimalField("車輛成本", max_digits=12, decimal_places=0, default=0)
    vehicle_cost_manual = models.BooleanField("車輛成本已人工調整", default=False)
    vehicle_cost_rule = models.ForeignKey(
        VehicleSettlementCostRule,
        on_delete=models.SET_NULL,
        related_name="order_snapshots",
        verbose_name="套用成本規則",
        blank=True,
        null=True,
    )
    vehicle_cost_registration_date = models.DateField(
        "成本認列領牌日",
        blank=True,
        null=True,
    )
    vehicle_cost_locked_at = models.DateTimeField(
        "成本鎖定時間",
        blank=True,
        null=True,
    )
    vehicle_cost_locked_by = models.CharField(
        "成本鎖定人員",
        max_length=150,
        blank=True,
    )
    incentive_rule = models.ForeignKey(
        VehicleIncentiveRule,
        on_delete=models.SET_NULL,
        related_name="order_snapshots",
        verbose_name="套用獎勵補助版本",
        blank=True,
        null=True,
    )
    incentive_registration_date = models.DateField(
        "獎勵補助認列領牌日",
        blank=True,
        null=True,
    )
    incentive_locked_at = models.DateTimeField(
        "獎勵補助鎖定時間",
        blank=True,
        null=True,
    )
    incentive_locked_by = models.CharField(
        "獎勵補助鎖定人員",
        max_length=150,
        blank=True,
    )
    manual_financial_fields = models.JSONField(
        "已人工調整財務欄位",
        default=list,
        blank=True,
        help_text="記錄不應再被訂單同步覆蓋的收支欄位。",
    )
    registration_tax_expense = models.DecimalField("領牌稅金支出", max_digits=12, decimal_places=0, default=0)
    compulsory_insurance_expense = models.DecimalField("強制險支出", max_digits=12, decimal_places=0, default=0)
    plate_selection_expense = models.DecimalField("選號支出", max_digits=12, decimal_places=0, default=0)
    gift_expense = models.DecimalField("贈品支出", max_digits=12, decimal_places=0, default=0)
    shipping_expense = models.DecimalField("運費支出", max_digits=12, decimal_places=0, default=0)
    dealer_commission_expense = models.DecimalField("車行傭金支出", max_digits=12, decimal_places=0, default=0)
    dealer_commission_base = models.DecimalField(
        "車行基礎佣金快照", max_digits=12, decimal_places=0, default=0
    )
    dealer_commission_adjustment = models.DecimalField(
        "車行加減佣金快照", max_digits=12, decimal_places=0, default=0
    )
    dealer_commission_policy = models.ForeignKey(
        SalesSourceBrandPolicy,
        on_delete=models.SET_NULL,
        related_name="order_snapshots",
        verbose_name="套用車行品牌規則",
        blank=True,
        null=True,
    )
    dealer_commission_registration_date = models.DateField(
        "車行佣金認列領牌日", blank=True, null=True
    )
    dealer_commission_locked_at = models.DateTimeField(
        "車行佣金鎖定時間", blank=True, null=True
    )
    card_fee_expense = models.DecimalField("銀行刷卡手續費支出", max_digits=12, decimal_places=0, default=0)
    registration_tax_income = models.DecimalField("領牌稅金收入", max_digits=12, decimal_places=0, default=0)
    compulsory_insurance_income = models.DecimalField("強制險收入", max_digits=12, decimal_places=0, default=0)
    agency_fee_income = models.DecimalField("代辦費收入", max_digits=12, decimal_places=0, default=0)
    plate_selection_income = models.DecimalField("選號收入", max_digits=12, decimal_places=0, default=0)
    installment_fee_income = models.DecimalField("分期手續費收入", max_digits=12, decimal_places=0, default=0)
    card_fee_income = models.DecimalField("刷卡手續費收入", max_digits=12, decimal_places=0, default=0)
    other_income = models.DecimalField("其他收入", max_digits=12, decimal_places=0, default=0)
    scrap_agency_income = models.DecimalField("報廢代辦收入", max_digits=12, decimal_places=0, default=0)
    scrap_vehicle_income = models.DecimalField("報廢車收入", max_digits=12, decimal_places=0, default=0)
    sales_bonus = models.DecimalField("實銷獎勵金", max_digits=12, decimal_places=0, default=0)
    promotion_subsidy = models.DecimalField("促銷補助金", max_digits=12, decimal_places=0, default=0)
    installment_interest_subsidy = models.DecimalField("分期補貼息", max_digits=12, decimal_places=0, default=0)
    insurance_commission = models.DecimalField("強制險傭金", max_digits=12, decimal_places=0, default=0)
    credit_card_commission = models.DecimalField("信用卡傭金", max_digits=12, decimal_places=0, default=0)
    payment_confirmed = models.BooleanField("確認收款", default=False)
    installment_transfer_confirmed = models.BooleanField("分期公司確認匯款", default=False)
    invoice_date = models.DateField("發票日期", blank=True, null=True)
    balance_invoice_number = models.CharField("尾款發票號碼", max_length=80, blank=True)
    subsidy_amount = models.DecimalField("補助金額", max_digits=12, decimal_places=0, default=0)
    bank_name = models.CharField("銀行", max_length=120, blank=True)
    remittance_account = models.CharField("匯款帳戶", max_length=120, blank=True)
    subsidy_applied_on = models.DateField("申請日", blank=True, null=True)
    industry_bureau_status = models.CharField("工業局", max_length=30, choices=AgencyStatus.choices, default=AgencyStatus.NOT_SUBMITTED)
    environment_ministry_status = models.CharField("環境部", max_length=30, choices=AgencyStatus.choices, default=AgencyStatus.NOT_SUBMITTED)
    local_government_status = models.CharField("縣市政府", max_length=30, choices=AgencyStatus.choices, default=AgencyStatus.NOT_SUBMITTED)
    old_vehicle_engine_number = models.CharField("舊車引擎號碼", max_length=80, blank=True)
    old_vehicle_brand = models.CharField("舊車廠牌", max_length=120, blank=True)
    old_vehicle_displacement_cc = models.PositiveSmallIntegerField("舊車排氣量", blank=True, null=True)
    old_vehicle_manufactured_on = models.DateField("舊車出廠日期", blank=True, null=True)
    scrapped_on = models.DateField("報廢日期", blank=True, null=True)
    recycled_on = models.DateField("回收日期", blank=True, null=True)
    vehicle_control_account = models.CharField("車控帳號", max_length=160, blank=True)
    vehicle_control_password_encrypted = models.TextField("車控密碼（加密）", blank=True)
    battery_plan = models.CharField("電池合約方案", max_length=160, blank=True)
    battery_activated_on = models.DateField("電池合約啟用日期", blank=True, null=True)
    battery_account = models.CharField("電池合約帳號", max_length=160, blank=True)
    battery_password_encrypted = models.TextField("電池合約密碼（加密）", blank=True)
    helmet = models.CharField("安全帽", max_length=250, blank=True)
    company_gift_or_remittance = models.CharField("公司禮券、匯款", max_length=250, blank=True)
    other_fulfillment = models.TextField("其他", blank=True)
    platform_gift = models.CharField("平台贈品", max_length=250, blank=True)
    customer_service_phone = models.CharField("客服電話", max_length=50, blank=True)
    installment_info = models.TextField("分期資訊", blank=True)
    updated_by = models.CharField("最後更新人員", max_length=150, blank=True)

    INCOME_FIELDS = (
        "registration_tax_income", "compulsory_insurance_income",
        "agency_fee_income", "plate_selection_income", "installment_fee_income",
        "card_fee_income", "other_income", "scrap_agency_income",
        "scrap_vehicle_income",
    )
    EXPENSE_FIELDS = (
        "registration_tax_expense",
        "compulsory_insurance_expense", "plate_selection_expense",
        "gift_expense", "shipping_expense", "dealer_commission_expense",
        "card_fee_expense",
    )
    INCENTIVE_FIELDS = (
        "sales_bonus",
        "promotion_subsidy",
        "installment_interest_subsidy",
        "insurance_commission",
        "credit_card_commission",
    )

    @property
    def total_income(self):
        return sum(
            (getattr(self, field) or Decimal("0") for field in self.INCOME_FIELDS),
            Decimal("0"),
        )

    @property
    def total_expense(self):
        return sum(
            (getattr(self, field) or Decimal("0") for field in self.EXPENSE_FIELDS),
            Decimal("0"),
        )

    @property
    def net_profit(self):
        incentive_total = sum(
            (
                getattr(self, field) or Decimal("0")
                for field in self.INCENTIVE_FIELDS
            ),
            Decimal("0"),
        )
        return (
            (self.actual_disbursement or Decimal("0"))
            - (self.vehicle_cost or Decimal("0"))
            - self.total_expense
            + self.total_income
            + incentive_total
        )

    @property
    def total_received(self):
        prefetched = getattr(self.order, "_prefetched_objects_cache", {}).get(
            "payment_records"
        )
        if prefetched is not None:
            return sum(
                (
                    record.received_amount or Decimal("0")
                    for record in prefetched
                    if record.confirmed
                ),
                Decimal("0"),
            )
        return self.order.payment_records.filter(confirmed=True).aggregate(
            total=models.Sum("received_amount")
        )["total"] or Decimal("0")

    class Meta:
        verbose_name = "訂單營運資料"
        verbose_name_plural = "訂單營運資料"


class PaymentRecord(TimeStampedModel):
    order = models.ForeignKey(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="payment_records",
        verbose_name="訂單",
    )
    system_key = models.CharField(
        "系統同步代碼",
        max_length=40,
        blank=True,
        help_text="空白代表人工新增的收款紀錄。",
    )
    item_name = models.CharField("收款項目", max_length=160)
    expected_amount = models.DecimalField("應收金額", max_digits=12, decimal_places=0, default=0)
    expected_amount_overridden = models.BooleanField(
        "預計金額已人工調整",
        default=False,
        editable=False,
    )
    expected_amount_override_reason = models.CharField(
        "預計金額調整原因",
        max_length=250,
        blank=True,
    )
    received_amount = models.DecimalField("實收金額", max_digits=12, decimal_places=0, default=0)
    card_principal = models.DecimalField(
        "刷卡本金",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    card_fee_charged = models.DecimalField(
        "向客戶收取手續費",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    bank_card_fee = models.DecimalField(
        "銀行實扣手續費",
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    received_on = models.DateField("收款日期", blank=True, null=True)
    payment_method = models.CharField("付款方式", max_length=50, blank=True)
    receiving_account = models.CharField("收款帳戶", max_length=120, blank=True)
    confirmed = models.BooleanField("已確認", default=False)
    confirmed_by = models.CharField("確認人員", max_length=150, blank=True)
    confirmed_at = models.DateTimeField("確認時間", blank=True, null=True)
    proof = models.FileField("匯款／收款證明", upload_to="orders/payments/%Y/%m/", blank=True)
    note = models.CharField("備註", max_length=250, blank=True)

    @property
    def card_fee_difference(self):
        return (self.card_fee_charged or Decimal("0")) - (
            self.bank_card_fee or Decimal("0")
        )

    @property
    def outstanding_amount(self):
        return max(
            (self.expected_amount or Decimal("0"))
            - (self.received_amount or Decimal("0")),
            Decimal("0"),
        )

    @property
    def is_settled(self):
        return bool(
            (self.expected_amount or Decimal("0")) <= 0
            or (self.confirmed and self.outstanding_amount <= 0)
        )

    class Meta:
        ordering = ["received_on", "id"]
        indexes = [
            models.Index(
                fields=["order", "confirmed"], name="payment_order_confirmed_idx"
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "system_key"],
                condition=~models.Q(system_key=""),
                name="unique_order_system_payment",
            )
        ]
        verbose_name = "收款紀錄"
        verbose_name_plural = "收款紀錄"


class RegistrationDocument(TimeStampedModel):
    class DocumentType(models.TextChoices):
        NEW_LICENSE = "new_license", "新行照照片"
        REGISTRATION_APPLICATION = (
            "registration_application",
            "新車領牌登記書",
        )
        MOTOR_VEHICLE_RECEIPT = "motor_vehicle_receipt", "監理站單據"
        INVOICE = "invoice", "發票"
        COMPULSORY_INSURANCE = "compulsory_insurance", "強制險單"
        PLATE_SELECTION = "plate_selection", "選號單"
        OTHER_INSURANCE = "other_insurance", "其他保險單"

    @classmethod
    def retired_document_types(cls):
        """保留歷史檔案與顯示名稱，但不再接受新上傳或列入流程。"""
        return frozenset(
            {
                cls.DocumentType.MOTOR_VEHICLE_RECEIPT,
                cls.DocumentType.COMPULSORY_INSURANCE,
            }
        )

    @classmethod
    def active_fixed_document_types(cls):
        return (
            cls.DocumentType.NEW_LICENSE,
            cls.DocumentType.REGISTRATION_APPLICATION,
            cls.DocumentType.INVOICE,
            cls.DocumentType.PLATE_SELECTION,
        )

    order = models.ForeignKey(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="registration_documents",
        verbose_name="訂單",
    )
    document_type = models.CharField(
        "文件類型", max_length=40, choices=DocumentType.choices
    )
    name = models.CharField("文件名稱", max_length=160, blank=True)
    file = models.FileField(
        "檔案", upload_to="orders/registration/%Y/%m/"
    )
    uploaded_by = models.CharField("上傳人員", max_length=150, blank=True)

    class Meta:
        ordering = ["document_type", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "document_type"],
                condition=~models.Q(document_type="other_insurance"),
                name="unique_fixed_registration_document",
            )
        ]
        verbose_name = "領牌文件"
        verbose_name_plural = "領牌文件"

    @property
    def display_name(self):
        return self.name or self.get_document_type_display()

    def delete_with_file(self):
        stored_file = self.file
        super().delete()
        if stored_file:
            stored_file.delete(save=False)

    def __str__(self):
        return f"{self.order.number}／{self.display_name}"


class SubsidyDocument(TimeStampedModel):
    class DocumentType(models.TextChoices):
        OLD_OWNER_ID_FRONT = "old_owner_id_front", "舊車主身分證正面"
        OLD_OWNER_ID_BACK = "old_owner_id_back", "舊車主身分證反面"
        OLD_VEHICLE_REGISTRATION = "old_vehicle_registration", "舊車行照"
        SCRAP_CERTIFICATE = "scrap_certificate", "報廢證明"
        RECYCLING_RECEIPT = "recycling_receipt", "回收管制聯"
        NEW_OWNER_BANKBOOK = "new_owner_bankbook", "新車主存摺封面"
        OLD_OWNER_BANKBOOK = "old_owner_bankbook", "舊車主存摺封面"
        OWNER_DECLARATION = "owner_declaration", "新舊車主不同人聲明書"
        OTHER = "other", "其他補助文件"

    order = models.ForeignKey(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="subsidy_documents",
        verbose_name="訂單",
    )
    document_type = models.CharField(
        "文件類型", max_length=40, choices=DocumentType.choices
    )
    name = models.CharField("文件名稱", max_length=160, blank=True)
    note = models.CharField("備註", max_length=250, blank=True)
    file = models.FileField(
        "檔案", upload_to="orders/subsidy/%Y/%m/"
    )
    uploaded_by = models.CharField("上傳人員", max_length=150, blank=True)

    class Meta:
        ordering = ["document_type", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "document_type"],
                condition=~models.Q(document_type="other"),
                name="unique_subsidy_document",
            )
        ]
        verbose_name = "汰舊補助文件"
        verbose_name_plural = "汰舊補助文件"

    def delete_with_file(self):
        stored_file = self.file
        super().delete()
        if stored_file:
            stored_file.delete(save=False)

    def __str__(self):
        return f"{self.order.number}／{self.name or self.get_document_type_display()}"


class OrderDraft(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data = models.JSONField("草稿內容", default=dict, blank=True)
    id_front = models.ImageField(
        "證件正面", upload_to="drafts/id/%Y/%m/", blank=True
    )
    id_back = models.ImageField(
        "證件反面", upload_to="drafts/id/%Y/%m/", blank=True
    )
    revision = models.PositiveIntegerField("版本", default=1)
    created_by = models.CharField("建立人員", max_length=150, blank=True)
    updated_by = models.CharField("最後編輯人員", max_length=150, blank=True)
    editing_session = models.CharField("編輯工作階段", max_length=40, blank=True)
    editing_by = models.CharField("目前編輯人員", max_length=150, blank=True)
    editing_at = models.DateTimeField("最後編輯心跳", blank=True, null=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "訂單草稿"
        verbose_name_plural = "訂單草稿"

    @property
    def display_name(self):
        return self.data.get("owner_name") or "尚未填寫車主"

    @property
    def display_vehicle(self):
        model_id = self.data.get("vehicle_model")
        if not model_id:
            return "尚未選擇車型"
        vehicle = VehicleModel.objects.filter(pk=model_id).first()
        return str(vehicle) if vehicle else "原車型已不存在"

    def delete_with_files(self):
        front = self.id_front
        back = self.id_back
        super().delete()
        if front:
            front.delete(save=False)
        if back:
            back.delete(save=False)


class DraftFieldState(models.Model):
    draft = models.ForeignKey(
        OrderDraft, on_delete=models.CASCADE, related_name="field_states"
    )
    field_key = models.CharField("欄位識別碼", max_length=200)
    value = models.JSONField("欄位值", default=str)
    version = models.PositiveIntegerField("欄位版本", default=0)
    updated_by = models.CharField("最後編輯人員", max_length=150, blank=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["draft", "field_key"], name="unique_draft_field_state"
            )
        ]


class DraftFieldPresence(models.Model):
    draft = models.ForeignKey(
        OrderDraft, on_delete=models.CASCADE, related_name="field_presences"
    )
    session_key = models.CharField("編輯工作階段", max_length=40)
    client_id = models.CharField("瀏覽器連線", max_length=64)
    field_key = models.CharField("目前欄位", max_length=200, blank=True)
    editing_by = models.CharField("編輯人員", max_length=150)
    color = models.CharField("識別顏色", max_length=20, blank=True)
    updated_at = models.DateTimeField("最後活動時間", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["draft", "session_key", "client_id"],
                name="unique_draft_editor_client",
            )
        ]


class AccessoryLine(TimeStampedModel):
    class LineType(models.TextChoices):
        PURCHASE = "purchase", "加購"
        GIFT = "gift", "贈送"

    order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="accessories"
    )
    accessory_product = models.ForeignKey(
        AccessoryProduct,
        on_delete=models.PROTECT,
        related_name="order_lines",
        verbose_name="配件主檔",
        blank=True,
        null=True,
    )
    name = models.CharField("配件名稱", max_length=160)
    quantity = models.PositiveSmallIntegerField("數量", default=1)
    line_type = models.CharField(
        "類型", max_length=20, choices=LineType.choices, default=LineType.PURCHASE
    )
    amount = models.DecimalField(
        "配件售價", max_digits=12, decimal_places=0, default=0
    )
    labor_fee = models.DecimalField(
        "安裝工資", max_digits=12, decimal_places=0, default=0
    )
    note = models.CharField("備註", max_length=250, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "配件"
        verbose_name_plural = "配件"

    @property
    def line_total(self):
        if self.line_type == self.LineType.GIFT:
            return 0
        return (self.amount + self.labor_fee) * self.quantity

    @property
    def display_total(self):
        return (self.amount + self.labor_fee) * self.quantity

    def __str__(self):
        return self.name


class OtherFeeLine(TimeStampedModel):
    order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="other_fees"
    )
    name = models.CharField("費用項目", max_length=160)
    amount = models.DecimalField("金額", max_digits=12, decimal_places=0)

    class Meta:
        ordering = ["id"]
        verbose_name = "其他費用"
        verbose_name_plural = "其他費用"

    def __str__(self):
        return self.name


class OrderEvent(TimeStampedModel):
    order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField("事件類型", max_length=50)
    description = models.TextField("內容")
    actor_name = models.CharField("操作人員", max_length=150, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "訂單事件"
        verbose_name_plural = "訂單事件"


class OrderChange(TimeStampedModel):
    order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="changes"
    )
    reason = models.TextField("變更原因")
    changes = models.JSONField("欄位變更", default=dict)
    actor_name = models.CharField("操作人員", max_length=150)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "訂單變更"
        verbose_name_plural = "訂單變更"


class SalesOrderSearchIndex(TimeStampedModel):
    order = models.OneToOneField(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="search_index",
        primary_key=True,
    )
    search_text = models.TextField("搜尋文字", blank=True)
    match_payload = models.JSONField("命中欄位資料", default=list, blank=True)

    class Meta:
        verbose_name = "訂單搜尋索引"
        verbose_name_plural = "訂單搜尋索引"


class IdOcrJob(TimeStampedModel):
    class DocumentType(models.TextChoices):
        NATIONAL_ID = "national_id", "國民身分證"
        RESIDENT_CERTIFICATE = "resident_certificate", "居留證"

    class Status(models.TextChoices):
        QUEUED = "queued", "排隊中"
        RUNNING = "running", "辨識中"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "失敗"
        INVALIDATED = "invalidated", "已失效"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="id_ocr_jobs",
    )
    front = models.ImageField("證件正面", upload_to="ocr_jobs/%Y/%m/")
    back = models.ImageField("證件反面", upload_to="ocr_jobs/%Y/%m/")
    document_type = models.CharField(
        "證件類型",
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.NATIONAL_ID,
    )
    photo_token = models.CharField("照片版本", max_length=80)
    status = models.CharField(
        "狀態", max_length=20, choices=Status.choices, default=Status.QUEUED
    )
    result = models.JSONField("辨識結果", default=dict, blank=True)
    error = models.CharField("錯誤訊息", max_length=500, blank=True)
    attempts = models.PositiveSmallIntegerField("嘗試次數", default=0)
    started_at = models.DateTimeField("開始時間", blank=True, null=True)
    finished_at = models.DateTimeField("完成時間", blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_by", "status", "-created_at"]),
        ]


class UserAppearancePreference(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="appearance_preference",
        verbose_name="使用者",
    )
    theme = models.CharField(
        "介面主題",
        max_length=30,
        choices=THEME_CHOICES,
        default=DEFAULT_THEME,
    )

    class Meta:
        verbose_name = "使用者外觀偏好"
        verbose_name_plural = "使用者外觀偏好"

    def __str__(self):
        return f"{self.user.get_username()}－{self.get_theme_display()}"


class UserSecurityProfile(TimeStampedModel):
    """保存登入安全狀態；不保存任何明碼密碼。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="security_profile",
        verbose_name="使用者",
    )
    must_change_password = models.BooleanField("下次登入須變更密碼", default=False)
    password_changed_at = models.DateTimeField("密碼變更時間", blank=True, null=True)

    class Meta:
        verbose_name = "使用者安全設定"
        verbose_name_plural = "使用者安全設定"

    def __str__(self):
        return self.user.get_username()


class UserAccountAuditLog(TimeStampedModel):
    class Action(models.TextChoices):
        CREATE = "create", "建立帳號"
        UPDATE = "update", "修改帳號"
        ACTIVATE = "activate", "啟用帳號"
        DEACTIVATE = "deactivate", "停用帳號"
        RESET_PASSWORD = "reset_password", "重設密碼"
        CHANGE_PASSWORD = "change_password", "使用者變更密碼"
        GRANT_ADMIN = "grant_admin", "授予管理者"
        REVOKE_ADMIN = "revoke_admin", "移除管理者"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="account_actions_performed",
        verbose_name="操作人",
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="account_actions_received",
        verbose_name="對象",
    )
    target_username = models.CharField("帳號快照", max_length=150)
    action = models.CharField("動作", max_length=30, choices=Action.choices)
    description = models.CharField("說明", max_length=500)
    metadata = models.JSONField("變更摘要", default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "帳號異動紀錄"
        verbose_name_plural = "帳號異動紀錄"
        indexes = [
            models.Index(fields=["target", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()}－{self.target_username}"
