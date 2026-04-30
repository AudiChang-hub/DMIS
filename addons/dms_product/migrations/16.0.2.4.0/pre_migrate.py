# -*- coding: utf-8 -*-
"""Migration 16.0.2.4.0 — 將 SKU 的 gift_note / fees_note 提升至 template 層

dms.product.gift_note 與 dms.product.fees_note 改為 related='template_id.note'
與 related='template_id.fees_note'（store=True, readonly=False）。
為避免既有 SKU 端的獨立內容遺失，於 pre-migrate 將 SKU 上的非空值
回填到對應 template，僅在 template 端為空時才回寫，避免覆寫使用者既有資料。
"""


def migrate(cr, version):
    # 確保 template 端欄位已存在（應由 base init 階段建立）
    cr.execute("""
        ALTER TABLE dms_product_template
        ADD COLUMN IF NOT EXISTS fees_note text
    """)

    # 1) gift_note: SKU 端有值且 template.note 為空 -> 回填 template.note
    cr.execute("""
        UPDATE dms_product_template t
           SET note = sub.gift_note
          FROM (
              SELECT DISTINCT ON (template_id)
                     template_id, gift_note
                FROM dms_product
               WHERE template_id IS NOT NULL
                 AND gift_note IS NOT NULL
                 AND btrim(gift_note) <> ''
               ORDER BY template_id, id
          ) sub
         WHERE t.id = sub.template_id
           AND (t.note IS NULL OR btrim(t.note) = '')
    """)

    # 2) fees_note: SKU 端有值且 template.fees_note 為空 -> 回填
    cr.execute("""
        UPDATE dms_product_template t
           SET fees_note = sub.fees_note
          FROM (
              SELECT DISTINCT ON (template_id)
                     template_id, fees_note
                FROM dms_product
               WHERE template_id IS NOT NULL
                 AND fees_note IS NOT NULL
                 AND btrim(fees_note) <> ''
               ORDER BY template_id, id
          ) sub
         WHERE t.id = sub.template_id
           AND (t.fees_note IS NULL OR btrim(t.fees_note) = '')
    """)
