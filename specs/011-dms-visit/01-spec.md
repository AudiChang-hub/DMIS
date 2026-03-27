# 01 — Spec：拜訪紀錄模組（dms_visit）

## 1. 模型定義

### 1.1 dms.visit.purpose（拜訪目的類別）

| 欄位 | 類型 | 說明 |
|------|------|------|
| `name` | Char | 目的名稱，必填 |
| `code` | Char | 短碼 |
| `sequence` | Integer | 排序，預設 10 |
| `active` | Boolean | 啟用，預設 True |

### 1.2 dms.visit（拜訪紀錄）— 主模型

| 欄位 | 類型 | 說明 |
|------|------|------|
| `name` | Char | 顯示名稱，computed（可覆寫），格式：「拜訪 YYYY-MM-DD 車行名稱」 |
| `visit_date` | Datetime | 拜訪日期，必填，預設今日 |
| `dealer_id` | Many2one → dms.dealer | 拜訪車行，必填，ondelete=restrict |
| `dealer_address` | Char | related → dealer_id.address，只讀顯示 |
| `dealer_phone` | Char | related → dealer_id.phone_1，只讀顯示 |
| `visitor_id` | Many2one → res.users | 拜訪人員，必填，預設目前登入者 |
| `purpose_id` | Many2one → dms.visit.purpose | 拜訪目的，ondelete=set null |
| `note` | Text | 備註 |
| `item_ids` | One2many → dms.visit.item | 送出物品明細 |
| `state` | Selection | draft/done/cancel，預設 draft |
| `company_id` | Many2one → res.company | 公司，預設為目前公司 |

#### computed name 規則
- `@api.depends('visit_date', 'dealer_id')`
- 格式：「拜訪 YYYY-MM-DD {dealer.name}」

#### state 流轉
```
draft → done   (action_done)
draft → cancel (action_cancel)
done  → draft  (action_draft)
cancel → draft (action_draft)
```

#### onchange 行為
- 選擇 `dealer_id` 後，`dealer_address`、`dealer_phone` 自動帶出（related 欄位，唯讀，無需儲存）。
- 儲存時若 `visit_date` 早於現在，顯示提醒（onchange warning），不阻擋儲存（允許回填）。

### 1.3 dms.visit.item（拜訪送出物品）

| 欄位 | 類型 | 說明 |
|------|------|------|
| `visit_id` | Many2one → dms.visit | 所屬拜訪，必填，ondelete=cascade |
| `product_id` | Many2one → dms.product | 產品，必填，ondelete=restrict（模型由 `dms_sale` 提供） |
| `quantity` | Float | 數量，預設 1.0 |
| `note` | Text | 備註 |

### 1.4 dms.dealer（繼承擴充）

新增欄位：
| 欄位 | 類型 | 說明 |
|------|------|------|
| `visit_ids` | One2many → dms.visit | 所有拜訪紀錄 |
| `visit_count` | Integer | computed，拜訪次數 |

新增方法：
- `action_open_visits()`：回傳 act_window 動作，domain 限定 dealer_id=self.id。

---

## 2. 視圖規格

### 2.1 visit_views.xml

#### Tree 視圖
顯示欄位：`visit_date`、`dealer_id`、`visitor_id`、`purpose_id`、`state`

搜尋視圖：
- 搜尋：`dealer_id`、`visitor_id`、`purpose_id`
- 篩選：「今日拜訪」、「草稿」、「已完成」、「已取消」
- 群組：按月份、按車行、按拜訪人員

#### Form 視圖
- Header：狀態按鈕（確認完成、取消、重置草稿）+ Status Bar
- Sheet：
  - 基本資訊群組：`name`、`visit_date`、`dealer_id`、`dealer_address`（唯讀）、`dealer_phone`（唯讀）、`visitor_id`、`purpose_id`、`company_id`
  - Notebook：
    - 「備註」頁籤：`note`
    - 「送出物品」頁籤：`item_ids` editable tree（product_id、quantity、note）

#### Calendar 視圖
```xml
<calendar date_start="visit_date" color="state" mode="month">
  <field name="dealer_id"/>
  <field name="visitor_id"/>
</calendar>
```

### 2.2 visit_purpose_views.xml

Tree + Form 視圖，管理員可讀寫。

### 2.3 dealer_visit_inherit.xml

繼承 `dms_core.view_dealer_form`，在 `<sheet>` 前新增 `button_box`：
```xml
<button class="oe_stat_button" type="object" name="action_open_visits" icon="fa-calendar">
  <field name="visit_count" widget="statinfo" string="拜訪紀錄"/>
</button>
```

---

## 3. 選單結構

父選單使用 `dms_core.menu_dms_root`（車行管理）：

| 選單 ID | 名稱 | action | sequence | groups |
|---------|------|--------|----------|--------|
| `menu_dms_visit_list` | 拜訪清單 | action_dms_visit_list | 20 | group_dms_visit_user + group_dms_visit_admin |
| `menu_dms_visit_calendar` | 拜訪行事曆 | action_dms_visit_calendar | 25 | group_dms_visit_user + group_dms_visit_admin |
| `menu_dms_visit_purpose` | 拜訪目的類別 | action_visit_purpose | 30 | group_dms_visit_admin |

---

## 4. 安全設定

### 群組（dms_visit_security.xml）
- `group_dms_visit_user`：DMS/拜訪使用者
- `group_dms_visit_admin`：DMS/拜訪管理者（implied_ids → group_dms_visit_user）

