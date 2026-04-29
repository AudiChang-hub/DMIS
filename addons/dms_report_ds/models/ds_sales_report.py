from odoo import fields, models, tools


# 內建預設規則：當 dms.motor.type.rule 表尚未建立或無資料時使用，
# 維持 view 在初次安裝 / fresh DB 情境下仍可正確產出 motor_type。
_DEFAULT_MOTOR_TYPE_RULES = [
    ('eReady', '白牌電車'),
    ('Gogoro|Pulse|S2.?ABS', '白牌電車'),
    ('JEGO|VIVA|EZ1|EZZY|Ur2', '綠牌電車'),
    ('BOBE|SHINE|TSV57', '微型電車'),
    ('SUI|Saluto|NEX|SWISH|UQ|UC|UG|UT|Address', '速克達'),
    (r'DR-?Z|GSX|GIXXER|V-?STROM|Burgman|T-?MAX|DS\d', '擋車'),
]


class DsSalesReport(models.Model):
    """DataStudio 銷售分析 SQL View — 復刻全部 17 個計算欄位"""

    _name = 'ds.sales.report'
    _description = 'DataStudio 銷售分析'
    _auto = False
    _rec_name = 'order_name'
    _order = 'license_date desc'

    # ── 識別 ──────────────────────────────────────────────
    order_name = fields.Char(string='訂單編號', readonly=True)
    state = fields.Selection(
        [('draft', '草稿'), ('confirmed', '已成立'), ('cancel', '已取消')],
        string='狀態', readonly=True)
    order_date = fields.Date(string='訂單日期', readonly=True)

    # ── 領牌 ──────────────────────────────────────────────
    license_date = fields.Date(string='領牌日期', readonly=True)
    license_ym = fields.Char(string='領牌年月', readonly=True)
    sort_license_date = fields.Date(string='排序用領牌日期', readonly=True)

    # ── 車輛 ──────────────────────────────────────────────
    model = fields.Char(string='車種型號', readonly=True)
    car_color = fields.Char(string='車色', readonly=True)
    model_color = fields.Char(string='車型_顏色', readonly=True)
    dealer = fields.Char(string='車行名稱', readonly=True)
    dealer_not_null = fields.Char(string='車行（去空白大寫）', readonly=True)
    vin_or_en = fields.Char(string='引擎號碼', readonly=True)
    license_plate = fields.Char(string='車牌號碼', readonly=True)

    # ── 分類（fx 計算欄位）─────────────────────────────────
    energy_type = fields.Selection(
        [('電車', '電車'), ('油車', '油車')],
        string='能源型式', readonly=True)
    motor_type = fields.Selection(
        [('白牌電車', '白牌電車'), ('綠牌電車', '綠牌電車'),
         ('微型電車', '微型電車'), ('速克達', '速克達'),
         ('擋車', '擋車'), ('其他', '其他')],
        string='車種類型', readonly=True)
    sales_source = fields.Selection(
        [('馭盛', '馭盛'), ('網路平台', '網路平台'),
         ('店內員工', '店內員工'), ('車行', '車行')],
        string='銷售來源', readonly=True)
    sales_type = fields.Selection(
        [('本店', '本店'), ('網路平台', '網路平台'), ('車行', '車行')],
        string='銷售類型', readonly=True)
    brand_type = fields.Char(string='品牌分類', readonly=True)

    # ── 客戶（fx 計算欄位）─────────────────────────────────
    owner_name = fields.Char(string='車主姓名', readonly=True)
    sex = fields.Selection(
        [('男性', '男性'), ('女性', '女性'),
         ('未填寫或格式錯誤', '未填寫或格式錯誤')],
        string='性別', readonly=True)
    age = fields.Integer(string='年齡', readonly=True)
    age_group = fields.Selection(
        [('20歲以下', '20歲以下'), ('20-29歲', '20-29歲'),
         ('30-39歲', '30-39歲'), ('40-49歲', '40-49歲'),
         ('50-59歲', '50-59歲'), ('60歲以上', '60歲以上'),
         ('未填寫', '未填寫')],
        string='年齡組', readonly=True)

    # ── 地區（fx 計算欄位）─────────────────────────────────
    region = fields.Char(string='區域', readonly=True)
    region_district = fields.Char(string='縣市區域', readonly=True)

    # ── 金額 ──────────────────────────────────────────────
    receipt_price = fields.Float(string='收款價', readonly=True, digits=(12, 0))
    cost = fields.Float(string='成本', readonly=True, digits=(12, 0))
    net_profit = fields.Float(string='單筆淨利', readonly=True, digits=(12, 0))
    dealer_comm_out = fields.Float(string='車行傭金支出', readonly=True, digits=(12, 0))
    friendly_bonus_out = fields.Float(string='友善車行獎金', readonly=True, digits=(12, 0))
    first_sale_bonus = fields.Float(string='首賣獎金', readonly=True, digits=(12, 0))
    basic_bonus = fields.Float(string='獎勵金（BasicBonus）', readonly=True, digits=(12, 0))
    dealer_receipt = fields.Float(string='車行收款', readonly=True, digits=(12, 0))

    # ── 贈品 / 補助 ──────────────────────────────────────
    company_gift = fields.Char(string='公司贈品', readonly=True)
    platform_gift = fields.Char(string='平台贈品', readonly=True)
    gift_card = fields.Float(string='禮卷/匯款', readonly=True, digits=(12, 0))
    subsidy_plan = fields.Char(string='補助方案', readonly=True)
    settle_date = fields.Date(string='結清日期（訖）', readonly=True)
    apply_date = fields.Date(string='補助申請日', readonly=True)

    # ── 佣金 ──────────────────────────────────────────────
    volume_bonus = fields.Float(string='台數獎金', readonly=True, digits=(12, 0))
    total_commission = fields.Float(string='合計傭金', readonly=True, digits=(12, 0))

    # ── 備註 ──────────────────────────────────────────────
    remark = fields.Char(string='備註', readonly=True)

    def _get_motor_type_case_sql(self):
        """從 dms.motor.type.rule 讀取規則並組合 CASE 子句。

        - 規則表不存在或無啟用規則時，使用內建預設清單。
        - 結果僅來自設定中的 Selection 結果欄位（已限制可選值），
          pattern / result 透過 SQL 字串轉義內嵌，避免注入。
        """
        cr = self.env.cr
        rules = []
        cr.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'dms_motor_type_rule'
        """)
        if cr.fetchone():
            cr.execute("""
                SELECT pattern, result FROM dms_motor_type_rule
                WHERE active = TRUE
                ORDER BY sequence, id
            """)
            rules = cr.fetchall()
        if not rules:
            rules = list(_DEFAULT_MOTOR_TYPE_RULES)

        when_clauses = []
        for pattern, result in rules:
            if not pattern or not result:
                continue
            esc_pattern = pattern.replace("'", "''")
            esc_result = result.replace("'", "''")
            when_clauses.append(
                "WHEN s.pname ~* '%s' THEN '%s'" % (esc_pattern, esc_result)
            )
        if not when_clauses:
            return "'其他'"
        return "CASE\n                    " + \
               "\n                    ".join(when_clauses) + \
               "\n                    ELSE '其他'\n                END"

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        motor_type_case = self._get_motor_type_case_sql()
        self.env.cr.execute(("""
            CREATE OR REPLACE VIEW %(table)s AS (
            WITH src AS (
                SELECT
                    so.id,
                    so.name                     AS order_name,
                    so.state,
                    so.order_date,
                    so.registration_date,
                    so.customer_name,
                    so.id_number,
                    so.birthday_ad,
                    so.address_registered,
                    so.engine_number,
                    so.plate_number,
                    so.received_amount,
                    so.cost,
                    so.net_profit,
                    so.dealer_amount,
                    so.out_dealer_commission,
                    so.out_friendly_dealer_bonus,
                    so.out_first_sale_bonus,
                    so.extra_company_gift,
                    so.extra_platform_gift,
                    so.gift_voucher,
                    so.subsidy_plan,
                    so.settle_date,
                    so.subsidy_moenv_date,
                    so.extra_note,
                    COALESCE(so.display_product_name, '')  AS pname,
                    COALESCE(so.display_dealer_name, '')   AS dname,
                    COALESCE(so.display_color_name, '')    AS cname,
                    p.energy_type                          AS p_energy,
                    COALESCE(cr.volume_bonus, 0)           AS cr_volume_bonus,
                    COALESCE(cr.total_commission, 0)       AS cr_total_commission
                FROM dms_sale_order so
                LEFT JOIN dms_product p
                    ON so.product_id = p.id
                LEFT JOIN dms_commission_record cr
                    ON cr.sale_order_id = so.id
                   AND cr.state = 'active'
                WHERE so.active = True
            )
            SELECT
                s.id,
                s.order_name,
                s.state,
                s.order_date,

                -- ── 領牌 ──
                s.registration_date              AS license_date,
                TO_CHAR(s.registration_date, 'YYYY-MM')
                                                 AS license_ym,
                COALESCE(s.registration_date, '9999-12-31'::date)
                                                 AS sort_license_date,

                -- ── 車輛 ──
                s.pname                          AS model,
                s.cname                          AS car_color,
                s.pname || '_' || s.cname        AS model_color,
                CASE WHEN s.dname = '' THEN '馭盛'
                     ELSE s.dname
                END                              AS dealer,
                CASE WHEN s.dname = '' THEN '馭盛'
                     ELSE UPPER(TRIM(regexp_replace(s.dname, '\s+', '', 'g')))
                END                              AS dealer_not_null,
                s.engine_number                  AS vin_or_en,
                s.plate_number                   AS license_plate,

                -- ── 能源型式（fx #6）──
                CASE
                    WHEN s.p_energy = 'electric' THEN '電車'
                    WHEN s.p_energy = 'oil' THEN '油車'
                    WHEN s.pname ~* '(eReady|^EV|Gogoro|Pulse|S2.?ABS|BOBE|VIVAMIX|VIVABASIC|TSV57|SHINE|JEGO|EZ1|EZZY|VIVAXLSF|Ur2)'
                        THEN '電車'
                    ELSE '油車'
                END                              AS energy_type,

                -- ── 車種分類（fx #8 MotorType，由 dms.motor.type.rule 動態產生）──
                %(motor_type_case)s              AS motor_type,

                -- ── 客戶 ──
                s.customer_name                  AS owner_name,

                -- ── 性別（fx #16）──
                CASE
                    WHEN LENGTH(COALESCE(s.id_number, '')) >= 2
                     AND SUBSTRING(s.id_number, 2, 1) IN ('1','8')
                        THEN '男性'
                    WHEN LENGTH(COALESCE(s.id_number, '')) >= 2
                     AND SUBSTRING(s.id_number, 2, 1) IN ('2','9')
                        THEN '女性'
                    ELSE '未填寫或格式錯誤'
                END                              AS sex,

                -- ── 年齡（fx #1）──
                CASE WHEN s.birthday_ad IS NOT NULL
                    THEN EXTRACT(YEAR FROM CURRENT_DATE)::int
                       - EXTRACT(YEAR FROM s.birthday_ad)::int
                    ELSE NULL
                END                              AS age,

                -- ── 年齡組（fx #2）──
                CASE
                    WHEN s.birthday_ad IS NULL THEN '未填寫'
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE)::int
                       - EXTRACT(YEAR FROM s.birthday_ad)::int < 20
                        THEN '20歲以下'
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE)::int
                       - EXTRACT(YEAR FROM s.birthday_ad)::int BETWEEN 20 AND 29
                        THEN '20-29歲'
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE)::int
                       - EXTRACT(YEAR FROM s.birthday_ad)::int BETWEEN 30 AND 39
                        THEN '30-39歲'
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE)::int
                       - EXTRACT(YEAR FROM s.birthday_ad)::int BETWEEN 40 AND 49
                        THEN '40-49歲'
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE)::int
                       - EXTRACT(YEAR FROM s.birthday_ad)::int BETWEEN 50 AND 59
                        THEN '50-59歲'
                    ELSE '60歲以上'
                END                              AS age_group,

                -- ── 地區（fx #11 Region）──
                (regexp_match(
                    regexp_replace(
                        COALESCE(s.address_registered, ''),
                        '^\d{3}', ''),
                    '(.{2,5}(?:區|鄉|鎮|市))')
                )[1]                             AS region,

                -- ── 縣市區域（fx #13 Region_District）──
                (regexp_match(
                    COALESCE(s.address_registered, ''),
                    '((?:台北市|新北市|桃園市|台中市|台南市|高雄市|基隆市|新竹市|嘉義市|新竹縣|苗栗縣|宜蘭縣|彰化縣|南投縣|雲林縣|嘉義縣|屏東縣|花蓮縣|台東縣|澎湖縣|金門縣|連江縣).{1,6}(?:區|鄉|鎮|市))')
                )[1]                             AS region_district,

                -- ── 銷售來源（fx #14 Sales Source）──
                CASE
                    WHEN s.dname = '' OR s.dname = '中古車'
                        THEN '馭盛'
                    WHEN s.dname ~* '(yahoo|百利市|momo|PC|Friday|燦坤|小樹購|蝦皮)'
                        THEN '網路平台'
                    WHEN s.dname ~ '文傑'
                        THEN '店內員工'
                    ELSE '車行'
                END                              AS sales_source,

                -- ── 銷售類型（fx #15 SalesType）──
                CASE
                    WHEN s.dname = '' OR s.dname ~ '文傑'
                        THEN '本店'
                    WHEN s.dname ~* '(pc|momo|yahoo|燦坤|小樹購|百利市|friday|蝦皮)'
                        THEN '網路平台'
                    ELSE '車行'
                END                              AS sales_type,

                -- ── 品牌分類（fx #4 BrandType）──
                CASE
                    WHEN s.dname = '' THEN '馭盛網推'
                    WHEN s.dname ~* '(pc|momo|yahoo|燦坤|小樹購|百利市|friday|蝦皮)'
                        THEN '網路平台'
                    WHEN s.dname ~ '(鑫輝|特色|捷盛|祥銘|達能|立野|名豐|弘安)'
                        THEN '光陽'
                    WHEN s.dname ~ '(永湛|宏堂|見元|萬全|百福|昌億|風火輪|皇韋|成峰|百呈|明達|東永|嘉順)'
                        THEN '三陽'
                    WHEN s.dname ~ '(馳機|天佑|旭昇|宏偉|尚勁|德新|凱弘|鋐亞|群陽|德旺|駿翔|輪友|極昇|奕鈞|良澄|岩谷|昌勝|松祥|金利富|泳辰|源泰|旗成|嘉仁|金泰發|日信|名傑|鈞鴻)'
                        THEN '山葉'
                    WHEN s.dname ~ '(明毅|鑨來|阿松|佳峰|信益|鼎勝|上慶|合聰|宏昌|湖州|鉉豐)'
                        THEN '一般車行'
                    WHEN s.dname ~ '(明輝|新隆|旭昶|欣益|富順|運豐)'
                        THEN '台鈴'
                    WHEN s.dname ~ '(士辰|北野電能|北野)'
                        THEN '睿能'
                    WHEN s.dname ~ '中古車'
                        THEN '中古車'
                    WHEN s.dname ~ '彗星'
                        THEN '一般車行'
                    ELSE s.dname
                END                              AS brand_type,

                -- ── 金額 ──
                COALESCE(s.received_amount, 0)           AS receipt_price,
                COALESCE(s.cost, 0)                      AS cost,
                COALESCE(s.net_profit, 0)                AS net_profit,
                COALESCE(s.out_dealer_commission, 0)     AS dealer_comm_out,
                COALESCE(s.out_friendly_dealer_bonus, 0) AS friendly_bonus_out,
                COALESCE(s.out_first_sale_bonus, 0)      AS first_sale_bonus,
                COALESCE(s.out_friendly_dealer_bonus, 0)
                    + COALESCE(s.out_first_sale_bonus, 0)
                    + COALESCE(s.out_dealer_commission, 0)
                                                         AS basic_bonus,
                COALESCE(s.dealer_amount, 0)             AS dealer_receipt,

                -- ── 贈品 / 補助 ──
                s.extra_company_gift             AS company_gift,
                s.extra_platform_gift            AS platform_gift,
                COALESCE(s.gift_voucher, 0)      AS gift_card,
                s.subsidy_plan,
                s.settle_date,
                s.subsidy_moenv_date             AS apply_date,

                -- ── 佣金 ──
                s.cr_volume_bonus                AS volume_bonus,
                s.cr_total_commission            AS total_commission,

                -- ── 備註 ──
                s.extra_note                     AS remark

            FROM src s
            )
        """) % {'table': self._table, 'motor_type_case': motor_type_case})
