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
