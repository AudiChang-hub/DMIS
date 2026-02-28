# 規格（01-spec）— dms_product 產品管理模組

## 模組資訊
| 項目 | 值 |
|---|---|
| 技術名稱 | `dms_product` |
| 顯示名稱 | DMS 產品管理 |
| 版本 | 16.0.1.0.0 |
| 依賴 | `dms_core`, `web` |
| installable | True |
| application | False |

## 主要模型：`dms.product`（產品管理）

### 基本資料
| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `brand_id` | Many2one → `dms.brand` | ✓ | 品牌（來自 dms_core） |
| `name` | Char | ✓ | 名稱 |
| `model` | Char | | 型號 |
| `year` | Char | | 年份 |
| `brake_type` | Char | | 煞車型式 |
| `energy_type` | Selection(oil/electric) | ✓ | 能源型式，控制動力規格頁籤可見性 |
| `color` | Char | | 顏色 |
| `active` | Boolean(default=True) | | 啟用（False=歸檔） |

### 動力規格（油車）— 僅 energy_type='oil' 時顯示頁籤
| 欄位 | 型別 | 說明 |
|---|---|---|
| `engine_displacement` | Char | 總排氣量 (cc) |
| `fuel_tank` | Char | 油箱容量 (L) |
| `engine_type` | Char | 引擎型式 |
| `consumption_grade` | Char | 能耗等級 |
| `efficiency` | Char | 能源效率 (km/L) |
| `max_hp` | Char | 最大馬力 (hp) |
| `max_torque` | Char | 最大扭力 (Nm) |

### 動力規格（電車）— 僅 energy_type='electric' 時顯示頁籤
| 欄位 | 型別 | 說明 |
|---|---|---|
| `power_system` | Char | 動力系統 |
| `max_output` | Char | 最大功率 (kW) |
| `ev_max_hp` | Char | 最大馬力 EV (hp) |
| `ev_max_torque` | Char | 最大扭力 EV (Nm) |
| `ev_efficiency` | Char | 能源效率 EV (kWh/km) |
| `transmission` | Char | 傳動系統 |
| `battery_capacity` | Char | 電池容量 (kWh) |
| `battery_type` | Char | 電池型式 |
| `charge_time` | Char | 充電時間 (hr) |

### 車身規格（永遠顯示頁籤）
| 欄位 | 型別 | 說明 |
|---|---|---|
| `dimensions` | Text | 車輛尺寸 (mm) |
| `seat_height` | Char | 座高 (mm) |
| `wheel_base` | Char | 軸距 (mm) |
| `vehicle_weight` | Char | 車重 (kg) |
| `tire_front` | Char | 前輪規格 |
| `tire_rear` | Char | 後輪規格 |

## 視圖規格

### List View（tree）
- 預設顯示（optional="show"）：8 欄（brand_id、name、model、year、brake_type、energy_type、color、active）
- 預設隱藏（optional="hide"）：22 欄（7 油車 + 9 電車 + 6 車身）
- **JS 硬限制**：最多同時顯示 15 欄；超過時阻止切換、顯示 warning、強制 OWL rerender 回復 checkbox

### Form View
- 4 頁籤（notebook）：
  1. 基本資料（永遠顯示）
  2. 動力規格(油車)：`attrs="{'invisible': [('energy_type', '!=', 'oil')]}"`
  3. 動力規格(電車)：`attrs="{'invisible': [('energy_type', '!=', 'electric')]}"`
  4. 車身規格（永遠顯示）

### 選單
- 掛載於 `dms_core.menu_dms_root`（DMS 主選單）
- 選單名稱：產品管理，sequence=20

## 安全設定
| id | 模型 | group | R | W | C | D |
|---|---|---|---|---|---|---|
| access_dms_product | dms.product | (全員) | 1 | 1 | 1 | 1 |

## 前端資產
- `dms_product/static/src/js/dms_product_column_limit.js`
  - patch `ListRenderer.prototype.toggleOptionalField`
  - 僅對 `resModel === "dms.product"` 生效
  - 上限 15 欄，超過阻止 + warning + `this.state.columns = [...this.state.columns]`
