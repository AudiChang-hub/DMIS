import logging

import requests
import werkzeug

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Metabase 容器內部 URL（docker-compose service name）
METABASE_INTERNAL_URL = 'http://metabase:3000'

# 不轉發給 Metabase 的 hop-by-hop / 有問題 headers
HOP_BY_HOP = {
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
    'content-length', 'content-encoding',
}


class MetabaseController(http.Controller):

    @http.route('/dms_report_ds/metabase_config', type='json', auth='user')
    def metabase_config(self):
        # 預設使用 Odoo 反向代理（相對 URL，與 Odoo 同主機/同 HTTPS）
        base_url = (
            request.env['ir.config_parameter']
            .sudo()
            .get_param('dms_report_ds.metabase_url', '')
        )
        if not base_url:
            base_url = '/metabase'
        return {'base_url': base_url}

    @http.route(
        ['/metabase', '/metabase/<path:subpath>'],
        type='http', auth='user', methods=['GET', 'POST'], csrf=False,
    )
    def metabase_proxy(self, subpath='', **kwargs):
        """反向代理：把 /metabase/* 請求轉送到 Metabase 容器內部。"""
        target_url = f'{METABASE_INTERNAL_URL}/{subpath}'
        if request.httprequest.query_string:
            target_url += '?' + request.httprequest.query_string.decode('utf-8', 'ignore')

        fwd_headers = {
            k: v for k, v in request.httprequest.headers.items()
            if k.lower() not in HOP_BY_HOP
        }

        try:
            resp = requests.request(
                method=request.httprequest.method,
                url=target_url,
                headers=fwd_headers,
                data=request.httprequest.get_data(),
                cookies=request.httprequest.cookies,
                allow_redirects=False,
                stream=True,
                timeout=30,
            )
        except requests.RequestException as e:
            _logger.warning('Metabase proxy error: %s', e)
            return Response(f'Metabase proxy error: {e}', status=502)

        excluded = HOP_BY_HOP | {'content-security-policy', 'x-frame-options'}
        out_headers = [
            (k, v) for k, v in resp.raw.headers.items()
            if k.lower() not in excluded
        ]

        if 300 <= resp.status_code < 400 and 'location' in resp.headers:
            loc = resp.headers['location']
            if loc.startswith('/'):
                loc = '/metabase' + loc
            elif loc.startswith(METABASE_INTERNAL_URL):
                loc = '/metabase' + loc[len(METABASE_INTERNAL_URL):]
            out_headers = [(k, v) for k, v in out_headers if k.lower() != 'location']
            out_headers.append(('Location', loc))

        # 若是 HTML，強制 <base href="/metabase/"> 讓相對路徑解析正確
        ctype = resp.headers.get('content-type', '')
        if 'text/html' in ctype.lower():
            body = resp.content
            try:
                text = body.decode('utf-8', errors='replace')
                import re as _re
                # 移除 Metabase 內建的 <base href="/">，改為我們的 /metabase/
                text = _re.sub(r'<base\s+href="[^"]*"\s*/?>', '', text, flags=_re.IGNORECASE)
                if '<head>' in text:
                    text = text.replace('<head>', '<head><base href="/metabase/">', 1)
                body = text.encode('utf-8')
            except Exception:
                pass
            out_headers = [
                (k, v) for k, v in out_headers if k.lower() != 'content-length'
            ]
            return werkzeug.wrappers.Response(
                response=body,
                status=resp.status_code,
                headers=out_headers,
            )

        return werkzeug.wrappers.Response(
            response=resp.iter_content(chunk_size=8192),
            status=resp.status_code,
            headers=out_headers,
            direct_passthrough=True,
        )
