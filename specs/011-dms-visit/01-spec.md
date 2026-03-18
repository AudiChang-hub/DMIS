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
| `product_id` | Many2one → dms.product | 產品，必填，ondelete=restrict |
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
- `group_dms_visit_admin`：DMS/拜訪管理者

### 存取控制（ir.model.access.csv）

| model | user | admin |
|-------|------|-------|
| dms.visit.purpose | R | RWCD |
| dms.visit | RWC（no delete） | RWCD |
| dms.visit.item | RWC（no delete） | RWCD |

### Record Rule（record_rules.xml）
- `group_dms_visit_user`：domain = `[('visitor_id', '=', user.id)]`（read/write/create）
- `group_dms_visit_admin`：domain = `[(1, '=', 1)]`（all）

---

## 5. 模組清單（__manifest__.py）

```python
{
    'name': 'DMS 拜訪紀錄',
    'version': '16.0.1.0.0',
    'depends': ['dms_core', 'dms_product'],
    'application': False,
    'data': [
        'security/dms_visit_security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'views/visit_purpose_views.xml',
        'views/visit_views.xml',
        'views/dealer_visit_inherit.xml',
    ],
}
```
