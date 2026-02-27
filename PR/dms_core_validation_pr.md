Title: 修正 view/model 欄位不一致並加入驗證腳本

變更摘要

- 新增 `scripts/validate_views_fields.py`：使用 AST 解析 view 與 model，比對 view 中引用的欄位是否在 model 中定義。
- 新增 Makefile 目標 `validate-views` 與 `ci-checks`，方便本地與 CI 執行檢查。
- 新增文件 `docs/validate_views.md`，包含執行、CI、以及伺服器升級範例步驟。

驗證步驟（PR reviewer）

1. 於 CI 或本地執行：

```bash
make validate-views
```

2. 若通過，於受控環境升級模組（範例）：

```bash
docker compose exec odoo ./odoo-bin -c /etc/odoo/odoo.conf -d dmis_dev -u dms_core
```

3. 驗證 UI 中 `車行` 清單與表單能正常開啟，並無 `Field ... does not exist` 的錯誤。

備註

- 若 CI 需要，請在 pipeline 的適當 stage 呼叫 `make validate-views`。
