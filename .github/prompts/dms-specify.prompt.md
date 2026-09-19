---
name: dms-specify
description: "整理需求、驗收與未決事項，不改應用程式"
argument-hint: "功能需求或待釐清的問題"
agent: copilot
---

以 [AGENTS](../../AGENTS.md) 為規則來源，讀 [CURRENT_STATE](../../docs/context/CURRENT_STATE.md) 後只查相关文件。
先尋找可更新的 specs；以最小文件記錄範圍、有效規則、非目標、驗收、風險與未決問題。
區分已確認／假設／建議，不把歷史 Odoo 欄位當現行 Django schema。不執行部署、migration 或正式資料異動。
