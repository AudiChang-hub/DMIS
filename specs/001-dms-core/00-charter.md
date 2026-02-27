<!--
Charter: DMS Core - 車行（dms.dealer）功能補齊
Author: automated by Copilot
Note: 中文為主，必要時可包含英文說明
-->

# 00 - Charter

本規格目標在於補齊 `dms_core` 模組中「車行（model: dms.dealer）」的完整需求，包括欄位、檢視（list/form/search）、主檔（品牌/車行類型）、權限、示範資料與測試。採 Spec-first 流程，任何變更先更新 specs，再修改程式檔案。

範圍：
- 模型：`dms.dealer` 欄位補齊與行為修正（店名/負責人/店長/同負責人/聯絡資訊/價格表/排車容量/群組/標籤）
- 主檔：`dms.brand`、`dms.store_type`
- 視圖：tree/form(search) 與相關 action/menu
- 安全：ir.model.access.csv 完整設定
- 測試：TransactionCase 單元測試

驗收條件見 05-acceptance.md。
# Charter / 宗旨

This document describes the DMS core module purpose.

宗旨（繁中為主）：

-- 建立車行管理的最小模組示範（Dealer，模型技術名稱維持 `dms.dealer`）。
- 提供範例規格與驗證流程，作為團隊開發守則。
