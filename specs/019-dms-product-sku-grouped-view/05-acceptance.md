# 05 驗收標準

1. 「產品管理 → 車型產品 → SKU 折疊總覽」選單存在且可點擊
2. 開啟後列表預設以產品模板分組，可折疊/展開
3. 展開後可見：內部代碼、年份、顏色、現金售價、牌價、活動特殊價、有效售價
4. 點「開啟」按鈕可彈出 4-Tab SKU dialog
5. 列表本身不允許行內新增/刪除
6. `make smoke` 通過

## 驗證指令
```bash
make up
docker compose ps
bash scripts/smoke_odoo.sh
```
