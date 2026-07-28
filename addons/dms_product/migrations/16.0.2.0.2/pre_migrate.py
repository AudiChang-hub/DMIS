"""
Migration 16.0.2.0.2 — 產品分期方案橋接表

異動說明：
1. dms_installment_rule 加 interest_rate 欄位
2. 建立 dms_product_installment_line 橋接表
3. 將舊 M2M (dms_product_installment_rule_rel) + 舊 flat fee 欄位資料遷移至新表
4. 刪除舊欄位：installment_setup_fee, installment_opening_fee
5. 刪除舊 M2M 表：dms_product_installment_rule_rel
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 1. 新增 interest_rate 至 dms_installment_rule
    cr.execute("""
        ALTER TABLE dms_installment_rule
        ADD COLUMN IF NOT EXISTS interest_rate NUMERIC(5,4) DEFAULT 0.0 NOT NULL;
    """)
    _logger.info("migration 16.0.2.0.2: added interest_rate to dms_installment_rule")

    # 2. 建立 dms_product_installment_line
    cr.execute("""
        CREATE TABLE IF NOT EXISTS dms_product_installment_line (
            id          SERIAL PRIMARY KEY,
            product_id  INTEGER NOT NULL REFERENCES dms_product(id) ON DELETE CASCADE,
            rule_id     INTEGER NOT NULL REFERENCES dms_installment_rule(id) ON DELETE RESTRICT,
            periods     INTEGER NOT NULL DEFAULT 24,
            price_base  VARCHAR(8) NOT NULL DEFAULT 'cash',
            setup_fee   NUMERIC(12,0) DEFAULT 0,
            opening_fee NUMERIC(12,0) DEFAULT 0,
            monthly_payment NUMERIC(12,0) DEFAULT 0,
            note        VARCHAR,
            create_uid  INTEGER,
            write_uid   INTEGER,
            create_date TIMESTAMP DEFAULT NOW(),
            write_date  TIMESTAMP DEFAULT NOW(),
            CONSTRAINT unique_product_rule_periods UNIQUE (product_id, rule_id, periods)
        );
    """)
    _logger.info("migration 16.0.2.0.2: created dms_product_installment_line table")

    # 3. 遷移舊 M2M 資料（若舊表存在）
    cr.execute("""
        SELECT to_regclass('public.dms_product_installment_rule_rel') IS NOT NULL;
    """)
    m2m_exists = cr.fetchone()[0]

    if m2m_exists:
        # 遷移：每個 product+rule 組合建立一筆 line，帶入舊 flat fee
        cr.execute("""
            INSERT INTO dms_product_installment_line
                (product_id, rule_id, periods, price_base,
                 setup_fee, opening_fee, monthly_payment,
                 create_date, write_date)
            SELECT
                rel.product_id,
                rel.rule_id,
                24 AS periods,
                'cash' AS price_base,
                COALESCE(p.installment_setup_fee, 0),
                COALESCE(p.installment_opening_fee, 0),
                0 AS monthly_payment,
                NOW(),
                NOW()
            FROM dms_product_installment_rule_rel rel
            JOIN dms_product p ON p.id = rel.product_id
            ON CONFLICT (product_id, rule_id, periods) DO NOTHING;
        """)
        migrated = cr.rowcount
        _logger.info("migration 16.0.2.0.2: migrated %d rows from old M2M to installment_line", migrated)

        # 刪除舊 M2M 表
        cr.execute("DROP TABLE IF EXISTS dms_product_installment_rule_rel;")
        _logger.info("migration 16.0.2.0.2: dropped dms_product_installment_rule_rel")
    else:
        _logger.info("migration 16.0.2.0.2: old M2M table not found, skipping migration")

    # 4. 刪除舊欄位（若存在）
    for col in ('installment_setup_fee', 'installment_opening_fee'):
        cr.execute(f"""
            ALTER TABLE dms_product DROP COLUMN IF EXISTS {col};
        """)
    _logger.info("migration 16.0.2.0.2: dropped old flat fee columns from dms_product")
