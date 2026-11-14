"""依 bikecity 訂購表重建配件主檔（使用者 2026-11-14 T-179 方案 1：斷開連結後全部刪除）。

正式資料寫入，使用者看過 dry-run 同意後才 --apply。訂單上的配件明細是快照（名稱、類型、數量、售價、工資、備註），
斷開主檔連結後原樣保留為歷史紀錄；舊單再存檔不會把舊名稱加回主檔（learn_custom_accessories 只學新列或改名的列）。

- 預設 dry-run：列出要刪的主檔（含被幾列明細引用）、要斷開的明細與訂單數、要刪／建的類別、要建的配件。
- --export：輸出 JSON 備份到 stdout（主檔、類別、被引用明細的快照、相關訂單的簽署指紋與已簽檔名），在主機上導到 backups/ 保存。
- --apply：從 stdin 讀 --export 的備份，確認和目前資料一致後，同一交易內斷開明細、刪舊主檔與舊類別、建新類別與配件，
  每張訂單寫 OrderChange、主檔與類別異動寫 admin LogEntry；最後逐列核對快照與簽署指紋，不一致整筆不做。
- --restore：從 stdin 讀同一份備份，刪掉本指令建立且沒被訂單用到的配件與類別，用原 id 重建舊類別與舊主檔，明細改連回去。
"""
import json
import sys
from decimal import Decimal

from django.contrib.admin.models import ADDITION, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct, OrderChange, SalesOrder
from sales.services.accessory_catalog import normalized_accessory_name

