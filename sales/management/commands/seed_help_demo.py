"""使用說明截圖用的合成資料（T-197）。只能寫進空白或只有合成資料的 SQLite，正式資料庫一律拒絕。

由 tools/help_screens/run.py 在暫存資料庫呼叫；全部資料都是虛構的：
客人「王小明」「示範客戶01–30」、車行「示範車行甲乙丙」、引擎號碼 DEMOE 開頭。
"""
import io
import os
import random
import uuid
from datetime import date, datetime, time
from decimal import Decimal as D

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from sales.models import (
    AccessoryCategory, AccessoryProduct, BrandRegistrationFeeRule, InstallmentCompany, InstallmentPlanOption,
    InstallmentPlanVersion, OrderDraft, PrintCompany, SalesOrder, SalesSource, Store, SubsidyProgram, VehicleBrand,
    VehicleColor, VehicleInventory, VehicleModel, VehiclePriceVersion, VehicleSettlementCostRule,
)

START = date(2026, 1, 1)
DEMO_PHONE_PREFIX = "0900-000-"  # 合成訂單的電話開頭；用來判斷資料庫裡是否只有合成資料
# 30 張示範訂單：(月, 日, 車型序號, 來源, 付款)。寫死而不用亂數，說明範例的數字才固定：
# 2026/09/01～11/30 共 23 張：本店 11、示範網路平台 5、示範車行丙 4（全是 SUI 125）、甲 2、乙 1（〈報表中心〉篇）。
# 示範車行丙 10 月 3 張（10/12 分期、10/19 現金、10/28 分期）走真正的配車與確認領牌，傭金固定、達到台數獎金門檻（〈車行傭金與台數獎金〉篇）。
ORDERS = (
    (6, 12, 0, "store", "cash"), (6, 25, 1, "示範車行甲", "installment"), (7, 8, 2, "store", "installment"),
    (7, 21, 0, "示範車行乙", "cash"), (8, 3, 1, "store", "installment"), (8, 15, 0, "platform", "installment"),
    (8, 27, 2, "示範車行丙", "cash"),
    (9, 2, 0, "store", "installment"), (9, 5, 0, "示範車行丙", "cash"), (9, 11, 0, "platform", "installment"),
    (9, 17, 2, "store", "cash"), (9, 22, 0, "示範車行甲", "installment"), (9, 28, 1, "store", "installment"),
    (10, 3, 0, "store", "cash"), (10, 8, 2, "platform", "installment"), (10, 12, 0, "示範車行丙", "installment"),
    (10, 19, 0, "示範車行丙", "cash"), (10, 23, 1, "store", "installment"), (10, 26, 2, "示範車行乙", "cash"),
    (10, 30, 0, "platform", "installment"),
    (11, 2, 0, "store", "installment"), (11, 3, 1, "store", "cash"), (11, 4, 0, "platform", "installment"),
    (10, 28, 0, "示範車行丙", "installment"), (11, 8, 2, "store", "installment"), (11, 9, 0, "示範車行甲", "cash"),
    (11, 11, 1, "store", "installment"), (11, 12, 0, "platform", "cash"), (11, 14, 2, "store", "installment"),
    (11, 16, 0, "store", "installment"),
)


def demo_id(i):
    """產生通過檢查碼的虛構身分證字號（A 開頭）。"""
    body = [1 if i % 2 else 2] + [int(x) for x in f"{(i * 7919) % 10**7:07d}"]
    total = 1 + 0 * 9 + sum(d * w for d, w in zip(body, (8, 7, 6, 5, 4, 3, 2, 1)))
    return "A" + "".join(map(str, body)) + str((10 - total % 10) % 10)


