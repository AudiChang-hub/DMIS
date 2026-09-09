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
                When(owner_type="company", then=Value("公司或其他")),
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
