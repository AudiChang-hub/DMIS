import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.osv import expression


LEGACY_GENERATED_CODE_PATTERN = re.compile(r'^SKU-\d{5}$')
COLOR_SPLIT_PATTERN = re.compile(r'[、/,，\s]+')


class DmsProductCompat(models.Model):
    _inherit = 'dms.product'

    template_id = fields.Many2one(
        'dms.product.template', string='產品模板', ondelete='cascade')
    internal_code = fields.Char(string='內部唯一代碼', index=True, copy=False)
    production_year = fields.Char(string='出廠年份')
    color_ids = fields.One2many(
        'dms.product.color',
        'product_id',
        string='產品顏色',
        context={'active_test': False},
    )

    # ── 定價欄位 ──────────────────────────────────────────────────────────
    cash_price = fields.Float(
        string='現金售價', digits=(12, 0), default=0.0,
        help='原廠公告現金售價，直接填入生效')
    list_price = fields.Float(
        string='牌價（MSRP）', digits=(12, 0), default=0.0)
    promo_price = fields.Float(
        string='活動特殊價', digits=(12, 0), default=0.0,
        help='原廠活動補助價；大於 0 時優先使用此價，活動結束後清零即可')
    promo_note = fields.Char(
        string='活動說明',
        help='如「2026 Q2 原廠補助」')
    effective_price = fields.Float(
        string='有效售價', digits=(12, 0),
        compute='_compute_effective_price', store=True,
        help='promo_price > 0 時回傳 promo_price，否則回傳 cash_price')
    installment_line_ids = fields.One2many(
        'dms.product.installment.line', 'product_id',
        string='分期方案明細')
    price_log_ids = fields.One2many(
        'dms.product.price.log', 'product_id',
        string='價格異動日誌')
    installment_log_ids = fields.One2many(
        'dms.product.installment.log', 'product_id',
        string='分期方案異動日誌')
    price_change_note = fields.Char(
        string='異動說明',
        store=False,
        inverse='_inverse_price_change_note',
        help='本次價格異動的說明，儲存後自動記入異動日誌並清空')

    def _inverse_price_change_note(self):
        """不需儲存；Odoo 透過此 inverse 確保欄位值傳入 write() 的 vals。"""
        pass

    _sql_constraints = [
        ('unique_internal_code', 'unique(internal_code)', '內部唯一代碼不可重複。'),
    ]

    @api.depends('cash_price', 'promo_price')
    def _compute_effective_price(self):
        for rec in self:
            rec.effective_price = rec.promo_price if rec.promo_price > 0 else rec.cash_price

    @api.constrains('template_id', 'production_year')
    def _check_production_year_required(self):
        """年份必填（中文錯誤提示，取代內建英文 required 訊息）"""
        if self.env.context.get('skip_product_year_uniqueness'):
            return
        for record in self:
            if not record.template_id:
                continue
            year_value = record._normalize_year_value(record.production_year or record.year)
            if not year_value:
                raise ValidationError(
                    '【必填欄位未填寫】出廠年份\n\n'
                    '已選擇產品模板，但「出廠年份」尚未填寫。\n'
                    '請在產品項清單的「出廠年份」欄位中輸入年份，例如：2025。'
                )

    @api.constrains('template_id', 'production_year')
    def _check_unique_template_year(self):
        if self.env.context.get('skip_product_year_uniqueness'):
            return
        for record in self:
            year_value = record._normalize_year_value(record.production_year or record.year)
            if not record.template_id or not year_value:
                continue
            duplicate = self.with_context(active_test=False).search([
                ('id', '!=', record.id),
                ('template_id', '=', record.template_id.id),
                ('production_year', '=', year_value),
            ], limit=1)
            if duplicate:
                raise ValidationError('同一產品模板與出廠年份僅能建立一筆產品項；若要新增顏色，請改到顏色清單維護。')

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.brand_id = self.template_id.brand_id
            self.name = self.template_id.family_name
            self.model = self.template_id.model_name or False
            self.energy_type = self.template_id.energy_type
        else:
            self.brand_id = False
            self.name = False
            self.model = False
            self.energy_type = False

    def _normalize_year_value(self, value):
        if value in (False, None, ''):
            return False
        normalized = str(value).strip().replace(',', '')
        return normalized or False

    def _normalize_color_name(self, value):
        if value in (False, None, ''):
            return False
        normalized = str(value).strip()
        return normalized or False

    def _split_color_names(self, value):
        normalized = self._normalize_color_name(value)
        if not normalized:
            return []
        return [token.strip() for token in COLOR_SPLIT_PATTERN.split(normalized) if token.strip()]

    def _sorted_color_records(self):
        self.ensure_one()
        return self.with_context(active_test=False).color_ids.sorted(
            key=lambda color: (color.sequence, color.id)
        )

    def _build_color_summary(self):
        self.ensure_one()
        colors = self._sorted_color_records()
        display_colors = colors.filtered('active') or colors
        names = []
        for color in display_colors:
            if color.name and color.name not in names:
                names.append(color.name)
        return '、'.join(names) or False

    def _ensure_color_record(self, name, color_code=False, image=False, active=True):
        self.ensure_one()
        normalized_name = self._normalize_color_name(name)
        if not normalized_name or not self.id:
            return self.env['dms.product.color'].browse()
        color_model = self.env['dms.product.color'].with_context(active_test=False)
        existing = color_model.search([
            ('product_id', '=', self.id),
            ('name', '=', normalized_name),
        ], limit=1)
        if existing:
            update_vals = {}
            if color_code and hasattr(existing, 'color_code') and not existing.color_code:
                update_vals['color_code'] = color_code
            if image and hasattr(existing, 'image_1920') and not existing.image_1920:
                update_vals['image_1920'] = image
            if active and not existing.active:
                update_vals['active'] = True
            if update_vals:
                existing.write(update_vals)
            return existing
        create_vals = {
            'product_id': self.id,
            'name': normalized_name,
            'active': active,
        }
        if hasattr(color_model, 'color_code') and color_code:
            create_vals['color_code'] = color_code
        if hasattr(color_model, 'image_1920') and image:
            create_vals['image_1920'] = image
        return color_model.create(create_vals)

    def _ensure_color_records_from_legacy(self):
        for record in self:
            for color_name in record._split_color_names(record.color):
                record._ensure_color_record(
                    color_name,
                    color_code=record.color_code,
                    image=getattr(record, 'image_1920', False),
                    active=record.active,
                )

    def _sync_legacy_color_summary(self):
        if self.env.context.get('skip_product_color_sync'):
            return
        for record in self:
            summary = record._build_color_summary()
            if summary != (record.color or False):
                super(
                    DmsProductCompat,
                    record.with_context(skip_product_color_sync=True),
                ).write({'color': summary, 'color_code': False})

    def _sync_color_templates(self):
        for record in self:
            mismatched_colors = record.with_context(active_test=False).color_ids.filtered(
                lambda color: color.template_id != record.template_id
            )
            if mismatched_colors:
                mismatched_colors.write({'template_id': record.template_id.id or False})

    def name_get(self):
        result = []
        for record in self:
            template_label = (
                record.template_id.family_name
                if record.template_id and record.template_id.family_name
                else (record.name or record.model or '產品項')
            )
            parts = [
                record.internal_code or False,
                template_label,
            ]
            label = " / ".join(part for part in parts if part)
            result.append((record.id, label))
        return result

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        args = list(args or [])
        if name:
            args = expression.AND([
                args,
                expression.OR([
                    [('internal_code', operator, name)],
                    [('production_year', operator, name)],
                    [('year', operator, name)],
                    [('name', operator, name)],
                    [('model', operator, name)],
                    [('template_id.family_name', operator, name)],
                    [('template_id.model_name', operator, name)],
                    [('color_ids.name', operator, name)],
                ]),
            ])
        return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    def action_duplicate_from_template_tab(self):
        self.ensure_one()
        wizard = self.env['dms.product.duplicate.wizard'].create({
            'source_product_id': self.id,
        })
        form_view = self.env.ref('dms_product.view_product_duplicate_wizard_form')
        return {
            'type': 'ir.actions.act_window',
            'name': '複製產品項',
            'res_model': 'dms.product.duplicate.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'new',
        }

    def action_open_installment_dialog(self):
        """在對話框開啟分期專用 form，只顯示分期方案，不含產品顏色 Tab。"""
        self.ensure_one()
        form_view = self.env.ref('dms_product.view_product_form_installment_dialog')
        return {
            'type': 'ir.actions.act_window',
            'name': f'產品項：{self.display_name}',
            'res_model': 'dms.product',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'new',
        }

    def action_save_and_stay(self):
        """儲存後保持視窗開啟。
        price_change_note 為 store=False，web_save 的 web_read 回傳空值，
        client 自動清空欄位；回傳 False 讓對話框原地停留。
        """
        self.ensure_one()
        return False

    def action_open_color_editor(self):
        self.ensure_one()
        form_view = self.env.ref('dms_sale.view_product_form')
        return {
            'type': 'ir.actions.act_window',
            'name': '維護產品顏色',
            'res_model': 'dms.product',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'new',
            'context': {
                **self.env.context,
                'active_test': False,
                'form_view_initial_mode': 'edit',
            },
        }

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        same_template_copy = (
            default.get('template_id', self.template_id.id) == self.template_id.id
        )
        if same_template_copy and 'production_year' not in default:
            default['production_year'] = False
            default.setdefault('year', False)
        default['internal_code'] = False
        default.setdefault('color', False)
        default.setdefault('color_code', False)
        copied = super(
            DmsProductCompat,
            self.with_context(skip_product_year_uniqueness=True),
        ).copy(default)
        if copied.production_year and not copied.internal_code:
            copied.with_context(
                skip_product_compat_sync=True,
                skip_product_year_uniqueness=True,
            ).write({
                'internal_code': copied._build_generated_code(),
            })
        elif not copied.production_year and copied.internal_code:
            copied.with_context(
                skip_product_compat_sync=True,
                skip_product_year_uniqueness=True,
            ).write({'internal_code': False})
        for color in self.with_context(active_test=False).color_ids:
            color.copy({'product_id': copied.id})
        copied._sync_legacy_color_summary()
        return copied

    def _sanitize_code_part(self, value):
        token = re.sub(r'[^A-Z0-9]+', '-', (value or '').upper()).strip('-')
        return token

    def _build_code_base(self):
        self.ensure_one()
        model_token = self._sanitize_code_part(
            self.model or self.template_id.model_name or self.name or self.template_id.family_name
        )
        year_value = self._normalize_year_value(self.production_year or self.year)
        year_token = self._sanitize_code_part(year_value) if year_value else ''
        parts = [part for part in [model_token, year_token] if part]
        return "-".join(parts)

    def _has_legacy_generated_code(self):
        self.ensure_one()
        return bool(LEGACY_GENERATED_CODE_PATTERN.match(self.internal_code or ''))

    def _build_generated_code(self):
        self.ensure_one()
        base_code = self._build_code_base()
        if not base_code:
            return f"SKU-{self.id:05d}"
        candidate = base_code
        suffix = 2
        while self.with_context(active_test=False).search_count([
            ('internal_code', '=', candidate),
            ('id', '!=', self.id),
        ]):
            candidate = f"{base_code}-{suffix:02d}"
            suffix += 1
        return candidate

    def _prepare_template_sync_vals(self):
        self.ensure_one()
        vals = {}
        if self.template_id:
            vals['brand_id'] = self.template_id.brand_id.id
            vals['name'] = self.template_id.family_name
            vals['model'] = self.template_id.model_name or False
            vals['energy_type'] = self.template_id.energy_type
        normalized_year = self._normalize_year_value(self.production_year)
        if normalized_year and normalized_year != (self.year or ''):
            vals['year'] = normalized_year
        return vals

    @api.model
    def _prepare_create_vals_from_template(self, vals):
        if not vals.get('template_id'):
            return vals
        template = self.env['dms.product.template'].browse(vals['template_id'])
        if not template.exists():
            return vals
        prepared = dict(vals)
        prepared.setdefault('brand_id', template.brand_id.id)
        prepared.setdefault('name', template.family_name)
        prepared.setdefault('model', template.model_name or False)
        prepared.setdefault('energy_type', template.energy_type)
        if prepared.get('production_year') and not prepared.get('year'):
            prepared['year'] = self._normalize_year_value(prepared['production_year'])
        return prepared

    def _ensure_template_from_legacy(self):
        self.ensure_one()
        if self.template_id:
            return self.template_id
        if not (self.brand_id and self.name and self.energy_type):
            return self.env['dms.product.template'].browse()
        template = self.env['dms.product.template']._find_or_create_from_legacy(self)
        return template

    def _pick_canonical_product(self, products):
        return products.sorted(key=lambda product: (not product.active, product.id))[0]

    def _merge_duplicate_product(self, canonical, duplicate):
        relation_models = {
            'dms.vehicle.price': {'unique_fields': []},
            'dms.ev.fee.schedule': {'unique_fields': []},
            'dms.commission.rule': {'unique_fields': []},
            'dms.visit.item': {'unique_fields': []},
            'dms.product.color': {'unique_fields': ['name']},
            'dms.vehicle.color': {'unique_fields': []},
            'dms.price.line': {'unique_fields': ['version_id']},
            'dms.installment.rule.binding': {'unique_fields': ['price_version_id']},
            'dms.sale.order': {'unique_fields': []},
        }

        for field_name in [
            'brake_type', 'engine_displacement', 'fuel_tank', 'engine_type',
            'consumption_grade', 'efficiency', 'max_hp', 'max_torque',
            'power_system', 'max_output', 'ev_max_hp', 'ev_max_torque',
            'ev_efficiency', 'transmission', 'battery_capacity', 'battery_type',
            'charge_time', 'dimensions', 'seat_height', 'wheel_base',
            'vehicle_weight', 'tire_front', 'tire_rear',
        ]:
            if not getattr(canonical, field_name) and getattr(duplicate, field_name):
                canonical.with_context(
                    skip_product_compat_sync=True,
                    skip_product_year_uniqueness=True,
                ).write({field_name: getattr(duplicate, field_name)})

        primary_color = canonical._ensure_color_record(
            duplicate.color,
            color_code=duplicate.color_code,
            image=getattr(duplicate, 'image_1920', False),
            active=duplicate.active,
        )
        color_map = {}
        for color in duplicate.with_context(active_test=False).color_ids:
            target_color = canonical._ensure_color_record(
                color.name,
                color_code=getattr(color, 'color_code', False),
                image=getattr(color, 'image_1920', False),
                active=color.active,
            )
            if target_color:
                color_map[color.id] = target_color.id

        for model_name, config in relation_models.items():
            if model_name not in self.env.registry.models:
                continue
            records = self.env[model_name].with_context(active_test=False).search([
                ('product_id', '=', duplicate.id),
            ])
            for record in records:
                if model_name == 'dms.sale.order':
                    vals = {'product_id': canonical.id}
                    if record.color_id:
                        mapped_color_id = color_map.get(record.color_id.id)
                        if mapped_color_id:
                            vals['color_id'] = mapped_color_id
                        else:
                            target_color = canonical._ensure_color_record(
                                record.color_id.name,
                                color_code=getattr(record.color_id, 'color_code', False),
                                image=getattr(record.color_id, 'image_1920', False),
                                active=record.color_id.active,
                            )
                            vals['color_id'] = target_color.id if target_color else False
                    elif primary_color:
                        vals['color_id'] = primary_color.id
                    record.write(vals)
                    continue

                if model_name == 'dms.product.color':
                    if record.id in color_map:
                        record.unlink()
                    else:
                        record.write({'product_id': canonical.id})
                    continue

                unique_fields = config.get('unique_fields') or []
                domain = [('product_id', '=', canonical.id)]
                for unique_field in unique_fields:
                    domain.append((unique_field, '=', record[unique_field].id))
                existing = self.env[model_name].with_context(active_test=False).search(
                    domain, limit=1)
                if existing and existing.id != record.id:
                    if hasattr(existing, 'note') and not existing.note and getattr(record, 'note', False):
                        existing.write({'note': record.note})
                    record.unlink()
                else:
                    record.write({'product_id': canonical.id})

        if duplicate.active and not canonical.active:
            canonical.with_context(
                skip_product_compat_sync=True,
                skip_product_year_uniqueness=True,
            ).write({'active': True})

        duplicate.unlink()

    @api.model
    def _consolidate_products_by_template_year(self):
        products = self.with_context(active_test=False).search([
            ('template_id', '!=', False),
        ], order='id')
        grouped_products = {}
        for product in products:
            year_value = product._normalize_year_value(product.production_year or product.year)
            if not year_value:
                continue
            grouped_products.setdefault((product.template_id.id, year_value), self.browse())
            grouped_products[(product.template_id.id, year_value)] |= product

        for grouped in grouped_products.values():
            if len(grouped) <= 1:
                grouped._ensure_color_records_from_legacy()
                grouped._sync_legacy_color_summary()
                continue
            canonical = self._pick_canonical_product(grouped)
            canonical._ensure_color_records_from_legacy()
            for duplicate in (grouped - canonical).sorted('id'):
                self._merge_duplicate_product(canonical, duplicate)
            canonical._sync_compat_fields()

    def _sync_compat_fields(self):
        if self.env.context.get('skip_product_compat_sync'):
            return
        for record in self:
            vals = {}
            template = record.template_id or record._ensure_template_from_legacy()
            if template and record.template_id != template:
                vals['template_id'] = template.id
            if not record.internal_code or record._has_legacy_generated_code():
                vals['internal_code'] = record._build_generated_code()
            normalized_production_year = record._normalize_year_value(record.production_year)
            if normalized_production_year != (record.production_year or False):
                vals['production_year'] = normalized_production_year
            if not normalized_production_year:
                normalized_year = record._normalize_year_value(record.year)
                if normalized_year:
                    vals['production_year'] = normalized_year
            if template:
                vals.update(record._prepare_template_sync_vals())
            if vals:
                super(
                    DmsProductCompat,
                    record.with_context(
                        skip_product_compat_sync=True,
                        skip_product_year_uniqueness=self.env.context.get(
                            'skip_product_year_uniqueness'
                        ),
                    ),
                ).write(vals)
        self._sync_color_templates()
        self._ensure_color_records_from_legacy()
        self._sync_legacy_color_summary()

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._prepare_create_vals_from_template(vals) for vals in vals_list]
        records = super().create(vals_list)
        records._sync_compat_fields()
        return records

    def write(self, vals):
        # 在寫入前快照舊價格，供日誌記錄使用
        price_fields = {'cash_price', 'list_price', 'promo_price'}
        records_snapshot = {}
        if price_fields.intersection(vals):
            for rec in self:
                records_snapshot[rec.id] = {
                    'old_cash_price': rec.cash_price,
                    'old_list_price': rec.list_price,
                    'old_promo_price': rec.promo_price,
                }

        result = super().write(vals)

        # 寫入價格異動日誌
        if records_snapshot:
            log_model = self.env['dms.product.price.log'].sudo()
            note = vals.get('price_change_note') or ''
            for rec in self:
                snap = records_snapshot.get(rec.id)
                if not snap:
                    continue
                new_cash = rec.cash_price
                new_list = rec.list_price
                new_promo = rec.promo_price
                if (snap['old_cash_price'] != new_cash
                        or snap['old_list_price'] != new_list
                        or snap['old_promo_price'] != new_promo):
                    log_model.create({
                        'product_id': rec.id,
                        'user_id': self.env.uid,
                        'old_cash_price': snap['old_cash_price'],
                        'new_cash_price': new_cash,
                        'old_list_price': snap['old_list_price'],
                        'new_list_price': new_list,
                        'old_promo_price': snap['old_promo_price'],
                        'new_promo_price': new_promo,
                        'note': note,
                    })

        # 儲存後清空 price_change_note：欄位為 store=False，web_read 自動回傳空值
        # 不需要 SQL clear

        tracked_fields = {
            'template_id', 'brand_id', 'name', 'model', 'year', 'energy_type',
            'production_year', 'internal_code', 'color', 'color_code', 'active',
        }
        if tracked_fields.intersection(vals):
            self._sync_compat_fields()
        return result

    @api.model
    def _run_product_backfill(self):
        products = self.with_context(
            skip_product_year_uniqueness=True,
        ).search([])
        products._sync_compat_fields()
        self.with_context(skip_product_year_uniqueness=True)._consolidate_products_by_template_year()
        self.search([])._sync_compat_fields()

    def _register_hook(self):
        result = super()._register_hook()
        self._run_product_backfill()
        return result
