import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# 不追蹤的欄位類型（二進位太大、one2many/many2many 語義複雜）
_SKIP_TYPES = frozenset(['one2many', 'many2many', 'binary', 'serialized', 'properties'])


def _fmt_val(field_obj, val):
    """將欄位值轉為可讀字串，用於記錄舊值/新值。"""
    if val is False or val is None:
        return ''
    if field_obj.type == 'many2one':
        # val 是 browse record
        if hasattr(val, 'display_name'):
            return f"{val.display_name} (id={val.id})" if val else ''
        return str(val)
    if field_obj.type == 'selection':
        # 取 selection label
        selection_dict = dict(field_obj.selection if isinstance(field_obj.selection, list) else [])
        return selection_dict.get(val, str(val))
    if field_obj.type == 'boolean':
        return '是' if val else '否'
    return str(val)


class BaseAuditMixin(models.AbstractModel):
    """繼承 base，攔截所有 dms.* 模型的 create/write/unlink 並寫入操作歷程。"""
    _inherit = 'base'

    def _um_should_audit(self):
        return (
            self._name.startswith('dms.')
            and not self.env.context.get('_um_auditing')
        )

    def _um_write_log(self, action, record_id, record_name, changes_json=None):
        """實際寫入一筆 um.audit.log 記錄（呼叫時需已帶 _um_auditing context）。"""
        try:
            self.env['um.audit.log'].sudo().create({
                'user_id': self.env.uid,
                'user_name': self.env.user.name,
                'model_name': self._name,
                'model_desc': self._description or self._name,
                'record_id': record_id,
                'record_name': record_name or '',
                'action': action,
                'changed_fields': changes_json,
            })
        except Exception:
            _logger.exception('um.audit.log 寫入失敗（%s id=%s）', self._name, record_id)

    # ------------------------------------------------------------------ create
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self._um_should_audit():
            aenv = self.with_context(_um_auditing=True)
            for record in records:
                try:
                    rname = record.display_name
                except Exception:
                    rname = str(record.id)
                aenv._um_write_log('create', record.id, rname)
        return records

    # ------------------------------------------------------------------ write
    def write(self, vals):
        if self._um_should_audit() and self:
            # 只追蹤可安全讀取的純量/many2one 欄位
            tracked = [
                f for f in vals
                if f in self._fields
                and self._fields[f].type not in _SKIP_TYPES
                and not self._fields[f].compute
                and not self._fields[f].related
            ]
            # 擷取修改前的值
            old_data = {}
            if tracked:
                for r in self.sudo():
                    old_data[r.id] = {
                        f: _fmt_val(self._fields[f], r[f]) for f in tracked
                    }
        else:
            tracked = []
            old_data = {}

        result = super().write(vals)

        if old_data:
            aenv = self.with_context(_um_auditing=True)
            for r in self.sudo():
                if r.id not in old_data:
                    continue
                changes = {}
                for f in tracked:
                    old_v = old_data[r.id].get(f, '')
                    new_v = _fmt_val(self._fields[f], r[f])
                    if old_v != new_v:
                        label = self._fields[f].string or f
                        changes[label] = {'舊值': old_v, '新值': new_v}
                if changes:
                    try:
                        rname = r.display_name
                    except Exception:
                        rname = str(r.id)
                    aenv._um_write_log(
                        'write', r.id, rname,
                        json.dumps(changes, ensure_ascii=False),
                    )
        return result

    # ------------------------------------------------------------------ unlink
    def unlink(self):
        if self._um_should_audit() and self:
            pre_info = []
            for r in self.sudo():
                try:
                    rname = r.display_name
                except Exception:
                    rname = str(r.id)
                pre_info.append((r.id, rname))
        else:
            pre_info = []

        result = super().unlink()

        if pre_info:
            aenv = self.with_context(_um_auditing=True)
            for rid, rname in pre_info:
                aenv._um_write_log('unlink', rid, rname)

        return result