SOURCE = "https://www.bikecity.com.tw/eready/sorder.html"
NOTE = "T-179 依 bikecity 訂購表建立（2026-11-14）"
ACTOR_NAME = "系統（T-179 配件主檔重建）"
CATEGORIES = [("車身部品配件", 10), ("車主周邊配件", 20), ("eReady 精品配件", 30), ("Saluto 精品配件", 40), ("SUI 精品配件", 50)]
# （類別, 名稱, 料錢＝售價, 4 碼編號＝工資）；同名出現在兩類的「SUZUKI 踩發桿」建一筆、掛兩類（使用者 2026-11-14）。
CATALOG = [
    ("車身部品配件", "ASTUTAIN 阿斯圖坦置物箱", 2800, 0),
    ("車身部品配件", "RE MAX PRO 45L SUZUKI聯名軍事鋁箱", 7900, 0),
    ("車身部品配件", "SHAD 行李箱", 1840, 0),
    ("車身部品配件", "[CarPlay] Pernis MS700CL 多媒體連動雙鏡行車記錄器 (選配 胎壓偵測器)", 9900, 2600),
    ("車身部品配件", "[CarPlay] Pernis MS700C 摩托車多媒體連動主機 (選配 胎壓偵測器)", 5990, 1510),
    ("車身部品配件", "[CarPlay] AIO 5 LITE 安心教練 AI智慧行車紀錄器 (選配 胎壓偵測器)", 15880, 2520),
    ("車身部品配件", "Polaroid 寶麗萊 ME206WG Lite 迷你鷹 1080P 雙鏡頭 行車紀錄器", 4990, 1500),
    ("車身部品配件", "Polaroid 寶麗萊 MS283WGS 新小蜂鷹 1080P 夜視雙鏡頭 行車紀錄器", 5990, 1500),
    ("車身部品配件", "Polaroid 寶麗萊 MX200WGS 極清鷹 1080P 真60fps雙鏡頭 行車紀錄器", 6990, 1500),
    ("車身部品配件", "KEWIG 凱威格 《無線充電款》M33A手機架 及 遮陽帽", 2480, 700),
    ("車身部品配件", "TAKEWAY 逆磁浮減震手機架 LA3-PH05-AnvR", 1980, 60),
    ("車身部品配件", "MWUPP 甲殼蟲手機架", 850, 0),
    ("車身部品配件", "EPIC大牌防撞底版", 250, 0),
    ("車主周邊配件", "SUZUKI MotoGP 紀念款安全帽(3/4帽)", 2000, 0),
    ("車主周邊配件", "SUZUKI NHK客製專屬安全帽", 2600, 0),
    ("車主周邊配件", "eReady個性風格安全帽(黑)", 2400, 0),
    ("車主周邊配件", "eReady個性風格安全帽(白)", 2400, 0),
    ("車主周邊配件", "洛克人XDiVE 聯名安全帽(傑洛款)", 3000, 0),
    ("車主周邊配件", "LIGHT PARKA 防潑水外套", 1600, 0),
    ("eReady 精品配件", "腳踏延伸踏板(不含踏墊)", 1180, 120),
    ("eReady 精品配件", "eReady 橡膠腳踏墊", 580, 50),
    ("eReady 精品配件", "日本原廠RK 428黃金油封鍊條 92目", 2000, 390),
    ("eReady 精品配件", "eReady 車身防刮保護套 (多種圖樣可選)", 1080, 0),
    ("eReady 精品配件", "RR預載阻尼可調避震器(黃/黑)", 3960, 540),
    ("eReady 精品配件", "自動彈開座墊彈簧", 290, 60),
    ("eReady 精品配件", "eReady 後箱架", 1600, 240),
    ("eReady 精品配件", "eReady 邊柱加大座", 450, 0),
    ("eReady 精品配件", "Ridea 鋁合金握把/碳纖維握把/平衡端子", 1450, 300),
    ("eReady 精品配件", "DID 鏈條油", 600, 0),
    ("eReady 精品配件", "eReady RK輕量化齒盤組", 1800, 200),
    ("eReady 精品配件", "快拆型/滑軌型外送平台", 1250, 0),
    ("eReady 精品配件", "六段可調煞車拉桿", 1200, 200),
    ("eReady 精品配件", "ORO 胎內式/胎外式 胎壓偵測器 (一組2顆)", 1980, 715),
    ("Saluto 精品配件", "Saluto 黑化套件", 10000, 0),
    ("Saluto 精品配件", "Saluto 義式醇黑(炫銀)後保桿", 3300, 0),
    ("Saluto 精品配件", "Saluto 義式醇黑(炫銀)後靠背", 2500, 0),
    ("Saluto 精品配件", "SUZUKI 踩發桿", 2000, 100),
    ("Saluto 精品配件", "Saluto 原廠鍍鉻後置物架", 1800, 0),
    ("Saluto 精品配件", "Saluto 精品置物雙掛鉤", 980, 0),
    ("SUI 精品配件", "SUI AJ 輔助大燈", 3650, 1100),
    ("SUI 精品配件", "CRAFIT SUI 後扶手", 1650, 0),
    ("SUI 精品配件", "CRAFIT SUI 小鴨尾蓋", 750, 0),
    ("SUI 精品配件", "CRAFIT SUI 前方向燈蓋(JIMNY造型)", 1400, 0),
    ("SUI 精品配件", "AD-1 SUZUKI SUI復古方向燈框", 950, 0),
    ("SUI 精品配件", "Ghost SUI 書包架+專用內鐵", 3970, 500),
    ("SUI 精品配件", "Ghost SUI 復古刀鋒燈罩", 790, 0),
    ("SUI 精品配件", "SUZUKI 踩發桿", 2000, 100),
    ("SUI 精品配件", "SIXIS SUI 腳踏飛翼", 1580, 100),
    ("SUI 精品配件", "SUI 前置物籃", 2980, 320),
    ("SUI 精品配件", "SUI 精品置物雙掛鉤", 980, 0),
    ("SUI 精品配件", "SUI USB充電座", 800, 400),
    ("SUI 精品配件", "SUI 前面板側保桿", 2000, 0),
    ("SUI 精品配件", "SUI SIXIS 日規後貨架 (亮黑)", 2280, 0),
    ("SUI 精品配件", "KOSO SUI 前土除護蓋", 1000, 0),
    ("SUI 精品配件", "SUI 前土除保桿", 1500, 0),
    ("SUI 精品配件", "SUI 左右後保桿", 2800, 0),
    ("SUI 精品配件", "SUI 後座靠墊", 2500, 0),
    ("SUI 精品配件", "SUI 前風鏡", 3200, 0),
]
SIGNED_FILES = ("signed_contract", "privacy_consent", "tax_consent")


def planned_products():
    """名稱 →（售價、工資、類別清單）；同名多列合併類別，價格必須一致。"""
    plan = {}
    for category, name, price, labor in CATALOG:
        name = normalized_accessory_name(name)
        item = plan.setdefault(name, {"sale_price": price, "labor_fee": labor, "categories": []})
        if (item["sale_price"], item["labor_fee"]) != (price, labor):
            raise CommandError(f"「{name}」在不同類別的價格不一致，請先確認。")
        if category not in item["categories"]:
            item["categories"].append(category)
    return plan