class Command(BaseCommand):
    help = "建立使用說明截圖用的合成資料（只限空白的本機 SQLite）。"

    def add_arguments(self, parser):
        parser.add_argument("--admin-password", default=os.environ.get("HELP_DEMO_ADMIN_PASSWORD", ""),
                            help="示範 admin 的密碼；只在暫存資料庫使用，不要用真實密碼。")
        parser.add_argument("--confirm-demo-database", action="store_true",
                            help="確認目前資料庫是說明截圖專用的暫存資料庫。")
        parser.add_argument("--manage", action="store_true",
                            help="只補「設定與管理」篇用的資料；在日常篇截圖拍完後才執行，不改變日常篇的畫面與數字。")

    def handle(self, *args, **options):
        self.guard(options)
        random.seed(197)  # 只影響示範客戶的生日
        if options["manage"]:  # 不重設 admin 密碼：截圖程式的登入狀態要繼續有效
            admin = get_user_model().objects.get(username="admin")
            models = list(VehicleModel.objects.filter(name__in=("SUI 125", "示範 150", "示範 Jet")).order_by("pk"))
            self.manage_data(admin, models, options["admin_password"])
            self.stdout.write(self.style.SUCCESS("設定與管理篇的合成資料完成。"))
            return
        admin = self.admin(options["admin_password"])
        models = self.master_data()
        made = self.orders(admin, models)
        self.reports(admin)
        self.stdout.write(self.style.SUCCESS(f"合成資料完成：{len(models)} 個車型、{made} 張示範訂單。"))

    # ── 安全檢查 ────────────────────────────────────────────────
    def guard(self, options):
        if getattr(settings, "IS_PRODUCTION", False) or os.environ.get("POSTGRES_HOST"):
            raise CommandError("正式環境不能建立說明用合成資料。")
        if connection.vendor != "sqlite":
            raise CommandError("只能寫進 SQLite 暫存資料庫。")
        default_db = os.path.abspath(str(settings.BASE_DIR / "db.sqlite3"))
        if os.path.abspath(str(settings.DATABASES["default"]["NAME"])) == default_db:
            raise CommandError("不能寫進專案預設的 db.sqlite3；請用 tools/help_screens/run.py 建立的暫存資料庫。")
        if not options["confirm_demo_database"]:
            raise CommandError("請加上 --confirm-demo-database，確認這是說明截圖專用的暫存資料庫。")
        if SalesOrder.objects.exclude(owner_phone__startswith=DEMO_PHONE_PREFIX).exists():
            raise CommandError("資料庫裡有非合成的訂單，停止執行。")

    # ── 帳號與主檔 ──────────────────────────────────────────────
    def admin(self, password):
        if not password:
            raise CommandError("請用 --admin-password 或 HELP_DEMO_ADMIN_PASSWORD 指定示範 admin 密碼。")
        user, _ = get_user_model().objects.get_or_create(username="admin", defaults={"is_staff": True, "is_superuser": True})
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        return user

    def model(self, brand, name, cc, cash, suggested, colors):
        VehicleBrand.objects.get_or_create(name=brand)
        model, _ = VehicleModel.objects.get_or_create(brand=brand, name=name, defaults=dict(
            energy_type="gas", model_year=2026, model_number=name.replace(" ", "").upper()[:10], model_code="cbs_drum",
            displacement_cc=cc, base_dealer_commission=D(1500)))
        for color in colors:
            VehicleColor.objects.get_or_create(vehicle_model=model, name=color)
        VehiclePriceVersion.objects.get_or_create(vehicle_model=model, effective_from=START, defaults=dict(
            suggested_price=D(suggested), cash_price=D(cash), suggested_price_includes_registration=False, source_note="說明用合成資料"))
        VehicleSettlementCostRule.objects.get_or_create(vehicle_model=model, effective_from=START, defaults=dict(amount=D(int(cash * .85))))
        return model

    def master_data(self):
        store, _ = Store.objects.get_or_create(code="HQ", defaults={"name": "總店"})
        models = [self.model("SUZUKI", "SUI 125", 125, 72000, 76000, ("珍珠白", "消光黑")),
                  self.model("SUZUKI", "示範 150", 150, 89000, 94000, ("石墨灰", "競技藍")),
                  self.model("SYM", "示範 Jet", 125, 79000, 84000, ("亮白", "霧黑"))]
        company, _ = InstallmentCompany.objects.get_or_create(name="示範融資")
        for model in models:
            version, _ = InstallmentPlanVersion.objects.get_or_create(vehicle_model=model, effective_from=START)
            for periods, monthly in ((24, 3500), (30, 2900)):
                InstallmentPlanOption.objects.get_or_create(version=version, company=company, periods=periods, defaults=dict(
                    monthly_amount=D(monthly), opening_fee=D(1500), expected_disbursement_rate=D(92)))
        for brand in ("SUZUKI", "SYM"):
            BrandRegistrationFeeRule.objects.get_or_create(brand=brand, energy_type="gas", effective_from=START, defaults=dict(
                calculation_type="fixed_components", min_cc=0, max_cc=250, fixed_registration_fee=D(706), fixed_compulsory_insurance_fee=D(658)))
        category, _ = AccessoryCategory.objects.get_or_create(name="安全配件")
        for name, price, labor in (("示範安全帽", 1200, 0), ("示範後箱", 1500, 200), ("示範手機架", 600, 100)):
            product, _ = AccessoryProduct.objects.get_or_create(name=name, defaults=dict(
                category=category, sale_price=D(price), labor_fee=D(labor), cost=D(price // 2)))
            product.categories.add(category)
        sui = models[0]
        for i in range(1, 41):
            color = sui.colors.get(name="消光黑" if i % 2 == 0 else "珍珠白")
            VehicleInventory.objects.get_or_create(engine_number=f"DEMOE{i:05d}", defaults=dict(
                vehicle_model=sui, color=color, ownership_store=store, location_store=store,
                received_on=date(2026, 10, 1), manufactured_year_month="2026/09"))
        for name in ("示範車行甲", "示範車行乙", "示範車行丙"):
            SalesSource.objects.get_or_create(source_type="dealer", name=name)
        SalesSource.objects.get_or_create(source_type="platform", name="示範網路平台")
        SubsidyProgram.objects.get_or_create(name="示範新購補助")
        # 遷移時就建好的本店公司資料是真實抬頭；截圖一律換成合成公司（只改暫存資料庫）
        PrintCompany.objects.update_or_create(key="home", defaults=dict(
            legal_name="示範機車行", tax_id="12345678", address="示範市示範路 1 號", phone="02-0000-0000"))
        return models

    # ── 30 張示範訂單：走真正的建單流程，再補領牌確認日 ────────────────
    def orders(self, admin, models):
        if SalesOrder.objects.filter(owner_name__startswith="示範客戶").exists():
            return SalesOrder.objects.filter(owner_name__startswith="示範客戶").count()
        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(admin)
        made = 0
        for i, (month, day, model_index, source_name, pay) in enumerate(ORDERS, 1):
            model = models[model_index]
            color = model.colors.order_by("pk")[i % model.colors.count()]
            if source_name == "store":
                kind, source = "store", ""
            elif source_name == "platform":
                kind, source = "platform", str(SalesSource.objects.get(source_type="platform", name="示範網路平台").pk)
            else:
                kind, source = "dealer", str(SalesSource.objects.get(source_type="dealer", name=source_name).pk)
            version = VehiclePriceVersion.objects.filter(vehicle_model=model).first()
            price = int(version.cash_price if pay == "cash" else version.suggested_price)
            data = self.order_data(i, model, color, kind, source, pay, price)
            if self.submit(client, data, f"示範客戶{i:02d}"):
                registered = date(2026, month, day)
                if source_name == "示範車行丙" and month == 10:
                    self.register_through_flow(f"示範客戶{i:02d}", registered, i)
                else:
                    SalesOrder.objects.filter(owner_name=f"示範客戶{i:02d}").update(
                        order_date=registered, registration_date=registered, registration_completed_by="admin",
                        registration_completed_at=timezone.make_aware(datetime.combine(registered, time(15))),
                        status="completed" if registered < date(2026, 11, 1) else "delivery_pending")
                made += 1
        self.volume_bonus()
        # 〈取消、退款與沒收〉用：還沒領牌、已收現金訂金 3,000 的單（不領牌，不影響報表數字）。
        cancel = self.order_data(31, models[0], models[0].colors.order_by("pk").first(), "store", "", "cash", 72000)
        cancel.update(deposit_amount="3000", deposit_date="2026-11-10", deposit_method="cash", owner_name="示範客戶31")
        self.submit(client, cancel, "示範客戶31")
        # 〈收訂金與登記收款〉用：還沒領牌的分期單，已收訂金 3,000。
        paying = self.order_data(32, models[0], models[0].colors.order_by("pk").first(), "store", "", "installment", 76000)
        paying.update(deposit_amount="3000", deposit_date="2026-11-12", deposit_method="cash", owner_name="示範客戶32")
        self.submit(client, paying, "示範客戶32")
        return made

    # ── 設定與管理類篇章（T-197 第二批）：同事帳號、通路、刪除申請、公告、官網比對、假日 ─────────
    def manage_data(self, admin, models, password):
        from sales.models import (
            BusinessHoliday, OfficialCatalogCheck, OfficialCatalogModel, SalesSourceCooperationProfile, SystemAnnouncement,
        )
        users = {}
        for username, name in (("demo.sales", "示範業務"), ("demo.finance", "示範會計")):
            user, _ = get_user_model().objects.get_or_create(username=username, defaults={"first_name": name})
            user.set_password(password)  # 只存在暫存資料庫；和示範 admin 同一組隨機密碼
            user.save()
            users[username] = user
        SalesSource.objects.get_or_create(source_type="store", name="示範業務", defaults=dict(
            staff_stores=["yusheng"], staff_commission=D(500)))
        for name in ("示範車行甲", "示範車行乙", "示範車行丙"):
            dealer = SalesSource.objects.get(source_type="dealer", name=name)
            if not dealer.address:
                SalesSource.objects.filter(pk=dealer.pk).update(address="新北市示範區示範路 100 號", holiday_gift=True)
            SalesSourceCooperationProfile.objects.get_or_create(source=dealer, cooperation_scope="suzuki_gas", defaults=dict(
                cooperates=True, relationship_type="general"))
        # 〈刪除訂單與還原〉：示範業務送出的刪除申請（還沒領牌、沒有收款）。
        if not SalesOrder.all_objects.filter(owner_name="示範客戶33").exists():
            client = Client(HTTP_HOST="127.0.0.1")
            client.force_login(admin)
            dup = self.order_data(33, models[0], models[0].colors.order_by("pk").first(), "store", "", "cash", 72000)
            self.submit(client, dup, "示範客戶33")
            SalesOrder.objects.filter(owner_name="示範客戶33").update(
                deletion_requested_at=timezone.now(), deletion_requested_by=users["demo.sales"], deletion_request_reason="重複建單")
        if not SystemAnnouncement.objects.exists():
            SystemAnnouncement.objects.create(
                title="12/1 起 SUI 125 現金價調整", body="（合成資料）12/1 起 SUI 125 現金價調整為 73,000，分期總價不變。",
                published=True, pinned=True, audience="all", ends_at=timezone.make_aware(datetime(2026, 12, 31, 23, 59)),
                updated_by="admin")
        BusinessHoliday.objects.get_or_create(date=date(2027, 1, 1), defaults=dict(name="中華民國開國紀念日", source="manual"))
        if not OfficialCatalogModel.objects.exists():
            check = OfficialCatalogCheck.objects.create(brand="sym", status="succeeded", started_at=timezone.now(),
                                                        finished_at=timezone.now(), entries_found=1, pages_total=1, pages_done=1)
            data = {"name": "示範 Jet SR", "year_hint": 2027, "displacement_cc": 125, "main_image_url": "", "price": 86000,
                    "colors": [{"name": "亮白", "code": "", "stem": "", "image_url": ""}]}
            OfficialCatalogModel.objects.create(
                brand="sym", source_key="demo-jet-sr", source_url="https://example.com/demo-jet-sr", name="示範 Jet SR",
                data=data, content_hash="demo", last_seen_at=timezone.now(), last_check=check)

    def register_through_flow(self, owner_name, registered, i):
        """配車＋確認領牌，和畫面上按「確認配車並鎖定」「確認完成並鎖定」相同：傭金固定、會算台數獎金。"""
        from sales.services.registration_edit import finish_registration
        order = SalesOrder.objects.get(owner_name=owner_name)
        SalesOrder.objects.filter(pk=order.pk).update(order_date=date(registered.year, registered.month, 1))
        order.refresh_from_db()
        vehicle = VehicleInventory.objects.filter(vehicle_model=order.vehicle_model, color=order.color, status="available").order_by("pk").first()
        order.allocate(vehicle, actor_name="admin")
        order.refresh_from_db()
        order.registration_date = registered
        order.final_plate_number = f"DEM-{i:04d}"
        order.save()
        ok, message = finish_registration(order, "admin")
        if not ok:
            raise CommandError(f"{owner_name} 確認領牌失敗：{message}")

    def volume_bonus(self):
        """10 月滿 3 台每台加 500；10 月已結束，立刻入帳（和每天 03:50 的排程結果相同）。"""
        from sales.models import DealerVolumeBonusRule, DealerVolumeBonusTier
        from sales.services.volume_bonus import recompute_rule
        rule, created = DealerVolumeBonusRule.objects.get_or_create(name="示範十月台數獎金", defaults=dict(
            starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 31), period_type="month", active=True))
        if created:
            DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=3, bonus_per_vehicle=D(500))
        recompute_rule(rule.pk)

    def order_data(self, i, model, color, kind, source, pay, price):
        installment = pay == "installment"
        return {
            "source_type": kind, "source": source, "owner_type": "local", "owner_name": f"示範客戶{i:02d}", "owner_name_en": "",
            "owner_phone": f"{DEMO_PHONE_PREFIX}{i:03d}", "owner_email": "", "owner_nationality": "",
            "owner_birth_date": f"{random.randint(1965, 2003)}-0{random.randint(1, 9)}-1{random.randint(0, 9)}",
            "owner_address": "示範市示範路1號", "owner_id_number": demo_id(i), "residence_expiry": "", "id_verified": "on",
            "_id_check": "passed", "vehicle_model": str(model.pk), "color": str(color.pk), "payment_type": pay,
            "vehicle_price": str(price), "plate_insurance_fee": "", "installment_opening_fee": "1500" if installment else "0",
            "deposit_amount": "", "deposit_date": "", "deposit_method": "",
            "installment_company": "示範融資" if installment else "", "installment_amount": str(price) if installment else "0",
            "installment_periods": "24" if installment else "0", "installment_monthly": "3500" if installment else "0",
            "installment_applied_on": "", "installment_status": "", "installment_decided_on": "", "trade_in_plate": "",
            "subsidy_type": "", "old_vehicle_valuation": "0", "old_vehicle_tax": "0", "plate_choice": "none",
            "watched_numbers": "", "plate_preference_note": "", "delivery_method": "store_pickup", "delivery_destination": "",
            "note": "", "accessories-TOTAL_FORMS": "0", "accessories-INITIAL_FORMS": "0", "accessories-MIN_NUM_FORMS": "0",
            "accessories-MAX_NUM_FORMS": "1000", "other_fees-TOTAL_FORMS": "0", "other_fees-INITIAL_FORMS": "0",
            "other_fees-MIN_NUM_FORMS": "0", "other_fees-MAX_NUM_FORMS": "1000",
        }

    def submit(self, client, data, owner_name):
        key = str(uuid.uuid4())
        draft = None
        for step in ("vehicle", "owner", "tradein", "delivery", "accessories", "deposit"):
            post = {**data, "_wizard_step": step, "_wizard_action": "next", "_submission_key": key}
            if draft:
                post.update({"_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)})
            if step == "owner":
                post.update(id_front=self.photo(), id_back=self.photo())
            if client.post(reverse("order_create"), post).status_code != 302:
                self.stderr.write(f"{owner_name} 停在「{step}」，略過。")
                return False
            draft = OrderDraft.objects.order_by("-updated_at").first()
        client.post(reverse("order_create"), {**data, "_wizard_step": "confirm", "_wizard_action": "submit",
                                              "_submission_key": key, "_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)})
        return SalesOrder.objects.filter(owner_name=owner_name).exists()

    @staticmethod
    def photo():
        content = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(content, "PNG")
        return SimpleUploadedFile("demo.png", content.getvalue(), content_type="image/png")

    # ── 報表：用系統內建範本 ──────────────────────────────────────
    def reports(self, admin):
        from sales.reporting.models import ReportDefinition, ReportRevision
        from sales.reporting.starters import starter_config
        from sales.reporting.views import results
        for key in ("overview", "channel", "trend"):
            config = starter_config(key)
            if ReportDefinition.objects.filter(published__title=config["title"]).exists():
                continue
            results(config, {})
            report = ReportDefinition.objects.create(draft=config, published=config, version=1, published_at=timezone.now())
            ReportRevision.objects.create(report=report, version=1, action="publish", config=config, actor=admin)
