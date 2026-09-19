---
name: dms-merge
description: "合併前只讀檢查規格、測試與風險"
argument-hint: "PR 或要檢查的變更範圍"
agent: copilot
---

遵守 [AGENTS](../../AGENTS.md)。只讀目前 diff、相關規格與驗證結果，不遍讀歷史。
依 [DEVELOPMENT](../../docs/reference/DEVELOPMENT.md) 與 [RELEASE_POLICY](../../docs/RELEASE_POLICY.md) 檢查：
範圍／需求、資料相容、授權、安全、測試證據、升版適用性與回復。
區分通過／未驗證／阻擋；本命令不代表授權合併、push、部署或修改正式資料。
