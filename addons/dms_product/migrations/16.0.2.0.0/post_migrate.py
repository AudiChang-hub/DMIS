"""
dms_product 16.0.2.0.0 post-migration

將舊版 price.version/price.line 架構的資料遷移至產品欄位：
1. dms.price.line → dms.product.cash_price / list_price
   （取同一 product 中 effective_date 最新的有效或封存版本）
2. dms.installment.rule.binding → dms_product_installment_rule_rel (M2M)
3. 對每個有價格的 product 建立一筆初始 price.log
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info('dms_product migration 16.0.2.0.0: 開始資料遷移')
    _migrate_price_lines(cr)
    _migrate_bindings(cr)
    _logger.info('dms_product migration 16.0.2.0.0: 遷移完成')


def _migrate_price_lines(cr):
    """
    從 dms_price_line 取每個 product 最新有效/封存版本的價格，
    寫入 dms_product.cash_price 和 list_price。
    """
    cr.execute("""
        SELECT DISTINCT ON (pl.product_id)
            pl.product_id,
            pl.cash_price,
            pl.list_price
        FROM dms_price_line pl
        JOIN dms_price_version pv ON pv.id = pl.version_id
        WHERE pv.state IN ('effective', 'archive')
        ORDER BY
            pl.product_id,
            pv.effective_date DESC NULLS LAST,
            pv.id DESC
    """)
    rows = cr.fetchall()
    if not rows:
        _logger.info('dms_product migration: 無 dms_price_line 資料，跳過')
        return

    _logger.info('dms_product migration: 找到 %d 筆 price.line，開始轉移', len(rows))
    for product_id, cash_price, list_price in rows:
        cr.execute("""
            UPDATE dms_product
            SET cash_price = %s,
                list_price = %s,
                effective_price = CASE WHEN promo_price > 0 THEN promo_price ELSE %s END
            WHERE id = %s
              AND cash_price = 0
        """, (cash_price, list_price, cash_price, product_id))

    # 寫入初始 price.log
    cr.execute("""
        INSERT INTO dms_product_price_log
            (product_id, changed_at, user_id, old_cash_price, new_cash_price,
             old_list_price, new_list_price, note)
        SELECT DISTINCT ON (pl.product_id)
            pl.product_id,
            NOW(),
            1,
            0,
            pl.cash_price,
            0,
            pl.list_price,
            '由 dms.price.version 遷移'
        FROM dms_price_line pl
        JOIN dms_price_version pv ON pv.id = pl.version_id
        WHERE pv.state IN ('effective', 'archive')
          AND pl.product_id IN (
              SELECT id FROM dms_product WHERE cash_price > 0
          )
        ORDER BY
            pl.product_id,
            pv.effective_date DESC NULLS LAST,
            pv.id DESC
        ON CONFLICT DO NOTHING
    """)
    _logger.info('dms_product migration: price.line 遷移完成')


def _migrate_bindings(cr):
    """
    將 dms_installment_rule_binding 轉為 M2M 中繼表記錄。
    """
    cr.execute("SELECT COUNT(*) FROM dms_installment_rule_binding")
    count = cr.fetchone()[0]
    if not count:
        _logger.info('dms_product migration: 無 binding 資料，跳過')
        return

    _logger.info('dms_product migration: 找到 %d 筆 binding，開始轉移', count)
    cr.execute("""
        INSERT INTO dms_product_installment_rule_rel (product_id, rule_id)
        SELECT DISTINCT product_id, rule_id
        FROM dms_installment_rule_binding
        WHERE product_id IS NOT NULL AND rule_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    _logger.info('dms_product migration: binding 遷移完成')
