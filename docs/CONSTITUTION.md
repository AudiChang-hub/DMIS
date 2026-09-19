# 專案治理入口

Django 是唯一正式 runtime。為避免多份規則漂移，治理內容已依職責集中：

- [AGENTS](../AGENTS.md)：修改授權、安全邊界、Spec-driven 與交付規則。
- [開發驗證](reference/DEVELOPMENT.md)：最低測試、PostgreSQL 與 UI 驗收。
- [正式維運](reference/OPERATIONS.md)：部署、備份、資料庫角色、健康與還原。
- [發布政策](RELEASE_POLICY.md)：SemVer、版本歷程與 CI 後標籤。

按任務讀取，不要求每次四份全讀。舊版原文在 [歷史治理](archive/2026-09-19/CONSTITUTION.md)，不是額外有效規則。
