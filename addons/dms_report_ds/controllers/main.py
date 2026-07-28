import logging

import requests
import werkzeug
from requests.adapters import HTTPAdapter

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Metabase 容器內部 URL（docker-compose service name）
METABASE_INTERNAL_URL = 'http://metabase:3000'

METABASE_SESSION = requests.Session()
METABASE_SESSION.mount('http://', HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0))
METABASE_SESSION.mount('https://', HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0))

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

    @http.route('/dms_report_ds/oil_owner_dashboard_data', type='json', auth='user')
    def oil_owner_dashboard_data(
        self, license_yms=None, models=None, regions=None, age_buckets=None
    ):
        """Return oil-car owner gender and age distribution for the custom dashboard."""
        cr = request.env.cr
        license_yms = [value for value in (license_yms or []) if value]
        models = [value for value in (models or []) if value]
        regions = [value for value in (regions or []) if value]
        age_buckets = [value for value in (age_buckets or []) if value]

        where = ["age_bucket IS NOT NULL"]
        params = []
        if license_yms:
            where.append("license_ym = ANY(%s)")
            params.append(license_yms)
        if models:
            where.append("model = ANY(%s)")
            params.append(models)
        if regions:
            where.append("region = ANY(%s)")
            params.append(regions)
        if age_buckets:
            where.append("age_bucket = ANY(%s)")
            params.append(age_buckets)
        where_sql = " AND ".join(where)

        base_cte = """
            WITH oil_sales AS (
                SELECT
                    license_ym,
                    model,
                    COALESCE(NULLIF(region, ''), '未設定') AS region,
                    CASE
                        WHEN sex = '男性' THEN '男性'
                        WHEN sex = '女性' THEN '女性'
                        ELSE '未填寫'
                    END AS gender,
                    CASE
                        WHEN age >= 13 AND age <= 17 THEN '13~17'
                        WHEN age >= 18 AND age <= 24 THEN '18~24'
                        WHEN age >= 25 AND age <= 34 THEN '25~34'
                        WHEN age >= 35 AND age <= 44 THEN '35~44'
                        WHEN age >= 45 AND age <= 54 THEN '45~54'
                        WHEN age >= 55 AND age <= 64 THEN '55~64'
                        WHEN age >= 65 THEN '65以上'
                    END AS age_bucket,
                    CASE
                        WHEN age >= 13 AND age <= 17 THEN 1
                        WHEN age >= 18 AND age <= 24 THEN 2
                        WHEN age >= 25 AND age <= 34 THEN 3
                        WHEN age >= 35 AND age <= 44 THEN 4
                        WHEN age >= 45 AND age <= 54 THEN 5
                        WHEN age >= 55 AND age <= 64 THEN 6
                        WHEN age >= 65 THEN 7
                    END AS age_sort
                FROM ds_sales_report
                WHERE state = 'confirmed'
                  AND energy_type = '油車'
                  AND age >= 13
                  AND model IS NOT NULL
            )
        """

        cr.execute(f"""
            {base_cte}
            SELECT gender, COUNT(*) AS count
            FROM oil_sales
            WHERE {where_sql}
            GROUP BY gender
        """, params)
        gender_counts = dict(cr.fetchall())

        cr.execute(f"""
            {base_cte}
            SELECT age_bucket, age_sort, COUNT(*) AS count
            FROM oil_sales
            WHERE {where_sql}
            GROUP BY age_bucket, age_sort
            ORDER BY age_sort
        """, params)
        age_counts = {row[0]: row[2] for row in cr.fetchall()}

        cr.execute(f"""
            {base_cte}
            SELECT DISTINCT model
            FROM oil_sales
            WHERE model IS NOT NULL
            ORDER BY model
        """)
        model_options = [row[0] for row in cr.fetchall()]

        cr.execute(f"""
            {base_cte}
            SELECT DISTINCT license_ym
            FROM oil_sales
            WHERE license_ym IS NOT NULL
            ORDER BY license_ym DESC
        """)
        license_ym_options = [row[0] for row in cr.fetchall()]

        cr.execute(f"""
            {base_cte}
            SELECT DISTINCT region
            FROM oil_sales
            WHERE region IS NOT NULL
            ORDER BY region
        """)
        region_options = [row[0] for row in cr.fetchall()]

        age_order = ['13~17', '18~24', '25~34', '35~44', '45~54', '55~64', '65以上']
        genders = [
            {'label': '男性', 'count': gender_counts.get('男性', 0)},
            {'label': '女性', 'count': gender_counts.get('女性', 0)},
            {'label': '未填寫', 'count': gender_counts.get('未填寫', 0)},
        ]
        ages = [
            {'label': label, 'count': age_counts.get(label, 0)}
            for label in age_order
        ]
        total = sum(item['count'] for item in ages)

        return {
            'total': total,
            'genders': genders,
            'ages': ages,
            'options': {
                'license_yms': license_ym_options,
                'models': model_options,
                'regions': region_options,
                'age_buckets': age_order,
            },
        }

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
            resp = METABASE_SESSION.request(
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

        # 若是 HTML，強制 <base href="/metabase/"> 並注入字體路徑修正腳本
        ctype = resp.headers.get('content-type', '')
        if 'text/html' in ctype.lower():
            body = resp.content
            try:
                text = body.decode('utf-8', errors='replace')
                import re as _re
                # 移除 Metabase 內建的 <base href="/">，改為我們的 /metabase/
                text = _re.sub(r'<base\s+href="[^"]*"\s*/?>', '', text, flags=_re.IGNORECASE)
                # 注入 <base> + insertRule monkey-patch
                # Metabase JS 透過 Emotion CSS-in-JS insertRule() 動態注入
                # @font-face 規則，url 為絕對路徑 /app/fonts/...
                # 我們 monkey-patch insertRule，在規則插入 CSSOM 前改寫路徑
                inject = (
                    '<base href="/metabase/">'
                    '<script>'
                    '(function(){'
                    'var orig=CSSStyleSheet.prototype.insertRule;'
                    'CSSStyleSheet.prototype.insertRule=function(r,i){'
                    'if(r&&r.indexOf("/app/fonts/")!==-1){'
                    'r=r.replace(/\\/app\\/fonts\\//g,"/metabase/app/fonts/");'
                    '}'
                    'return orig.call(this,r,i);'
                    '};'
                    '})();'
                    '</script>'
                )
                if '<head>' in text:
                    text = text.replace('<head>', '<head>' + inject, 1)
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