def _fingerprints(order):
    from sales.services.document_signing import TERMS, current_fingerprint
    return {document: current_fingerprint(order, document) for document in TERMS}


def _line_snapshot(line):
    return {"id": line.pk, "order_id": line.order_id, "accessory_product_id": line.accessory_product_id, "name": line.name,
            "line_type": line.line_type, "quantity": line.quantity, "amount": str(line.amount),
            "labor_fee": str(line.labor_fee), "note": line.note}


def snapshot():
    lines = list(AccessoryLine.objects.filter(accessory_product__isnull=False).order_by("pk"))
    orders = SalesOrder.objects.filter(pk__in={line.order_id for line in lines}).order_by("pk")
    return {
        "task": "T-179 rebuild_accessory_catalog",
        "categories": [{"id": c.pk, "name": c.name, "sort_order": c.sort_order, "active": c.active}
                       for c in AccessoryCategory.objects.order_by("pk")],
        "products": [{"id": p.pk, "name": p.name, "category_id": p.category_id,
                      "categories": sorted(p.categories.values_list("pk", flat=True)),
                      "sale_price": str(p.sale_price), "labor_fee": str(p.labor_fee),
                      "cost": None if p.cost is None else str(p.cost), "active": p.active, "note": p.note}
                     for p in AccessoryProduct.objects.order_by("pk")],
        "lines": [_line_snapshot(line) for line in lines],
        "orders": [{"id": o.pk, "number": o.number, "fingerprints": _fingerprints(o),
                    "files": {field: getattr(o, field).name or "" for field in SIGNED_FILES}} for o in orders],
    }


def _read_backup():
    try:
        return json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        raise CommandError(f"讀不到備份 JSON（請用 stdin 傳入 --export 的檔案）：{exc}") from exc


def _log(user, model_object, flag, message):
    LogEntry.objects.create(
        user_id=user.pk, content_type=ContentType.objects.get_for_model(type(model_object)), object_id=str(model_object.pk),
        object_repr=str(model_object)[:200], action_flag=flag, change_message=message,
    )


