# Spec 018 — 技術規格

## 模型變更

### dms.product（product_compat.py 擴充）
| 欄位 | 變更 | 說明 |
|------|------|------|
| `color` (Char) | readonly=True，UI 隱藏 | 保留欄位但不再讓使用者手填；改由 color_ids 衍生 |
| `color_code` (Char) | readonly=True，UI 隱藏 | 同上 |
| `color_ids` (O2M) | 已存在 ✅ | 不動 |
| `production_year` | 已存在 ✅ | 不動 |
| `_compute_color_summary` | 新增 | 從 color_ids 彙整顏色名稱 → 寫回 `color` Char（唯讀摘要用） |

### dms.sale.order（sale_order.py）
| 欄位 | 變更 |
|------|------|
| `color_id` | 補 `domain="[('product_id','=',product_id)]"` |

### dms.product.color（product_color.py，dms_product 擴充）
不動。

## 視圖變更

### product_sku_views.xml
- tree：移除 `color` Char 欄，改顯示 `color_ids` 計數
- form：`color` Char 設為 `invisible`；「產品顏色」頁籤已有 `color_ids` ✅

### sale_order_views.xml（dms_sale）
- `color_id` 補 `options="{'no_create': True}"` + domain

## Migration（16.0.2.0.1）
1. **合併同 template + year 的重複 product**：
   - 對 `dms_product` 按 `(template_id, production_year)` 分組，每組保留 id 最小的一筆（master）
   - 把其他筆的 `dms_product_color` records 的 `product_id` 改為 master
   - 把其他筆的 `dms_sale_order.product_id` 改為 master（顏色已有 color_id 對應）
   - 刪除多餘的 product 記錄
2. **補 color 摘要**：呼叫 `_compute_color_summary` 更新所有 product 的 `color` Char

## 版本
`dms_product`：`16.0.2.0.0` → `16.0.2.0.1`
`dms_sale`：維持版本，只改 XML domain（不需 migration）

## 驗證
- `make smoke` HTTP 200
- 查詢：`SELECT template_id, production_year, count(*) FROM dms_product GROUP BY 1,2 HAVING count(*)>1;` → 應為空
- Sale order 選產品後，顏色下拉只顯示該產品的顏色
