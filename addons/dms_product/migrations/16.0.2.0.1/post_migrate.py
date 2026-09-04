"""
dms_product 16.0.2.0.1 post-migration

合併「同 template_id + production_year 但不同顏色」的重複 product 記錄：
1. 對每個 (template_id, production_year) 分組，保留 id 最小的一筆（master）
2. 把其他筆的 dms_product_color.product_id → master
3. 把其他筆的 dms_sale_order.product_id → master
4. 把其他筆的 dms_product_price_log.product_id → master
5. 把其他筆的 dms_product_installment_rule_rel → master（去除衝突）
6. 刪除多餘的 product 記錄
7. 重算所有 product 的 color 摘要欄
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info('dms_product migration 16.0.2.0.1: 開始合併重複 product 記錄')
    _merge_duplicate_products(cr)
    _rebuild_color_summaries(cr)
    _logger.info('dms_product migration 16.0.2.0.1: 遷移完成')


def _merge_duplicate_products(cr):
    """
    找出同 (template_id, production_year) 中多筆的 product，
    保留最小 id 為 master，其餘的 slave 更新外鍵後刪除。
    """
    # 找出需要合併的分組
    cr.execute("""
        SELECT template_id, production_year, MIN(id) AS master_id,
               array_agg(id ORDER BY id) AS all_ids
        FROM dms_product
        WHERE template_id IS NOT NULL
          AND production_year IS NOT NULL
          AND production_year != ''
        GROUP BY template_id, production_year
        HAVING COUNT(*) > 1
    """)
    groups = cr.fetchall()
    if not groups:
        _logger.info('migration 16.0.2.0.1: 無重複 product，跳過合併')
        return

    _logger.info('migration 16.0.2.0.1: 發現 %d 組重複 product，開始合併', len(groups))

    for template_id, production_year, master_id, all_ids in groups:
        slave_ids = [i for i in all_ids if i != master_id]
        _logger.info('合併 template=%s year=%s: master=%s, slaves=%s',
                     template_id, production_year, master_id, slave_ids)

        for slave_id in slave_ids:
            # 1. dms_product_color → master（忽略名稱重複的衝突）
            cr.execute("""
                UPDATE dms_product_color
                SET product_id = %s
                WHERE product_id = %s
                  AND name NOT IN (
                      SELECT name FROM dms_product_color WHERE product_id = %s
                  )
            """, (master_id, slave_id, master_id))

            # 2. sale order → master
            cr.execute("""
                UPDATE dms_sale_order
                SET product_id = %s
                WHERE product_id = %s
            """, (master_id, slave_id))

            # 3. price log → master
            cr.execute("""
                UPDATE dms_product_price_log
                SET product_id = %s
                WHERE product_id = %s
            """, (master_id, slave_id))

            # 4. installment rule M2M → master（去除衝突）
            cr.execute("""
                INSERT INTO dms_product_installment_rule_rel (product_id, rule_id)
                SELECT %s, rule_id
                FROM dms_product_installment_rule_rel
                WHERE product_id = %s
                ON CONFLICT DO NOTHING
            """, (master_id, slave_id))

            # 5. 刪除 slave（剩餘顏色記錄已無法遷移的（名稱重複）一併刪除）
            cr.execute("DELETE FROM dms_product_color WHERE product_id = %s", (slave_id,))
            cr.execute("DELETE FROM dms_product_installment_rule_rel WHERE product_id = %s", (slave_id,))
            cr.execute("DELETE FROM dms_product WHERE id = %s", (slave_id,))

    _logger.info('migration 16.0.2.0.1: 合併完成，共處理 %d 組', len(groups))


def _rebuild_color_summaries(cr):
    """
    重算所有 product 的 color 摘要（將 color_ids 顏色名稱合併成字串）。
    """
    cr.execute("""
        UPDATE dms_product p
        SET color = subq.summary
        FROM (
            SELECT pc.product_id,
                   string_agg(pc.name, '、' ORDER BY pc.sequence, pc.id) AS summary
            FROM dms_product_color pc
            WHERE pc.active = true
            GROUP BY pc.product_id
        ) subq
        WHERE p.id = subq.product_id
    """)
    affected = cr.rowcount
    _logger.info('migration 16.0.2.0.1: 重算 %d 筆 product 的顏色摘要', affected)
