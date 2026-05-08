#!/usr/bin/env python3
"""將 EV062 / EV062FL 的機種名稱統一修正為 eReady Fun。"""

from __future__ import annotations

import json
import os
import xmlrpc.client


ODOO_URL = os.environ.get('ODOO_URL', 'http://localhost:8069')
DB = os.environ.get('POSTGRES_DB', 'dmis_dev')
USER = os.environ.get('ODOO_USER', 'admin')
PASSWORD = os.environ.get('ODOO_PASSWORD', 'admin')


def main() -> None:
    common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
    uid = common.authenticate(DB, USER, PASSWORD, {})
    if not uid:
        raise SystemExit('Odoo 驗證失敗，請確認 ODOO_URL / ODOO_USER / ODOO_PASSWORD / POSTGRES_DB')

    models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
    result = models.execute_kw(
        DB,
        uid,
        PASSWORD,
        'dms.product',
        'fix_eready_fun_names',
        [],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()