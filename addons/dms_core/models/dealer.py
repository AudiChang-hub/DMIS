import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class DealerTag(models.Model):
    _name = 'dms.dealer.tag'
    _description = '車行標籤'

    name = fields.Char(string='標籤名稱', required=True)


class Dealer(models.Model):
    _name = 'dms.dealer'
    _description = '車行'

    code = fields.Char(string='車行代碼', required=True)
    name = fields.Char(string='車行名稱', required=True)
    short_name = fields.Char(string='簡稱')
    owner_name = fields.Char(string='負責人', required=True)
    store_manager = fields.Char(string='店長', required=True)
    level = fields.Selection([
        ('distributor', '總經銷'),
        ('tier1', '一級'),
        ('tier2', '二級'),
        ('owned', '自營店'),
    ], string='車行層級', default='tier1')
    store_type = fields.Selection([
        ('direct', '直營'),
        ('franchise', '加盟'),
        ('partner', '合作'),
        ('other', '其他'),
    ], string='車行類型')
    parent_id = fields.Many2one('dms.dealer', string='上層車行', ondelete='set null')
    child_ids = fields.One2many('dms.dealer', 'parent_id', string='下層車行')
    active = fields.Boolean(string='啟用', default=True)
    contact_name = fields.Char(string='聯絡人')
    phone = fields.Char(string='電話')
    # New contact fields
    phone_1 = fields.Char(string='電話1')
    phone_2 = fields.Char(string='電話2')
    mobile = fields.Char(string='手機')
    mobile_fax = fields.Char(string='手機/傳真')
    email = fields.Char(string='電子郵件')
    address = fields.Text(string='地址')
    city = fields.Char(string='縣市')
    district = fields.Char(string='鄉鎮市區')
    tags = fields.Many2many('dms.dealer.tag', string='標籤')
    note = fields.Html(string='備註')
    partner_id = fields.Many2one('res.partner', string='Partner (選用)')

    # Price list permissions
    sym_gas_price_list = fields.Boolean(string='三陽油車價格表', default=False)
    sym_ev_price_list = fields.Boolean(string='三陽電車價格表', default=False)
    suzuki_gas_price_list = fields.Boolean(string='台鈴油車價格表', default=False)
    suzuki_ev_price_list = fields.Boolean(string='台鈴電車價格表', default=False)

    # Dispatch capacities
    sym_dispatch_capacity = fields.Integer(string='三陽排車容量')
    suzuki_dispatch_capacity = fields.Integer(string='台鈴排車容量')

    # Groups / activities
    sym_line_group = fields.Boolean(string='三陽LINE群組', default=False)
    suzuki_line_group = fields.Boolean(string='台鈴LINE群組', default=False)
    common_line_group = fields.Boolean(string='通用LINE群組', default=False)
    special_line_group = fields.Boolean(string='特殊LINE群組', default=False)
    holiday_gift = fields.Boolean(string='年節送禮', default=False)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', '車行代碼必須唯一')
    ]

    @api.constrains('parent_id')
    def _check_parent_no_cycle(self):
        for rec in self:
            if not rec.parent_id:
                continue
            parent = rec.parent_id
            if parent == rec:
                raise ValidationError('parent_id 不能指向自己')
            # 檢查循環
            seen = set()
            while parent:
                if parent.id in seen:
                    raise ValidationError('parent_id 造成循環，請檢查上層設定')
                seen.add(parent.id)
                parent = parent.parent_id

    @api.constrains('sym_dispatch_capacity', 'suzuki_dispatch_capacity')
    def _check_capacities_non_negative(self):
        for rec in self:
            for field_name in ('sym_dispatch_capacity', 'suzuki_dispatch_capacity'):
                val = getattr(rec, field_name)
                if val is not None and val < 0:
                    raise ValidationError('%s 不可為負數' % (self._fields[field_name].string or field_name))

    @api.model
    def name_get(self):
        result = []
        for rec in self:
            if rec.code:
                display = '[%s] %s' % (rec.code, rec.name or '')
            else:
                display = rec.name or ''
            result.append((rec.id, display))
        return result

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        args = args or []
        terms = [
            ('code', operator, name),
            ('name', operator, name),
            ('short_name', operator, name),
            ('phone_1', operator, name),
            ('phone_2', operator, name),
            ('mobile', operator, name),
            ('mobile_fax', operator, name),
        ]
        # build OR domain
        domain = []
        for term in terms[:-1]:
            domain += ['|', term]
        domain += [terms[-1]]
        return self.search(domain + args, limit=limit).name_get()

    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        # Call super() but guard against view-cache / combination errors; add logs for debugging
        # Add richer tracing: log context keys, HTTP request info (if present), and mark logs for easy grepping
        try:
            ctx_keys = list(self.env.context.keys()) if self.env and getattr(self.env, 'context', None) else []
        except Exception:
            ctx_keys = []
        try:
            from odoo import http as _http
            _req = getattr(_http, 'request', None)
            req_path = None
            req_params = None
            try:
                if _req and getattr(_req, 'httprequest', None):
                    req_path = getattr(_req.httprequest, 'path', None)
                req_params = getattr(_req, 'params', None)
            except Exception:
                req_path = None
                req_params = None
        except Exception:
            _req = None
            req_path = None
            req_params = None
        _logger.info('[DMS-CUSTOM-ARCH] ENTRY fields_view_get view_id=%s view_type=%s uid=%s ctx_keys=%s http_path=%s http_params=%s', view_id, view_type, self.env.uid, ctx_keys, req_path, bool(req_params))
        try:
            res = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
            _logger.info('[DMS-CUSTOM-ARCH] super returned view_id=%s view_type=%s uid=%s arch_is_str=%s', view_id, view_type, self.env.uid, isinstance(res.get('arch'), str))
        except Exception:
            # If super() fails (cache/view combination edge cases), try to return a safe tree arch
            try:
                view = self.env['ir.ui.view'].search([('model', '=', 'dms.dealer'), ('type', '=', 'tree')], limit=1)
                if view:
                    return {'arch': view.arch_db or '<tree/>', 'fields': view.get('fields') if hasattr(view, 'get') else {}, 'type': 'tree'}
            except Exception:
                # fallback minimal response
                return {'arch': '<tree/>', 'fields': {}, 'type': view_type}
        # Only modify the arch for tree views and only when it's safe to parse/replace
        if view_type == 'tree' and res and isinstance(res.get('arch'), str):
            try:
                try:
                    from lxml import etree
                except Exception:
                    return res
                cols = False
                try:
                    cols = self.env.user.dms_dealer_tree_cols
                except Exception:
                    cols = False
                if cols:
                    _logger.info('[DMS-CUSTOM-ARCH] found saved_cols for uid=%s: %r', self.env.uid, cols)
                    field_names = [f.strip() for f in cols.split(',') if f.strip()]
                    if field_names:
                        # build a new tree element and attempt to preserve basic attributes
                        root = etree.Element('tree')
                        try:
                            orig = etree.fromstring(res.get('arch', '<tree/>'))
                            for attr in ('create', 'edit', 'string'):
                                val = orig.get(attr)
                                if val:
                                    root.set(attr, val)
                        except Exception:
                            # if original arch can't be parsed, continue with minimal root
                            pass
                        for name in field_names:
                            node = etree.SubElement(root, 'field')
                            node.set('name', name)
                        arch_str = etree.tostring(root, encoding='unicode')
                        _logger.info('[DMS-CUSTOM-ARCH] returning custom arch for uid=%s arch=%s', self.env.uid, arch_str)
                        # return a minimal response with our custom arch so callers don't use cached combined arch
                        return {'arch': arch_str, 'fields': res.get('fields', {}), 'type': 'tree'}
            except Exception:
                # On any failure, return the original res unmodified
                _logger.exception('Dealer.fields_view_get failure; returning original res')
                return res
        return res


