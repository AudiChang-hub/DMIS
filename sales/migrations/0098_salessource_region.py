from django.db import migrations, models


def populate_sales_source_regions(apps, schema_editor):
    from sales.services.taiwan_address import infer_taiwan_region

    SalesSource = apps.get_model("sales", "SalesSource")
    updates = []
    for source in SalesSource.objects.filter(source_type="dealer").only(
        "id", "address", "city", "district"
    ):
        city, district = infer_taiwan_region(source.address)
        if city or district:
            source.city = city
            source.district = district
            updates.append(source)
    if updates:
        SalesSource.objects.bulk_update(updates, ["city", "district"], batch_size=500)


def clear_sales_source_regions(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesSource.objects.update(city="", district="")


class Migration(migrations.Migration):
    dependencies = [("sales", "0097_remove_shareholder_relationship_type")]

    operations = [
        migrations.AddField(
            model_name="salessource",
            name="city",
            field=models.CharField(
                blank=True,
                choices=[
                    ("臺北市", "臺北市"), ("新北市", "新北市"), ("桃園市", "桃園市"),
                    ("臺中市", "臺中市"), ("臺南市", "臺南市"), ("高雄市", "高雄市"),
                    ("基隆市", "基隆市"), ("新竹市", "新竹市"), ("嘉義市", "嘉義市"),
                    ("新竹縣", "新竹縣"), ("苗栗縣", "苗栗縣"), ("彰化縣", "彰化縣"),
                    ("南投縣", "南投縣"), ("雲林縣", "雲林縣"), ("嘉義縣", "嘉義縣"),
                    ("屏東縣", "屏東縣"), ("宜蘭縣", "宜蘭縣"), ("花蓮縣", "花蓮縣"),
                    ("臺東縣", "臺東縣"), ("澎湖縣", "澎湖縣"), ("金門縣", "金門縣"),
                    ("連江縣", "連江縣"),
                ],
                max_length=20,
                verbose_name="縣市",
            ),
        ),
        migrations.AddField(
            model_name="salessource",
            name="district",
            field=models.CharField(blank=True, max_length=20, verbose_name="行政區"),
        ),
        migrations.AddIndex(
            model_name="salessource",
            index=models.Index(fields=["source_type", "city", "district", "active"], name="sales_src_region_idx"),
        ),
        migrations.RunPython(populate_sales_source_regions, clear_sales_source_regions),
    ]
