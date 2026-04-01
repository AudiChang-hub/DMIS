from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DmsProductTemplate(models.Model):
    _name = 'dms.product.template'
    _description = '產品模板'
    _order = 'brand_id, family_name, model_name, id'

    brand_id = fields.Many2one(
        'dms.brand', string='品牌', required=True, ondelete='restrict')
    family_name = fields.Char(string='機種', required=True)
    type_name = fields.Char(string='型式')
    model_name = fields.Char(string='型號')
    energy_type = fields.Selection(
        [('oil', '油車'), ('electric', '電車')],
        string='能源型式',
        required=True,
    )
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    @api.constrains('brand_id', 'family_name', 'energy_type')
    def _check_required_fields(self):
        for rec in self:
            missing = []
            if not rec.brand_id:
                missing.append('品牌')
            if not rec.family_name or not rec.family_name.strip():
                missing.append('機種')
            if not rec.energy_type:
                missing.append('能源型式')
            if missing:
                raise ValidationError(
                    '【必填欄位未填寫】' + '、'.join(missing) + '\n\n'
                    '請回到產品模板基本資料，補填以上欄位後再儲存。'
                )
    sku_ids = fields.One2many(
        'dms.product',
        'template_id',
        string='產品項',
        context={'active_test': False},
    )
    product_color_ids = fields.One2many(
        'dms.product.color',
        'template_id',
        string='產品顏色',
        context={'active_test': False},
    )
    sku_count = fields.Integer(
        string='產品項數量',
        compute='_compute_sku_count',
        store=False,
    )

    @api.depends('sku_ids')
    def _compute_sku_count(self):
        for record in self:
            record.sku_count = self.env['dms.product'].search_count([
                ('template_id', '=', record.id),
                ('active', '=', True),
            ])

    def name_get(self):
        result = []
        for record in self:
            parts = [
                record.brand_id.name or '',
                record.family_name or '',
                record.type_name or '',
                record.model_name or '',
            ]
            label = " / ".join(part for part in parts if part)
            result.append((record.id, label or '產品模板'))
        return result

    @api.model
    def _find_matching_template(self, brand_id, family_name, type_name, model_name, energy_type):
        templates = self.search([
            ('brand_id', '=', brand_id),
            ('family_name', '=', family_name or False),
            ('energy_type', '=', energy_type),
        ])
        normalized_type = (type_name or '').strip()
        normalized_model = (model_name or '').strip()
        for template in templates:
            if (
                (template.type_name or '').strip() == normalized_type
                and (template.model_name or '').strip() == normalized_model
            ):
                return template
        return self.browse()

    def copy(self, default=None):
        default = dict(default or {})
        copied_template = super().copy(default)
        for sku in self.with_context(active_test=False).sku_ids:
            sku.copy({'template_id': copied_template.id})
        return copied_template

    @api.model
    def _find_or_create_from_legacy(self, product):
        template = self._find_matching_template(
            product.brand_id.id,
            product.name,
            False,
            product.model,
            product.energy_type,
        )
        if template:
            return template
        return self.create({
            'brand_id': product.brand_id.id,
            'family_name': product.name,
            'type_name': False,
            'model_name': product.model,
            'energy_type': product.energy_type,
            'active': product.active,
        })
