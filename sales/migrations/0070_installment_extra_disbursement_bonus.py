from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0069_canonicalize_dr_z4s_model_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="installmentplanoption",
            name="extra_disbursement_bonus",
            field=models.DecimalField(
                decimal_places=0,
                default=0,
                help_text="分期公司在基礎撥款外另給的獎金；會加進預估撥款總額。",
                max_digits=12,
                validators=[MinValueValidator(0)],
                verbose_name="額外撥款獎金",
            ),
        ),
    ]
