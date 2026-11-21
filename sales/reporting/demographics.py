"""人口分類僅供分析；不輸出證號、不回寫訂單，舊口徑只供核對。"""
from django.db.models import Case, CharField, Q, Value, When
from django.db.models.functions import ExtractYear, Substr, Trim, Upper
from django.utils import timezone


DEMOGRAPHIC_DIMENSIONS = {
    "age_group": "年齡層（生日未填獨立列示）",
    "sex": "性別（公司或其他獨立列示）",
    "legacy_age_group": "原報表年齡層（比對用）",
    "legacy_sex": "原報表性別（比對用）",
}


def demographic_query(queryset, dimension, alias):
    today = timezone.localdate()
    queryset = queryset.annotate(
        report_demographic_age=Value(today.year) - ExtractYear("owner_birth_date"),
        report_id_normalized=Upper(Trim("owner_id_number")),
        report_legacy_sex_code=Substr("owner_id_number", 2, 1),
    )
    if dimension in ("sex", "legacy_sex"):
        if dimension == "legacy_sex":
            conditions = [
                When(report_legacy_sex_code__in=("1", "8"), then=Value("男性")),
                When(report_legacy_sex_code__in=("2", "9"), then=Value("女性")),
            ]
            fallback = "未填寫或格式錯誤"
        else:
            # 格式辨識不等於身分驗證。法人優先排除，不能由統編第二碼猜性別。
            male = (Q(owner_type="local", report_id_normalized__regex=r"^[A-Z]1[0-9]{8}$")
                    | Q(owner_type="foreign", report_id_normalized__regex=r"^[A-Z]8[0-9]{8}$"))
            female = (Q(owner_type="local", report_id_normalized__regex=r"^[A-Z]2[0-9]{8}$")
                      | Q(owner_type="foreign", report_id_normalized__regex=r"^[A-Z]9[0-9]{8}$"))
            conditions = [When(male, then=Value("男性")), When(female, then=Value("女性"))]
            fallback = "公司或其他"
    else:
        conditions = []
        if dimension == "age_group":
            conditions = [
                # 歷史匯入沒有設定 owner_type，八碼統編不能因預設 local 而當自然人。
                When(Q(owner_type="company") | Q(report_id_normalized__regex=r"^[0-9]{8}$"), then=Value("公司或其他")),
                When(owner_birth_date__isnull=True, then=Value("生日未填")),
                When(owner_birth_date__gt=today, then=Value("生日異常")),
            ]
        conditions += [When(report_demographic_age__lt=20, then=Value("20歲以下"))]
        conditions += [
            When(report_demographic_age__range=(start, start + 9), then=Value(f"{start}-{start + 9}歲"))
            for start in (20, 30, 40, 50)
        ]
        fallback = "60歲以上"
    return queryset.annotate(**{alias: Case(*conditions, default=Value(fallback), output_field=CharField())})


# T-268：年齡層依年齡排序並固定配色（使用者 2026-11-21 同意）。原本用字串排序，「20-29歲」會排在「20歲以下」前面，
# 細分系列又依出現順序配色，同一年齡層在不同圖顏色不同。只改順序與顏色，分組與數字不變。
AGE_DIMENSIONS = ("age_group", "legacy_age_group")
AGE_GROUP_ORDER = ("20歲以下", "20-29歲", "30-39歲", "40-49歲", "50-59歲", "60歲以上", "生日未填", "生日異常", "公司或其他")
AGE_GROUP_COLORS = {
    "20歲以下": "var(--chart-s1)", "20-29歲": "var(--chart-s2)", "30-39歲": "var(--chart-s3)",
    "40-49歲": "var(--chart-s4)", "50-59歲": "var(--chart-s5)", "60歲以上": "var(--chart-s6)",
    # 三個獨立列示的類別用三種灰階，堆疊在一起時仍分得出來。
    "生日未填": "var(--chart-other)", "生日異常": "var(--chart-other-2)", "公司或其他": "var(--chart-other-3)",
}


def age_sort_key(label):
    return (AGE_GROUP_ORDER.index(label) if label in AGE_GROUP_ORDER else len(AGE_GROUP_ORDER), label or "")