class Command(BaseCommand):
    help = "依 bikecity 訂購表重建配件主檔（T-179）。預設 dry-run；--export 備份、--apply 套用、--restore 回復，備份由 stdin 傳入。"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--export", action="store_true", help="輸出 JSON 備份到 stdout")
        mode.add_argument("--apply", action="store_true", help="從 stdin 讀備份並套用")
        mode.add_argument("--restore", action="store_true", help="從 stdin 讀備份並回復")
        parser.add_argument("--actor", default="admin", help="寫進異動紀錄的帳號（預設 admin）")

    def handle(self, *args, **options):
        if options["export"]:
            self.stdout.write(json.dumps(snapshot(), ensure_ascii=False, indent=1))
            return
        if options["apply"] or options["restore"]:
            user = get_user_model().objects.filter(username=options["actor"]).first()
            if user is None:
                raise CommandError(f"找不到帳號 {options['actor']}，請用 --actor 指定。")
            backup = _read_backup()
            if options["apply"]:
                self.apply(backup, user)
            else:
                self.restore(backup, user)
            return
        self.dry_run()

    # ---- dry-run ----
    def dry_run(self):
        plan = planned_products()
        current = snapshot()
        used = {}
        for line in current["lines"]:
            used.setdefault(line["accessory_product_id"], []).append(line)
        self.stdout.write(f"來源：{SOURCE}\n")
        self.stdout.write(f"刪除配件主檔 {len(current['products'])} 筆（含停用 {sum(not p['active'] for p in current['products'])} 筆）：")
        for product in current["products"]:
            lines = used.get(product["id"], [])
            refs = (f"｜斷開 {len(lines)} 列（加購 {sum(l['line_type'] == 'purchase' for l in lines)}、"
                    f"贈送 {sum(l['line_type'] == 'gift' for l in lines)}）" if lines else "")
            self.stdout.write(f"  - #{product['id']} {product['name']}{'（停用）' if not product['active'] else ''}{refs}")
        orders = {line["order_id"] for line in current["lines"]}
        self.stdout.write(f"斷開主檔連結的明細 {len(current['lines'])} 列、{len(orders)} 張訂單；名稱、類型、數量、售價、工資、備註不變。")
        self.stdout.write(f"刪除類別 {len(current['categories'])} 個：" + "、".join(c["name"] for c in current["categories"]))
        self.stdout.write(f"建立類別 {len(CATEGORIES)} 個：" + "、".join(f"{name}（排序 {order}）" for name, order in CATEGORIES))
        self.stdout.write(f"建立配件 {len(plan)} 筆（表格 {len(CATALOG)} 列）：")
        for name, item in plan.items():
            self.stdout.write(f"  + {name}｜{'、'.join(item['categories'])}｜售價 {item['sale_price']:,}｜工資 {item['labor_fee']:,}｜參考成本 未維護")
        self.stdout.write("dry-run：沒有寫入任何資料。")

    # ---- apply ----
    def apply(self, backup, user):
        plan = planned_products()
        with transaction.atomic():
            list(AccessoryProduct.objects.select_for_update().order_by("pk"))
            current = snapshot()
            for key in ("products", "categories", "lines"):
                if current[key] != backup.get(key):
                    raise CommandError(f"備份和目前的{ {'products': '配件主檔', 'categories': '類別', 'lines': '訂單配件明細'}[key] }不一致，請重新 --export 再套用。")
            names = {p["id"]: p["name"] for p in backup["products"]}
            by_order = {}
            for line in backup["lines"]:
                by_order.setdefault(line["order_id"], []).append(line)
            AccessoryLine.objects.filter(pk__in=[line["id"] for line in backup["lines"]]).update(accessory_product=None)
            for order in SalesOrder.objects.filter(pk__in=by_order).order_by("pk"):
                OrderChange.objects.create(
                    order=order, actor_name=ACTOR_NAME,
                    reason="配件主檔重建（T-179）：本列改為歷史紀錄，名稱、類型、數量、售價、工資都不變",
                    changes={f"配件明細 #{line['id']}「{line['name']}」對應主檔": {
                        "before": f"{names[line['accessory_product_id']]}（#{line['accessory_product_id']}）", "after": "歷史紀錄（不連主檔）"}
                        for line in by_order[order.pk]},
                )
            for product in AccessoryProduct.objects.order_by("pk"):
                _log(user, product, DELETION, f"T-179 配件主檔重建：刪除舊配件（售價 {product.sale_price}；工資 {product.labor_fee}）")
            AccessoryProduct.objects.all().delete()
            for category in AccessoryCategory.objects.order_by("pk"):
                _log(user, category, DELETION, "T-179 配件主檔重建：刪除舊類別")
            AccessoryCategory.objects.all().delete()
            categories = {}
            for name, order in CATEGORIES:
                categories[name] = AccessoryCategory.objects.create(name=name, sort_order=order, active=True)
                _log(user, categories[name], ADDITION, f"T-179 配件主檔重建：新增類別（排序 {order}）")
            for name, item in plan.items():
                product = AccessoryProduct.objects.create(name=name, sale_price=Decimal(item["sale_price"]),
                                                          labor_fee=Decimal(item["labor_fee"]), cost=None, active=True, note=NOTE)
                product.categories.set([categories[label] for label in item["categories"]])
                _log(user, product, ADDITION, f"T-179 依 bikecity 訂購表新增：{'、'.join(item['categories'])}；售價 {item['sale_price']}；工資 {item['labor_fee']}")
            self._verify_orders(backup, linked=False)
            if AccessoryProduct.objects.count() != len(plan) or AccessoryCategory.objects.count() != len(CATEGORIES):
                raise CommandError("建立後的配件或類別筆數不對，整筆不做。")
            if AccessoryProduct.objects.filter(name__in=names.values()).exclude(name__in=plan).exists():
                raise CommandError("還有舊配件名稱留在主檔，整筆不做。")
        self.stdout.write(self.style.SUCCESS(
            f"已套用：斷開 {len(backup['lines'])} 列明細（{len(by_order)} 張訂單）、刪除 {len(backup['products'])} 筆舊配件與 "
            f"{len(backup['categories'])} 個舊類別，建立 {len(CATEGORIES)} 個類別、{len(plan)} 筆配件；明細快照與簽署指紋核對相同。"))

    def _verify_orders(self, backup, linked):
        """逐列核對明細快照（連結依 linked 決定：套用後應為空、回復後應為原主檔）與訂單簽署指紋、已簽檔名。"""
        for row in backup["lines"]:
            line = AccessoryLine.objects.filter(pk=row["id"]).first()
            if line is None:
                raise CommandError(f"明細 #{row['id']} 不見了，整筆不做。")
            expected = {**row, "accessory_product_id": row["accessory_product_id"] if linked else None}
            if _line_snapshot(line) != expected:
                raise CommandError(f"明細 #{row['id']}「{row['name']}」和備份不同，整筆不做。")
        for row in backup["orders"]:
            order = SalesOrder.objects.get(pk=row["id"])
            if _fingerprints(order) != row["fingerprints"]:
                raise CommandError(f"訂單 {row['number']} 的簽署內容指紋改變了，整筆不做。")
            if {field: getattr(order, field).name or "" for field in SIGNED_FILES} != row["files"]:
                raise CommandError(f"訂單 {row['number']} 的已簽檔案改變了，整筆不做。")

    # ---- restore ----
    def restore(self, backup, user):
        plan = planned_products()
        with transaction.atomic():
            list(AccessoryProduct.objects.select_for_update().order_by("pk"))
            ours = AccessoryProduct.objects.filter(name__in=plan, note=NOTE)
            others = AccessoryProduct.objects.exclude(pk__in=ours)
            if others.exists():
                raise CommandError("主檔裡有不是本指令建立的配件：" + "、".join(others.values_list("name", flat=True)[:20])
                                   + "。請先人工確認再回復。")
            used = AccessoryLine.objects.filter(accessory_product__in=ours)
            if used.exists():
                raise CommandError(f"新配件已被 {used.count()} 列訂單明細用到，不能自動回復，請先人工確認。")
            for product in ours.order_by("pk"):
                _log(user, product, DELETION, "T-179 回復：刪除重建時新增的配件")
            ours.delete()
            for category in AccessoryCategory.objects.order_by("pk"):
                _log(user, category, DELETION, "T-179 回復：刪除重建時新增的類別")
            AccessoryCategory.objects.all().delete()
            for row in backup["categories"]:
                category = AccessoryCategory.objects.create(id=row["id"], name=row["name"], sort_order=row["sort_order"], active=row["active"])
                _log(user, category, ADDITION, "T-179 回復：重建舊類別")
            for row in backup["products"]:
                product = AccessoryProduct.objects.create(
                    id=row["id"], name=row["name"], sale_price=Decimal(row["sale_price"]), labor_fee=Decimal(row["labor_fee"]),
                    cost=None if row["cost"] is None else Decimal(row["cost"]), active=row["active"], note=row["note"])
                product.categories.set(row["categories"])
                if row["category_id"] and product.category_id != row["category_id"]:
                    AccessoryProduct.objects.filter(pk=product.pk).update(category_id=row["category_id"])
                _log(user, product, ADDITION, "T-179 回復：重建舊配件")
            by_order = {}
            for row in backup["lines"]:
                AccessoryLine.objects.filter(pk=row["id"], accessory_product__isnull=True).update(accessory_product_id=row["accessory_product_id"])
                by_order.setdefault(row["order_id"], []).append(row)
            for order in SalesOrder.objects.filter(pk__in=by_order).order_by("pk"):
                OrderChange.objects.create(order=order, actor_name=ACTOR_NAME, reason="配件主檔重建（T-179）回復：明細改連回原配件",
                                           changes={f"配件明細 #{row['id']}「{row['name']}」對應主檔": {
                                               "before": "歷史紀錄（不連主檔）", "after": f"#{row['accessory_product_id']}"} for row in by_order[order.pk]})
            self._verify_orders(backup, linked=True)
            _reset_sequences()
        self.stdout.write(self.style.SUCCESS(
            f"已回復：重建 {len(backup['categories'])} 個類別、{len(backup['products'])} 筆配件，{len(backup['lines'])} 列明細改連回原配件。"))


def _reset_sequences():
    """用原 id 重建後，PostgreSQL 的序號要跟上（SQLite 不需要）。"""
    from django.core.management.color import no_style
    from django.db import connection
    if connection.vendor != "postgresql":
        return
    statements = connection.ops.sequence_reset_sql(no_style(), [AccessoryCategory, AccessoryProduct])
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