### 車行管理群組整合（dms_core 群組）
來自 `dms_core` 的 `group_dms_dealer_sales`（業務人員）與 `group_dms_dealer_manager`（車行管理者）
亦需具備拜訪模型存取權限，並受 Record Rule 限制。

| 菜單 | 新增可見群組 |
|------|-------------|
| menu_dms_visit_list | +`dms_core.group_dms_dealer_sales` |
| menu_dms_visit_calendar | +`dms_core.group_dms_dealer_sales` |
| menu_dms_visit_purpose | +`dms_core.group_dms_dealer_manager` |
| menu_dms_kanban_dealer_config | +`dms_core.group_dms_dealer_manager` |
| menu_dms_public_holiday | +`dms_core.group_dms_dealer_manager` |
| menu_dms_holiday_sync | +`dms_core.group_dms_dealer_manager` |

### 存取控制（ir.model.access.csv）

| model | group_dms_visit_user | group_dms_visit_admin | group_dms_dealer_sales | group_dms_dealer_manager |
|-------|------|-------|---|---|
| dms.visit.purpose | R | RWCD | R | RWCD |
| dms.visit | RWC | RWCD | RWC | RWCD |
| dms.visit.item | RWC | RWCD | RWC | RWCD |
| dms.visit.schedule | R | RWCD | R | R |
| dms.kanban.dealer.config | R | RWCD | R | RWCD |
| dms.public.holiday | R | RWCD | R | RWCD |

### Record Rule（record_rules.xml）
- `group_dms_visit_user`：domain = `[('visitor_id', '=', user.id)]`（read/write/create）
- `group_dms_visit_admin`：domain = `[(1, '=', 1)]`（all）
- `group_dms_dealer_sales`：domain = `[('visitor_id', '=', user.id)]`（read/write/create）
- `group_dms_dealer_manager`：無 Rule（預設可見全部）

---

## 5. 模組清單（__manifest__.py）

```python
{
    'name': 'DMS 拜訪紀錄',
    'version': '16.0.1.0.0',
    'depends': ['dms_core', 'dms_sale'],
    'application': False,
    'data': [
        'security/dms_visit_security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/visit_cron.xml',
        'views/visit_purpose_views.xml',
        'views/visit_views.xml',
        'views/dealer_visit_inherit.xml',
    ],
}
```

---

## 6. 自動拜訪排程（v1.2 更新）

### 6.1 新增模型 `dms.visit.schedule`

> 自動拜訪已從車行上的兩個布林/負責人欄位，升級為可維護多筆規則的排程模型。

| 欄位 | 類型 | 說明 |
|------|------|------|
| `dealer_id` | Many2one → dms.dealer | 車行，必填 |
| `active` | Boolean | 是否啟用，預設 True |
| `purpose_id` | Many2one → dms.visit.purpose | 拜訪目的，必填 |
| `visitor_id` | Many2one → res.users | 拜訪業務人員，留空則 fallback admin |
| `interval_months` | Selection | 頻率：每月 / 每兩個月 / 每季 / 每半年 / 每年 |
| `schedule_type` | Selection | 固定日期 / 每月第 N 個星期幾 |
| `day_of_month` | Integer | 固定日期模式使用（1–28） |
| `week_number` | Selection | 第幾週 |
| `weekday` | Selection | 星期幾 |
| `schedule_summary` | Char | 人性化週期摘要（computed） |
| `next_date` | Date | 下一筆預計日期（computed） |

### 6.2 `dms.dealer` 擴充

新增欄位：

| 欄位 | 類型 | 說明 |
|------|------|------|
| `visit_schedule_ids` | One2many → dms.visit.schedule | 此車行的自動拜訪排程 |

### 6.3 方法（`dms.visit.schedule` / `dms.dealer`）

#### `dms.visit.schedule._regenerate_future_visits()`
- 依目前排程設定重新產生未來 horizon 內的草稿拜訪
- 先刪除同排程未來草稿，再依規則重建

#### `dms.visit.schedule._topup_future_visits()`
- 用於 cron 補齊漏掉的未來拜訪
- 同一天若已有未取消的拜訪則不重複建立

#### `dms.dealer.cron_generate_price_list_visits()`
- 每日執行
- 搜尋所有啟用中的 `dms.visit.schedule`
- 對每筆排程呼叫 `_topup_future_visits()`
- 記錄 `_logger.info(...)` 統計

### 6.4 排程（data/visit_cron.xml）

- 以 `dms.dealer` 為 cron model，執行 `model.cron_generate_price_list_visits()`
- 任務目的從「單一價格表月拜訪」擴充為「補足所有啟用排程的未來拜訪」

---

## 7. 車行列表 Kanban 視圖（v1.1 新增）

在 `dms_visit` 模組新增 `views/dealer_kanban_inherit.xml`，繼承並補充 `dms_core` 的 act_window。

### 7.1 Kanban 視圖規格

| 項目 | 內容 |
|------|------|
| 視圖 model | dms.dealer |
| 排序 | 預設（dealer_id order） |
| 每卡顯示欄位 | name、store_type_id、owner_name、phone_1、visit_count |
| Smart Button 連結 | action_open_visits（拜訪次數） |
| 手機行動友善 | 字體 ≥ 14px，按鈕高度 ≥ 44px |

### 7.2 act_window 更新

`dms_core.action_dealer` 的 `view_mode` 擴充為 `tree,kanban,form`。
