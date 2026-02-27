# 實作計畨01-dms-core (03-plan)

## 實作步驟（2026）

1. **更新 specs**：更新全部 5 個 spec 檔案並 commit。
2. **Revamp `dealer.py`**：更新欄位（公告 title/required/type/label）、`name_search`、`create/write` 同負責人防呇。
3. **新增 `brand.py`**：`dms.brand` 模型，包含 `name`(required, unique), `active`。
4. **新增 `store_type.py`**：`dms.store_type` 模型，包含 `name`(required, unique), `active`。
5. **更新 `__init__.py`**：依序 import brand, store_type, dealer。
6. **Revamp `dealer_views.xml`**：4分頁表單、更新清單、搜尋、action（含預設編輯 context）。
7. **新增 `brand_views.xml`**：`dms.brand` tree/form/action/menu。
8. **新增 `store_type_views.xml`**：`dms.store_type` tree/form/action/menu。
9. **更新 `ir.model.access.csv`**：全部開放，新增 `dms.store_type`。
10. **更新 `seed.xml`**：引用新欄位，放個展示資料。
11. **更新 `__manifest__.py`**：將 brand_views.xml, store_type_views.xml 加入 data。
12. **更新測試**：`test_dealer.py` 淫蓋新 Boolean 價格欄位。
13. **升級 + smoke**：`docker compose restart odoo` → CLI upgrade dmis_dev → `make smoke`。