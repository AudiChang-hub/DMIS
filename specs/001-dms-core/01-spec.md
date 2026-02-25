# 規格（01-spec）

此檔為 DMS Core 的規格文件（繁體中文）。

功能概述：
- 提供 `dealer` 模型，包含名稱、電話與email。

欄位定義（繁體中文）：

- `code`（經銷商代碼）：Char，必填、唯一，用於識別與搜尋。
- `name`（經銷商名稱）：Char，必填，作為主要名稱顯示。
- `level`（經銷層級）：Selection（`總經銷`/`一級`/`二級`/`自營店`），預設 `一級`。
- `active`（啟用）：Boolean，預設 True，用於軟刪除或停用。
- `contact_name`（聯絡人）：Char，可選。
- `phone`（電話）：Char，可選；支援在搜尋欄位以電話搜尋。
- `email`（電子郵件）：Char，可選。
- `address`（地址）：Text，可選。

索引/唯一性：
- `code` 欄位需唯一，透過資料庫約束 (_sql_constraints) 強制。

搜尋需求：
- 支援以 `code`、`name`、`phone` 搜尋。

介面：
- tree、form、search view；選單位置：`DMS` → `經銷商`。
- 在主選單顯示「經銷商」，可查看清單與明細。