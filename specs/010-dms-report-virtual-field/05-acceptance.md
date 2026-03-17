# 05 — Acceptance：驗收標準（dms_report_virtual）

## 驗收指令

```bash
# 安裝新模組
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev -i dms_report_virtual --stop-after-init 2>&1 \
   | grep -E 'ERROR|WARNING|Module|queries' | tail -20"

# 重啟確認
docker compose restart odoo
Start-Sleep -Seconds 20
docker compose ps
```

## 功能驗收項目

| # | 測試情境 | 預期結果 | 狀態 |
|---|----------|----------|------|
| AC-01 | 安裝 `dms_report_virtual`，無 ERROR/WARNING | queries > 0，Exit 0 | ⬜ |
| AC-02 | 「報表分析」選單出現「虛擬欄位」子選單 | 可見且可點擊 | ⬜ |
| AC-03 | 管理員建立虛擬欄位（code=brand_cat，model=dms.sale.order） | 記錄儲存成功 | ⬜ |
| AC-04 | 為虛擬欄位新增 contains 規則（field=dealer_id.name，condition=Yamaha，value=山葉） | 規則儲存成功 | ⬜ |
| AC-05 | 點擊「測試虛擬欄位」，輸入含 dealer_id.name=Yamaha 的記錄 ID，結果顯示「山葉」 | 計算結果正確 | ⬜ |
| AC-06 | 在報表規則中選取虛擬維度後，點「預覽報表」，彈出分組結果精靈 | 精靈顯示各虛擬值的計數 | ⬜ |
| AC-07 | 資料超過 1000 筆時，精靈顯示「結果已截斷（前 1000 筆）」警告 | 截斷提示可見 | ⬜ |
| AC-08 | 一般使用者無法看到他人的私有（public=False）虛擬欄位 | 清單中不顯示 | ⬜ |
| AC-09 | 以非法 regex（如 `[invalid`）建立規則，儲存時收到驗證錯誤 | ValidationError 提示 | ⬜ |
| AC-10 | 代碼格式不正確（含空格/特殊字元），儲存時收到驗證錯誤 | ValidationError 提示 | ⬜ |
| AC-11 | 既有 dms_report_rule「銷售報表」「利潤報表」功能正常 | 不受影響 | ⬜ |

## 既有模組回歸驗證

```bash
# 確認 dms_report_rule + dms_report 仍正常升級
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev -u dms_report_rule --stop-after-init 2>&1 \
   | grep -E 'ERROR|WARNING' | tail -5"
```

預期：無輸出。
