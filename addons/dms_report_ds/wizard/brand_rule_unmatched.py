from odoo import api, fields, models


class BrandRuleUnmatchedWizard(models.TransientModel):
    _name = 'dms.dealer.brand.rule.unmatched.wizard'
    _description = '規則未命中診斷'

    kind = fields.Selection(
        [('brand', 'brand_type'), ('motor', 'motor_type')],
        string='類型', default='brand', readonly=True)
    summary = fields.Text(string='摘要', readonly=True)
    line_ids = fields.One2many(
        'dms.dealer.brand.rule.unmatched.line',
        'wizard_id', string='未命中項目')

    @api.model
    def action_open(self):
        """建立 wizard 並開啟視窗，展示 brand_type 未命中清單。"""
        cr = self.env.cr
        cr.execute("""
            WITH known AS (
                SELECT DISTINCT result FROM dms_dealer_brand_rule
                WHERE active = TRUE
            ),
            stats AS (
                SELECT
                    SUM(CASE WHEN brand_type IN ('馭盛網推','網路平台','中古車')
                              OR brand_type IN (SELECT result FROM known)
                             THEN 1 ELSE 0 END) AS matched,
                    SUM(CASE WHEN brand_type NOT IN ('馭盛網推','網路平台','中古車')
                              AND brand_type NOT IN (SELECT result FROM known)
                             THEN 1 ELSE 0 END) AS unmatched,
                    COUNT(*) AS total
                FROM ds_sales_report
            )
            SELECT matched, unmatched, total FROM stats
        """)
        matched, unmatched, total = cr.fetchone() or (0, 0, 0)
        rate = (matched / total * 100.0) if total else 0.0

        cr.execute("""
            WITH known AS (
                SELECT DISTINCT result FROM dms_dealer_brand_rule
                WHERE active = TRUE
            )
            SELECT brand_type, COUNT(*) AS cnt
            FROM ds_sales_report
            WHERE brand_type NOT IN (SELECT result FROM known)
              AND brand_type NOT IN ('馭盛網推', '網路平台', '中古車')
            GROUP BY 1
            ORDER BY 2 DESC, 1
        """)
        rows = cr.fetchall()

        summary = (
            f'類型：brand_type（車行品牌分類）\n'
            f'命中：{matched} / 未命中：{unmatched} / 總計：{total}\n'
            f'命中率：{rate:.1f}%'
        )
        wizard = self.create({
            'kind': 'brand',
            'summary': summary,
            'line_ids': [
                (0, 0, {'dname': name, 'order_count': cnt})
                for name, cnt in rows
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'brand_type 未命中診斷',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    @api.model
    def action_open_motor(self):
        """建立 wizard 並開啟視窗，展示 motor_type 未命中清單。

        motor_type 未命中 = ELSE 落到 '其他'。明細以商品名 pname 分組。
        """
        cr = self.env.cr
        cr.execute("""
            SELECT
                SUM(CASE WHEN motor_type IS NOT NULL AND motor_type <> '其他'
                         THEN 1 ELSE 0 END) AS matched,
                SUM(CASE WHEN motor_type = '其他' OR motor_type IS NULL
                         THEN 1 ELSE 0 END) AS unmatched,
                COUNT(*) AS total
            FROM ds_sales_report
        """)
        matched, unmatched, total = cr.fetchone() or (0, 0, 0)
        rate = (matched / total * 100.0) if total else 0.0

        cr.execute("""
            SELECT model, COUNT(*) AS cnt
            FROM ds_sales_report
            WHERE motor_type = '其他' OR motor_type IS NULL
            GROUP BY 1
            ORDER BY 2 DESC, 1
        """)
        rows = cr.fetchall()

        summary = (
            f'類型：motor_type（車種類型分類，依商品名 model 比對）\n'
            f'命中：{matched} / 未命中：{unmatched} / 總計：{total}\n'
            f'命中率：{rate:.1f}%'
        )
        wizard = self.create({
            'kind': 'motor',
            'summary': summary,
            'line_ids': [
                (0, 0, {'dname': name or '(空)', 'order_count': cnt})
                for name, cnt in rows
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'motor_type 未命中診斷',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }


class BrandRuleUnmatchedLine(models.TransientModel):
    _name = 'dms.dealer.brand.rule.unmatched.line'
    _description = '規則未命中明細'
    _order = 'order_count desc, dname'

    wizard_id = fields.Many2one(
        'dms.dealer.brand.rule.unmatched.wizard',
        ondelete='cascade')
    dname = fields.Char(string='名稱', readonly=True)
    order_count = fields.Integer(string='訂單筆數', readonly=True)
