import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Monkeypatch the WebClient.load to add tracing for actions that load dms.dealer
try:
    from odoo.addons.web.controllers import action as web_action
    _orig_load = getattr(web_action.WebClient, 'load', None)
except Exception:
    web_action = None
    _orig_load = None


def _wrapped_load(self, action_type=None, action_id=None, **kw):
    try:
        uid = request.env.uid if request and getattr(request, 'env', None) else 'n/a'
    except Exception:
        uid = 'n/a'
    try:
        act = None
        if action_id:
            try:
                act = request.env['ir.actions.act_window'].sudo().browse(int(action_id))
            except Exception:
                act = None
        if act and act.res_model == 'dms.dealer':
            _logger.info('[DMS-CUSTOM-ARCH] web.action.load ENTRY action_id=%s res_model=%s uid=%s', action_id, act.res_model, uid)
    except Exception:
        _logger.exception('[DMS-CUSTOM-ARCH] error in pre-load tracing')
    # call original
    try:
        result = _orig_load(self, action_type=action_type, action_id=action_id, **kw)
    except Exception:
        _logger.exception('[DMS-CUSTOM-ARCH] original web.action.load raised')
        raise
    try:
        if act and act.res_model == 'dms.dealer':
            # Log a short summary of the result to help identify if custom arch was returned
            _logger.info('[DMS-CUSTOM-ARCH] web.action.load EXIT action_id=%s uid=%s result_keys=%s', action_id, uid, list(result.keys()) if isinstance(result, dict) else type(result))
    except Exception:
        _logger.exception('[DMS-CUSTOM-ARCH] error in post-load tracing')
    return result


if _orig_load:
    try:
        web_action.WebClient.load = _wrapped_load
        _logger.info('[DMS-CUSTOM-ARCH] installed web.action.load wrapper')
    except Exception:
        _logger.exception('[DMS-CUSTOM-ARCH] failed to install web.action.load wrapper')
else:
    _logger.warning('[DMS-CUSTOM-ARCH] original WebClient.load not found; tracing not installed')
