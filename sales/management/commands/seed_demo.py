from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from sales.models import SalesSource, Store, VehicleColor, VehicleModel


class Command(BaseCommand):
    help = "建立第一版示範門市、來源、車型與管理員"

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default=None)

    def handle(self, *args, **options):
        stores = [("總店", "HQ"), ("二店", "S02"), ("三店", "S03")]
        for name, code in stores:
            Store.objects.get_or_create(code=code, defaults={"name": name})

        SalesSource.objects.get_or_create(
            source_type=SalesSource.SourceType.DEALER, name="示範合作車行"
        )
        SalesSource.objects.get_or_create(
            source_type=SalesSource.SourceType.PLATFORM, name="示範網路平台"
        )

        model, _ = VehicleModel.objects.get_or_create(
            brand="SUZUKI",
            name="SUI 125",
            defaults={
                "energy_type": VehicleModel.EnergyType.GAS,
                "displacement_cc": 125,
            },
        )
        if not model.displacement_cc:
            model.displacement_cc = 125
            model.save(update_fields=["displacement_cc", "updated_at"])
        for color in ("白", "黑", "灰"):
            VehicleColor.objects.get_or_create(vehicle_model=model, name=color)

        password = options["password"]
        if password:
            user, created = get_user_model().objects.get_or_create(
                username=options["username"],
                defaults={"is_staff": True, "is_superuser": True},
            )
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS("已建立管理員帳號。"))
            else:
                self.stdout.write("管理員帳號已存在，未修改密碼。")

        self.stdout.write(self.style.SUCCESS("示範主檔建立完成。"))

