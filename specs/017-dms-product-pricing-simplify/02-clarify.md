# 02 — Clarify：產品定價簡化澄清記錄

## Q1：「穩價機制」實際上表示什麼？

**A**：原廠對市場車款售價有管控，不允許業者自行調漲或大幅調降，因此：
- 售價幾乎不會主動調整，除非原廠通知
- 業者收到通知後，**直接更新當前售價**，不需要「預排未來生效日」
- 因此 `dms.price.version` 的「草稿→生效」流程在實務上從未被使用到

## Q2：「活動特殊價」的使用情境？

**A**：原廠不定期（如年節、母親節）推出補助或折扣活動，例如：
- 「Q2 原廠補助 3,000 元，特價 XX 元」
- 業務人員在接到通知後，在**該車款的產品頁**填入 `promo_price` 和 `promo_note`
- 活動結束後，將 `promo_price` 清零即可
- 同一車款在任一時間點**最多只有一個活動價**

**結論**：`promo_price` 是單純的「目前是否有促銷」的開關欄位，不需要時間範圍或複數筆活動記錄。

## Q3：為什麼用 `promo_price > 0` 而不是用 Boolean 開關？

**A**：直接用金額更直覺：
- 業務人員輸入活動價後就代表「活動開啟」
- 清零就代表「活動結束」
- 不需要額外勾選「是否啟用活動」

## Q4：訂單查價時要用哪個價格？

**A**：使用 `effective_price`（computed）：
- 若 `promo_price > 0`：使用 `promo_price`
- 否則：使用 `cash_price`

訂單的 `cash_price` 欄位在 onchange 帶入後，業務人員仍可手動修改（現有行為不變）。

## Q5：價格異動日誌（price.log）何時觸發？由誰觸發？

**A**：
- 觸發時機：`dms.product.write()` 且 `cash_price` 或 `list_price` 有變動時
- 寫入內容：舊值、新值、時間戳、操作者（`env.user`）
- 使用者在 UI 上只看得到這筆日誌，**無法手動新增或刪除**（ACL 僅 create，不給 write/unlink）
- Migration 時也為每筆 product 補寫一筆初始日誌，`note='由 dms.price.version 遷移'`

## Q6：Migration 時若同一車款有多個版本（price.version）的記錄，如何處理？

**A**：
- 取同一 `product_id` 在 state = `effective` 或 `archive` 中，`effective_date` **最新**的那一筆 `dms.price.line` 作為當前售價
- 若只有 `draft` 版本的 price.line，則以 `cash_price = 0` 遷移，並寫入 migration log 警告

## Q7：`dms.installment.rule` 與 `dms.product` 的關聯是否有方向性限制？

**A**：M2M 雙向可存取即可：
- 從產品頁：可以加入/移除適用的分期規則
- 從分期規則頁：可以看到哪些產品適用此規則（反向欄位）

一個產品可掛多個分期規則，一個分期規則也可被多個產品使用。

## Q8：現有 `dms.sale.order` 建立的訂單，`cash_price` 是否受影響？

**A**：**不受影響**。`cash_price` 只在 `onchange_product_id` 觸發時帶入，已建立的訂單不會因為產品價格修改而變動。這是現有行為，保持不動。
