# 驗收標準（05-acceptance）— dms_pricelist

## 安裝驗證
- [ ] `docker compose exec -T odoo bash -lc "PGHOST=db PGUSER=odoo PGPASSWORD=odoo odoo -d dmis_dev -i dms_pricelist --stop-after-init 2>&1 | tail -10"` 無 ERROR
- [ ] `/web/login` HTTP 200

## 功能驗收

### 車款售價
- [ ] 能新增車款售價（現金：installment_periods=0）
- [ ] 能新增分期方案（installment_periods > 0，填入月付金、分期公司）
- [ ] 車行欄位可留空（適用全部車行）
- [ ] 有效月份欄位格式可輸入 YYYY-MM

### 精品品項
- [ ] 能新增精品品項（名稱、型號）
- [ ] 精品表單中可直接新增/編輯售價記錄

### 精品售價
- [ ] 能新增精品售價（含安裝費、套裝組合名稱）
- [ ] 有效起始/截止日期可留空（代表長期有效）

### 牌險費率
- [ ] 能新增牌險費率（依車款：領牌費、強制險、代辦費）
- [ ] 同一車款可有多筆（不同有效期）

### 傭金規則
- [ ] 能新增傭金規則（依車行+車款+期數）
- [ ] 車款欄位可留空（適用全部車款）
- [ ] 期數=0 代表現金傭金

## UI 合規（參照 `specs/000-roadmap/03-ui-standards.md`）
- [ ] 每個 tree 中所有欄位皆為 optional（active=show，其餘依預設顯示/隱藏原則）
- [ ] 每個 search view 有「啟用中」和「已歸檔」篩選器
- [ ] `dms.accessory` 的 name/active 欄位 optional="show"
- [ ] 所有 UI 文字為繁體中文
