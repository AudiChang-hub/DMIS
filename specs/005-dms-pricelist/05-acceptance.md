# 驗收標準（05-acceptance）— dms_pricelist

> 歷史文件註記（2026-03-27）：此驗收標準對應 `dms_pricelist` 獨立模組時期。現況請改依 [`specs/014-module-removal/05-acceptance.md`](/home/audi/project/DMIS/specs/014-module-removal/05-acceptance.md) 與 `dms_sale` 驗收結果判定。

## 安裝驗證
- [ ] `docker compose exec -T odoo bash -lc "PGHOST=db PGUSER=odoo PGPASSWORD=odoo odoo -d dmis_dev -i dms_pricelist --stop-after-init 2>&1 | tail -10"` 無 ERROR
- [ ] `/web/login` HTTP 200

## 功能驗收

### 車款售價
- [ ] 能新增車款售價（車款、現金售價、有效月份 YYYY-MM）
- [ ] 在 form 的分期方案 tab 中能新增多筆分期方案
- [ ] 每筆分期方案可填入：期數、月付金、分期公司
- [ ] 有效月份欄位格式可輸入 YYYY-MM

### 精品售價
- [ ] 能新增精品售價（名稱、型號、單價、安裝費、套裝組合、有效期）
- [ ] 有效起始/截止日期可留空（代表長期有效）

### 電車牌險費率
- [ ] product_id domain 限定僅能選電車車款（energy_type=electric）
- [ ] 能填入 8 項費用明細（行照費、檢驗費、號牌費、刻印費、保險費、公會證明費、文件處理費、其他）
- [ ] 合計欄位自動計算（唯讀）
- [ ] Form 頂部顯示油車提示橫幅
- [ ] 同一電車車款可有多筆（不同有效期）

### 傭金規則
- [ ] 能新增傭金規則（依車行+車款+期數）
- [ ] 車款欄位可留空（適用全部車款）
- [ ] 期數=0 代表現金傭金

## UI 合規（參照 `specs/000-roadmap/03-ui-standards.md`）
- [ ] 每個 tree 中所有欄位皆為 optional（active=show，其餘依顯示/隱藏原則）
- [ ] 每個 search view 有「啟用中」和「已歸檔」篩選器
- [ ] 所有 UI 文字為繁體中文
- [ ] fee_total 在 form 為唯讀，tree 中不顯示 fee_total 以外的計算欄位
