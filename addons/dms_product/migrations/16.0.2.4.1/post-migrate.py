# -*- coding: utf-8 -*-
"""把先前 fees_note 改 related 造成的 SKU 端資料遺失補回：
- gift_note 仍維持 related='template_id.note'
- fees_note 還原為 SKU 獨立 Text 欄位
- 從 template.note 用 bullet（●）逐項分析，含「開辦|分期|利率|期(只在數字附近)|手續費|購車金|設定費|0利率」等費用關鍵字者
  → 拆到該 template 所屬「所有 SKU」的 fees_note；
  → 同時從 template.note 移除被拆走的 bullet（保留純贈品 bullet）。

僅執行一次（migration 觸發），且只在 SKU.fees_note 為空時才寫入，避免覆蓋使用者手動填的資料。
"""
import logging
import re

_logger = logging.getLogger(__name__)

FEE_KEYWORDS = re.compile(r'(開辦費|手續費|設定費|分期|利率|0利率|購車金|現金分期|低利率|期\s*0)')


def migrate(cr, version):
    if not version:
        return

    # 重建 dms_product.fees_note 欄位定義（從 related store 退回成普通 text）
    # related store 欄位本來就是實體欄位，這裡確保保留欄位且不影響資料
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='dms_product' AND column_name='fees_note'
    """)
    if not cr.fetchone():
        cr.execute("ALTER TABLE dms_product ADD COLUMN fees_note TEXT")
        _logger.info('[dms_product migration] 補建 dms_product.fees_note 欄位')

    # 拆分邏輯：對每個 template，把 note 依 ● 切 bullet，分流贈品 / 費用
    cr.execute("""
        SELECT id, note FROM dms_product_template
        WHERE note IS NOT NULL AND btrim(note) <> ''
    """)
    rows = cr.fetchall()
    splitted = 0
    for tpl_id, note in rows:
        # 拆 bullet：以 ● 為分隔，保留首段（無 ● 開頭時也成立）
        parts = re.split(r'(?=●)', note)
        gift_parts, fee_parts = [], []
        for part in parts:
            stripped = part.strip()
            if not stripped:
                continue
            if FEE_KEYWORDS.search(stripped):
                fee_parts.append(stripped)
            else:
                gift_parts.append(stripped)

        if not fee_parts:
            continue  # 此 template 沒有費用內容，跳過

        new_gift = '\n'.join(gift_parts).strip() or None
        new_fees = '\n'.join(fee_parts).strip()

        # 寫回 template.note（移除費用 bullet）
        cr.execute(
            "UPDATE dms_product_template SET note = %s WHERE id = %s",
            (new_gift, tpl_id),
        )
        # 把費用部分寫到該 template 所屬「所有 SKU」的 fees_note；只有 fees_note 為空才覆蓋
        cr.execute(
            """
            UPDATE dms_product
            SET fees_note = %s
            WHERE template_id = %s
              AND (fees_note IS NULL OR btrim(fees_note) = '')
            """,
            (new_fees, tpl_id),
        )
        splitted += 1
        _logger.info(
            '[dms_product migration] template %s: 拆出費用 %r，剩餘贈品 %r',
            tpl_id, new_fees[:60], (new_gift or '')[:60],
        )

    _logger.info('[dms_product migration] 共處理 %s 個 template 的費用拆分', splitted)
