PR #9 — 安裝 & 驗證日誌

1) 安裝 `dms_core` 日誌（摘錄）

```
2026-02-26 04:13:40,882 INFO dmis_dev odoo.modules.loading: Loading module dms_core (2/9)
2026-02-26 04:13:41,175 INFO dmis_dev odoo.modules.registry: module dms_core: creating or updating database tables
2026-02-26 04:13:41,175 INFO dmis_dev odoo.modules.loading: loading dms_core/security/dms_security.xml
2026-02-26 04:13:41,208 INFO dmis_dev odoo.modules.loading: loading dms_core/security/ir.model.access.csv
2026-02-26 04:13:41,227 INFO dmis_dev odoo.modules.loading: loading dms_core/views/dealer_views.xml
2026-02-26 04:13:41,305 INFO dmis_dev odoo.modules.loading: loading dms_core/data/seed.xml
2026-02-26 04:13:41,340 INFO dmis_dev odoo.modules.loading: Module dms_core loaded in 0.46s, 312 queries (+312 other)
2026-02-26 04:13:41,481 INFO dmis_dev odoo.modules.registry: Registry loaded in 1.311s
```

註：日誌含數個 DeprecationWarning 與一則關於 wizard 存取規則的建議警告，均為建議性訊息，不會阻止安裝。

2) ir_model_data 查詢結果（確認 XML IDs）

```
-- (摘錄) --
module | name                          | model                 | res_id
---------------------------------------------------------------
dms_core | action_dealer                | ir.actions.act_window | 86
dms_core | action_dealer_columns_wizard | ir.actions.act_window | 85
dms_core | action_dealer_create         | ir.actions.act_window | 87
... (多筆 field/view/group/menu/model 記錄略)
```

結論
- `dms_core` 已在 `dmis_dev` 成功安裝並建立對應的 `ir.model.data` 外部 ID（包括 `action_dealer_columns_wizard`）。
- 我已在此 branch 推送並更新 PR #9，並在本次留言附上安裝日誌與 ir_model_data 查詢結果作為驗證紀錄。

驗證步驟
1. 開啟 Odoo（DB 選擇 `dmis_dev`）
2. 前往 DMS → 車行，點選「欄位選擇」測試 wizard

---
(自動產生的驗證日誌由 agent 附上)