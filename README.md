# DMIS

此專案為 Odoo Community 最小專案骨架，包含 docker-compose 一鍵啟動、smoke 測試與規格治理。所有文件皆以繁體中文為主。

快速開始：

1. 複製 `.env.example` 為 `.env` 並調整必要參數。
2. 啟動：

```bash
make up
```

3. 看日誌：

```bash
make logs
```

4. 驗證：

```bash
make smoke
```

開發：新增 module 至 `addons/`，並同步更新 `specs/` 下對應規格檔。

如何安裝 `dms_core` 模組（繁中）：

1. 確保專案已啟動：`make up`。
2. 開啟瀏覽器至 http://localhost:8069，登入 Odoo 後台（或建立管理員帳號）。
3. 進入「應用程式（Apps）」，點選右上角的「更新應用清單」或在開發者模式下按「更新模組清單」。
4. 在搜尋欄輸入「DMS Core」或「經銷商」，找到 `DMS Core` 模組後按安裝。
5. 安裝後可在側邊選單 `DMS -> 經銷商` 瀏覽/建立經銷商。

提示：若在 Apps 找不到模組，請確認 `addons/` 已正確掛載到容器的 `/mnt/extra-addons`，並在 Odoo 的 Apps 頁面中按「更新應用清單」。
