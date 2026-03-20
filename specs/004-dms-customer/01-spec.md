# 規格（01-spec）— dms_customer 客戶管理模組

## 模組資訊
| 項目 | 值 |
|---|---|
| 技術名稱 | `dms_customer` |
| 顯示名稱 | DMS 客戶管理 |
| 版本 | 16.0.1.0.0 |
| 依賴 | `base`, `web` |
| installable | True |
| application | True |

## 模型一：`res.partner`（繼承擴充）

### 新增欄位
| 欄位 | 型別 | 說明 |
|---|---|---|
| `is_dms_customer` | Boolean(default=False) | 標記為 DMS 客戶，視圖過濾用 |
| `id_number` | Char | 身分證字號 |
| `dms_birthday` | Date | 生日（西元） |
| `dms_birthday_roc` | Char（Computed, store=False） | 民國生日（自動換算，格式 YYY/MM/DD） |
| `address_registered` | Text | 戶籍地址（與聯絡地址分開） |
| `old_vehicle_ids` | One2many → dms.old.vehicle | 舊車資訊 |

### dms_birthday_roc 邏輯
```python
roc_year = dms_birthday.year - 1911
return f"{roc_year}/{dms_birthday.month:02d}/{dms_birthday.day:02d}"
```

## 模型二：`dms.old.vehicle`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `partner_id` | Many2one → res.partner（required） | 關聯客戶 |
| `plate_number` | Char | 舊車車牌號碼 |
| `vehicle_owner` | Char | 舊車車主名稱 |
| `control_account` | Char | 車控帳號 |
| `note` | Text | 備註 |

## 視圖規格

> 遵循全域 UI 標準（specs/000-roadmap/03-ui-standards.md）：active 欄位、全 optional、15 欄 JS 限制、歸檔篩選。

### 客戶 List View / Kanban View
- `optional="show"`（預設顯示，共 8 欄）：name、phone、mobile、email、id_number、dms_birthday_roc、address_registered、active
- `optional="hide"`（預設隱藏）：dms_birthday
- **Kanban View**：新增，顯示 name、phone、mobile、email；action view_mode 改為 `kanban,tree,form`

### 客戶 Form View
3 頁籤：
1. **基本資料**：name、phone、mobile、email、id_number、dms_birthday、dms_birthday_roc(readonly)
2. **地址**：address_registered（戶籍）、street/city/zip/country（聯絡地址，繼承自 res.partner）
3. **舊車資訊**：old_vehicle_ids（embedded tree）

### Search View
搜尋欄位：name、id_number、phone
Filter：
- 「DMS 客戶」= is_dms_customer=True
- 「啟用中」= active=True
- 「已歸檔」= active=False

### JS 15 欄限制
- 檔案：`dms_customer/static/src/js/dms_customer_column_limit.js`
- resModel：`res.partner`
- Patch 名稱：`dms_customer.partnerColumnLimit`

### 選單
- 頂層：`menu_dms_customer_root`（無 parent，獨立 App）
- 子選單：「客戶清單」

## 安全設定
| id | 模型 | group | R | W | C | D |
|---|---|---|---|---|---|---|
| access_dms_old_vehicle | dms.old.vehicle | (全員) | 1 | 1 | 1 | 1 |
（res.partner 沿用 base 現有權限，不需另設）
