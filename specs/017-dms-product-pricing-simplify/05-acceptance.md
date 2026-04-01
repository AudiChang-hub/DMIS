# 05 — Acceptance：產品定價簡化（017-dms-product-pricing-simplify）

## 驗收指令

```bash
# 升級模組
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev -u dms_product,dms_sale --stop-after-init 2>&1 \
   | grep -E 'ERROR|WARNING|loaded' | tail -10"

# 執行測試
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev --test-enable --stop-after-init \
   -u dms_product,dms_sale 2>&1 \
   | grep -E 'tests\:|failed' | tail -5"

# Smoke test
docker compose restart odoo && bash scripts/smoke_odoo.sh
```

## 功能驗收項目

| # | 測試情境 | 預期結果 | 狀態 |
|---|----------|----------|------|
| AC-01 | 升級 `dms_product` 無 ERROR/WARNING，版本顯示 16.0.2.0.0 | 升級成功 | ⬜ |
| AC-02 | 開啟任一 `dms.product` 表單，可見「定價與分期」Tab | Tab 正常顯示 | ⬜ |
| AC-03 | 在「定價與分期」填入現金售價 → 儲存 → 「價格異動日誌」自動出現一筆記錄 | log 被寫入 | ⬜ |
| AC-04 | `promo_price = 0`：「有效售價」顯示等同 `cash_price`，顯示「無活動」提示 | computed 正確 | ⬜ |
| AC-05 | 填入 `promo_price > 0`：「有效售價」顯示 `promo_price`，`promo_note` 可填入 | computed 正確 | ⬜ |
| AC-06 | 在「適用分期規則」頁可加入 / 移除分期規則模板 | M2M 操作正常 | ⬜ |
| AC-07 | 一般使用者無法從 UI 手動新增或刪除「價格異動日誌」記錄 | 唯讀，無按鈕 | ⬜ |
| AC-08 | 新建銷售訂單，選擇已設定 `cash_price` 的車款，訂單 `cash_price` 自動帶入 | onchange 正確 | ⬜ |
| AC-09 | 新建銷售訂單，選擇已設定 `promo_price > 0` 的車款，訂單帶入 `promo_price` 值 | effective_price 優先 | ⬜ |
| AC-10 | 「產品管理」主選單中，「價目版本」和「規則掛接」子選單已不可見 | 選單已移除 | ⬜ |
| AC-11 | Migration 執行後，原 `dms.price.line` 的現金價已轉入對應 `dms.product.cash_price` | 資料不遺失 | ⬜ |
| AC-12 | Migration 執行後，原 `dms.installment.rule.binding` 已轉為 product.installment_rule_ids M2M | 資料不遺失 | ⬜ |
| AC-13 | 所有 dms_product + dms_sale 單元測試通過（0 FAIL / 0 ERROR） | 全數通過 | ⬜ |
| AC-14 | `make smoke` 通過（HTTP 200） | 環境正常 | ⬜ |

## 回歸驗證

- [ ] `dms_finance`：建立財務結算、淨利計算功能不受影響
- [ ] `dms_visit`：拜訪記錄模組與產品無關聯，功能正常
- [ ] `dms_report`：銷售 BI 報表讀取 `dms.sale.order.cash_price` 不受影響（欄位未變動）
