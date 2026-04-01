"""
Migration 16.0.2.0.3 — 移除分期方案 rule_id 必填，改為直接填年利率

異動說明：
1. dms_product_installment_line.rule_id 改為可空
2. 新增 interest_rate 欄位
3. 更換 unique 約束：(product_id, rule_id, periods) → (product_id, periods)
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 1. rule_id 改可空
    cr.execute("""
        ALTER TABLE dms_product_installment_line
        ALTER COLUMN rule_id DROP NOT NULL;
    """)

    # 2. 新增 interest_rate
    cr.execute("""
        ALTER TABLE dms_product_installment_line
        ADD COLUMN IF NOT EXISTS interest_rate NUMERIC(5,4) DEFAULT 0.0 NOT NULL;
    """)

    # 3. 更換 unique constraint
    cr.execute("""
        ALTER TABLE dms_product_installment_line
        DROP CONSTRAINT IF EXISTS unique_product_rule_periods;
    """)
    cr.execute("""
        ALTER TABLE dms_product_installment_line
        ADD CONSTRAINT unique_product_periods UNIQUE (product_id, periods);
    """)

    _logger.info("migration 16.0.2.0.3: rule_id nullable, added interest_rate, updated unique constraint")
