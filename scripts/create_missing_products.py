"""
建立 Excel 中缺少的車款至 dms.product（及對應 dms.product.template）
執行方式：python3 scripts/create_missing_products.py
"""
import xmlrpc.client

URL = 'http://localhost:8069'
DB  = 'dmis_dev'
USER = 'admin'
PASS = 'admin'

uid = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/common').authenticate(DB, USER, PASS, {})
m   = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/object')

def search_read(model, domain, fields, limit=0):
    kwargs = {'fields': fields}
    if limit:
        kwargs['limit'] = limit
    return m.execute_kw(DB, uid, PASS, model, 'search_read', [domain], kwargs)

def create(model, vals, context=None):
    kwargs = {}
    if context:
        kwargs['context'] = context
    return m.execute_kw(DB, uid, PASS, model, 'create', [vals], kwargs)

# ── 取得現有 model 值 ──────────────────────────────────────────────────────
existing = search_read('dms.product', [('active', '=', True)], ['model'])
existing_models = {p['model'] for p in existing if p['model']}
print(f'DB 中現有 active model 數量：{len(existing_models)}')

# ── 品牌 ID 對照（從現有資料取得）────────────────────────────────────────
brands = {b['name']: b['id'] for b in search_read('dms.brand', [], ['id', 'name'])}
print('品牌清單：', brands)

BRAND_SYM     = brands.get('台鈴 Suzuki', 2)    # 三陽/台鈴 (現有 UC/UQ/UT 也在此)
BRAND_SUZUKI  = brands.get('台鈴 Suzuki', 2)
BRAND_YAMAHA  = brands.get('山葉 Yamaha', 3)
BRAND_KYMCO   = brands.get('光陽 Kymco', 4)
BRAND_PGO     = brands.get('比雅久 PGO', 5)
BRAND_AEON    = brands.get('宏佳騰 Aeon', 6)
BRAND_GENERAL = brands.get('一般車行', 7)
BRAND_GOGORO  = brands.get('睿能 Gogoro', 10)

# ── 待建立車款清單 ─────────────────────────────────────────────────────────
# 格式： (model_code, family_name, brand_id, energy_type)
TO_CREATE = [
    # 台鈴/SYM 油車（對齊現有 UC125DA/UQ125DA 的 brand=台鈴 Suzuki）
    ('UC125',     'Saluto 125',         BRAND_SYM,     'oil'),
    ('UG125',     'SWISH 125',          BRAND_SYM,     'oil'),
    ('UQ125',     'SUI 125',            BRAND_SYM,     'oil'),
    ('UT125XDA',  'New NEX 125',        BRAND_SYM,     'oil'),
    # 台鈴 Suzuki 油車
    ('GSX-R150',  'GSX-R150',           BRAND_SUZUKI,  'oil'),
    ('GSX150',    'GIXXER 150',         BRAND_SUZUKI,  'oil'),
    ('GSX250',    'GIXXER 250',         BRAND_SUZUKI,  'oil'),
    ('GSX250F',   'GIXXER SF 250',      BRAND_SUZUKI,  'oil'),
    ('DS250',     'V-STROM 250SX',      BRAND_SUZUKI,  'oil'),
    ('DS250M4',   'V-STROM 250 M4',     BRAND_SUZUKI,  'oil'),
    ('DRZ-4SM',   'DR-Z4SM',            BRAND_SUZUKI,  'oil'),
    # 宏佳騰 Aeon 電車
    ('EV060L',    'e-moving EV060L',    BRAND_AEON,    'electric'),
    ('EV062',     'e-moving EV062',     BRAND_AEON,    'electric'),
    ('EV062FL',   'e-moving EV062FL',   BRAND_AEON,    'electric'),
    ('EV070V',    'e-moving EV070V',    BRAND_AEON,    'electric'),
    ('EV076',     'e-moving EV076',     BRAND_AEON,    'electric'),
    ('EV076S',    'e-moving EV076S',    BRAND_AEON,    'electric'),
    ('EV076SZV',  'e-moving EV076SZV',  BRAND_AEON,    'electric'),
    ('EZ1',       'EZ1',                BRAND_AEON,    'electric'),
    ('EZZY',      'EZZY',               BRAND_AEON,    'electric'),
    # 睿能 Gogoro 電車
    ('Gogoro2D',       'Gogoro 2 Delight',  BRAND_GOGORO, 'electric'),
    ('Gogoro2Premium', 'Gogoro 2 Premium',   BRAND_GOGORO, 'electric'),
    ('GogoroVIVAMIX',  'VIVA MIX',           BRAND_GOGORO, 'electric'),
    ('VIVABASIC',      'VIVA BASIC',          BRAND_GOGORO, 'electric'),
    ('VIVAMIX',        'VIVA MIX',            BRAND_GOGORO, 'electric'),
    ('VIVAXLSF',       'VIVA XL SF',          BRAND_GOGORO, 'electric'),
    ('Pulse',          'Gogoro Pulse',         BRAND_GOGORO, 'electric'),
    # 比雅久 PGO
    ('BOBE',  'BOBE',  BRAND_PGO,     'electric'),
    ('SHINE', 'SHINE', BRAND_PGO,     'oil'),
    ('Ur2',   'UR2',   BRAND_PGO,     'electric'),
    # 山葉 Yamaha
    ('TSV57', 'T-MAX 560', BRAND_YAMAHA, 'oil'),
    # 光陽 Kymco
    ('S2ABS', 'S2 ABS', BRAND_KYMCO, 'oil'),
    # 不確定品牌 → 一般車行
    ('JEGO',    'JEGO',    BRAND_GENERAL, 'oil'),
    ('02',      '02',      BRAND_GENERAL, 'oil'),
    ('7000021', '7000021', BRAND_GENERAL, 'oil'),
]

print(f'\n待建立清單共 {len(TO_CREATE)} 筆，開始處理...\n')

created = []
skipped = []

for model_code, family_name, brand_id, energy_type in TO_CREATE:
    if model_code in existing_models:
        skipped.append(model_code)
        print(f'  ⚪ 已存在，略過：{model_code}')
        continue

    # 建立 product（template 由 _sync_compat_fields 自動建立並連結）
    # context skip_product_year_uniqueness=True 讓 constrains 略過年份必填驗證
    prod_vals = {
        'brand_id':    brand_id,
        'name':        family_name,
        'model':       model_code,
        'energy_type': energy_type,
    }
    prod_id = create('dms.product', prod_vals,
                     context={'skip_product_year_uniqueness': True})

    created.append(model_code)
    print(f'  ✅ 建立完成：{model_code}  (product={prod_id})')

print(f'\n==== 結果 ====')
print(f'新建立：{len(created)} 筆  {created}')
print(f'已存在略過：{len(skipped)} 筆  {skipped}')
