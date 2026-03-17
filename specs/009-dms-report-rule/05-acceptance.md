# 05 — Acceptance：驗收標準（dms_report_rule）

## 驗收指令

```bash
# 安裝新模組
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev -i dms_report_rule --stop-after-init 2>&1 \
   | grep -E 'ERROR|WARNING|Module' | tail -20"

# 重啟並確認
docker compose restart odoo
Start-Sleep -Seconds 20
docker compose ps
```

## 功能驗收項目

| # | 測試情境 | 預期結果 | 狀態 |
|---|----------|----------|------|
| AC-01 | 安裝 `dms_report_rule` 後無 ERROR / WARNING | queries > 0，無 ERROR 字樣 | ⬜ |
| AC-02 | 「報表分析」選單出現「報表規則」子項目 | 可見且可點擊 | ⬜ |
| AC-03 | 管理員建立規則（選 dms.sale.order，維度 order_date，指標 amount_total，圖表 bar） | 記錄成功儲存 | ⬜ |
| AC-04 | 點擊「預覽報表」後開啟 Graph 視圖，類型為 bar，模型為 dms.sale.order | Action window 正確開啟 | ⬜ |
| AC-05 | 建立 pivot 類型規則，預覽後開啟 Pivot 視圖 | view_mode 為 pivot | ⬜ |
| AC-06 | 管理員可刪除任意規則；一般使用者刪除他人規則時收到權限錯誤 | 權限控管正確 | ⬜ |
| AC-07 | 設定 `public=False` 的規則，一般使用者登入後無法在清單看到該規則 | 記錄規則生效 | ⬜ |
| AC-08 | 設定 `public=True` 的規則，一般使用者登入後可在清單看到但無法編輯/刪除 | 可讀不可寫 | ⬜ |
| AC-09 | `filter_domain` 填入非法字串後點「預覽」，不崩潰 | 以空 domain 替代，彈出 Graph/Pivot 視圖 | ⬜ |
| AC-10 | 既有「銷售報表」、「利潤報表」、「傭金報表」選單功能正常 | 不受影響 | ⬜ |

## 模組升降級驗證

```bash
# 確認 dms_report 仍正常
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev -u dms_report --stop-after-init 2>&1 \
   | grep -E 'ERROR|WARNING' | tail -5"
```

預期：無輸出（無 ERROR/WARNING）。
