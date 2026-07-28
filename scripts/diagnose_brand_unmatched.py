#!/usr/bin/env python3
"""診斷 ds.sales.report.brand_type 中「未命中規則」的車行清單。

未命中 = brand_type 最終落入 ELSE s.dname 分支：
  - 不屬於前置條件（'馭盛網推' / '網路平台' / '中古車'）
  - 也不在 dms.dealer.brand.rule 啟用規則的 result 集合內

使用：
    python3 scripts/diagnose_brand_unmatched.py
"""
import subprocess
import sys

SQL = r"""
WITH known AS (
    SELECT DISTINCT result
    FROM dms_dealer_brand_rule
    WHERE active = TRUE
)
SELECT brand_type AS unmatched_name,
       COUNT(*)   AS order_count
FROM ds_sales_report
WHERE brand_type NOT IN (SELECT result FROM known)
  AND brand_type NOT IN ('馭盛網推', '網路平台', '中古車')
GROUP BY 1
ORDER BY 2 DESC, 1;
"""

SUMMARY_SQL = r"""
WITH known AS (
    SELECT DISTINCT result
    FROM dms_dealer_brand_rule
    WHERE active = TRUE
)
SELECT
    SUM(CASE WHEN brand_type IN ('馭盛網推','網路平台','中古車')
              OR brand_type IN (SELECT result FROM known)
             THEN 1 ELSE 0 END) AS matched,
    SUM(CASE WHEN brand_type NOT IN ('馭盛網推','網路平台','中古車')
              AND brand_type NOT IN (SELECT result FROM known)
             THEN 1 ELSE 0 END) AS unmatched,
    COUNT(*) AS total
FROM ds_sales_report;
"""


def run_psql(sql):
    cmd = [
        'docker', 'compose', 'exec', '-T', 'db',
        'psql', '-U', 'odoo', '-d', 'dmis_dev', '-A', '-F', '\t', '-c', sql,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()


def main():
    print('═' * 60)
    print(' brand_type 命中率摘要')
    print('═' * 60)
    summary = run_psql(SUMMARY_SQL)
    if len(summary) >= 2:
        cols = summary[0].split('\t')
        vals = summary[1].split('\t')
        for c, v in zip(cols, vals):
            print(f'  {c:>10s}: {v}')
    print()

    print('═' * 60)
    print(' 未命中清單（brand_type = dname，需評估補規則）')
    print('═' * 60)
    rows = run_psql(SQL)
    if len(rows) <= 1:
        print('  （無未命中項目）')
        return

    header = rows[0].split('\t')
    print(f'  {header[0]:<24s} {header[1]:>8s}')
    print('  ' + '-' * 33)
    for line in rows[1:]:
        # skip footer "(N rows)"
        if line.startswith('(') and 'rows' in line:
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        name, count = parts[0], parts[1]
        print(f'  {name:<24s} {count:>8s}')


if __name__ == '__main__':
    sys.exit(main())