class ResUsers(models.Model):
    _inherit = 'res.users'

    dms_dealer_tree_cols = fields.Char(string='DMS 列表顯示欄位', help='逗號分隔的 dms.dealer 欄位名稱，順序決定列表顯示順序')


class DealerColumnsWizard(models.TransientModel):
    _name = 'dms.dealer.columns.wizard'
    _description = '車行欄位選擇 Wizard'

    field_ids = fields.Many2many(
        'ir.model.fields',
        'dms_dealer_wizard_rel',
        'wiz_id',
        'field_id',
        string='欄位',
        domain=[('model', '=', 'dms.dealer')]
    )

    field_labels = fields.Char(string='欄位標籤', compute='_compute_field_labels', readonly=True)

    def apply(self):
        uid = self.env.uid
        names = ','.join(self.field_ids.mapped('name'))
        _logger.info('[DMS-CUSTOM-APPLY] uid=%s applying cols=%r', uid, names)
        self.env.user.sudo().write({'dms_dealer_tree_cols': names})
        _logger.info('[DMS-CUSTOM-APPLY] uid=%s wrote dms_dealer_tree_cols=%r', uid, names)
        # Build a minimal tree arch based on selected names and create a temporary
        # per-user ir.ui.view so we can return an act_window that forces the
        # client to open the list with our custom tree view immediately.
        try:
            try:
                from lxml import etree
            except Exception:
                etree = None
            if etree and names:
                root = etree.Element('tree')
                for n in [f.strip() for f in names.split(',') if f.strip()]:
                    node = etree.SubElement(root, 'field')
                    node.set('name', n)
                arch_str = etree.tostring(root, encoding='unicode')
            else:
                arch_str = '<tree/>'
        except Exception:
            _logger.exception('[DMS-CUSTOM-ARCH] failed to build arch in apply()')
            arch_str = '<tree/>'

        # create a temporary view record for this user and return an act_window
        try:
            uid = self.env.uid
            name_prefix = 'dms.dealer.tree.user.%s.' % (uid,)
            v_env = self.env['ir.ui.view'].sudo()
            # cleanup any previous temporary views for this user (best-effort)
            try:
                old = v_env.search([('name', 'like', name_prefix)])
                if old:
                    old.unlink()
            except Exception:
                pass
            view = v_env.create({
                'name': name_prefix + fields.Datetime.now(),
                'type': 'tree',
                'model': 'dms.dealer',
                'arch_db': arch_str,
            })
            _logger.info('[DMS-CUSTOM-APPLY] created temporary view id=%s name=%s for uid=%s', view.id, view.name, uid)
            return {
                'type': 'ir.actions.act_window',
                'name': '車行',
                'res_model': 'dms.dealer',
                'view_mode': 'tree,form',
                'views': [(view.id, 'tree')],
                'target': 'current',
            }
        except Exception:
            _logger.exception('[DMS-CUSTOM-ARCH] failed to create temporary view for uid=%s; falling back to client reload', self.env.uid)
            return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def default_get(self, fields_list):
        res = super(DealerColumnsWizard, self).default_get(fields_list)
        # pre-select the fields that are currently saved on the user
        cols = False
        try:
            cols = self.env.user.dms_dealer_tree_cols
        except Exception:
            cols = False
        if cols:
            names = [f.strip() for f in cols.split(',') if f.strip()]
            if names:
                imf = self.env['ir.model.fields'].sudo()
                records = imf.search([('model', '=', 'dms.dealer'), ('name', 'in', names)])
                if records:
                    res['field_ids'] = [(6, 0, records.ids)]
        return res

    @api.depends('field_ids')
    def _compute_field_labels(self):
        for rec in self:
            rec.field_labels = ', '.join(rec.field_ids.mapped('field_description') or [])
    def _nop(self):
        # placeholder to keep class structure stable
        return True


class DealerColumns(models.Model):
    _name = 'dms.dealer.columns'
    _description = '使用者車行欄位設定'

    user_id = fields.Many2one('res.users', string='使用者', required=True, default=lambda self: self.env.user)
    field_ids = fields.Many2many('ir.model.fields', 'dms_dealer_cols_rel', 'config_id', 'field_id', string='欄位',
                                 domain=[('model', '=', 'dms.dealer')])
