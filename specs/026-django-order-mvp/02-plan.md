# Plan — Django 訂單與庫存 MVP

## 架構

- Django 5.1
- PostgreSQL（正式環境）／SQLite（本機快速驗證）
- Django Templates + 原生 CSS/JavaScript
- Docker Compose 部署至 T470P Ubuntu
- 私有媒體檔案由登入後的受控 view 提供，不公開暴露

## 第一個垂直切片

1. 建立 Django 專案與基礎登入。
2. 建立門市、來源、車型、車色、實體庫存與訂單模型。
3. 建立手機優先訂單表單。
4. 建立訂單詳情、合約列印與簽署合約上傳。
5. 建立配車防呆。
6. 建立跨欄位搜尋及首頁待辦。
7. 補模型與流程測試。

