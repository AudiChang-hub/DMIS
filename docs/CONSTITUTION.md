# 專案治理規範（CONSTITUTION）

本文件是 DMIS 的變更治理基準。Django 是目前唯一正式 runtime；Odoo、Metabase
與舊報表資料源已退役。歷史規格不得作為重啟舊系統的指示。

## 共同規則

1. 文件、PR 標題／描述與 commit message 以繁體中文為主；技術代號、程式 identifiers
   與第三方名稱可保留英文。
2. 採 spec-driven 流程：需求釐清後先更新對應 `specs/`，再實作、測試、commit、部署
   與驗證。Django runtime、模板、靜態資源、migration、依賴或部署關鍵檔有行為變更時，
   必須同步規格；legacy `addons/**`、`docker-compose.yml` 亦同。
3. 優先小步修改並保留現有資料相容性。涉及資料庫時，必須檢查 migration、舊資料轉換、
   transaction、鎖定、unique／foreign key、可重跑性、備份與 rollback。
4. 不得提交 `.env*`、token、secret、客戶文件、資料庫、log 或備份。敏感資料只能由環境
   變數或唯讀 secret mount 提供。
5. 不得將尚未執行的測試、正式部署或人工驗收寫成「通過」。已知限制、skip、失敗與
   未涵蓋範圍必須在 release／完整性報告中明列。
6. Django admin 只作管理者緊急查詢，所有 model 維持唯讀；正式異動必須使用具備欄位
   驗證、財務連動與稽核紀錄的系統業務頁面。

## Django 變更最低驗證

一般程式變更至少執行：

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test <受影響測試>
```

合併或正式部署前另須執行完整 Django 測試；金流、傭金、台數歸屬、台數獎金、結算、
併發與鎖定異動，必須保留 PostgreSQL 測試。依賴異動須跑 `pip-audit`。設定或容器異動
須跑 `python manage.py check --deploy`、建置 `Dockerfile.django`，並驗證 runtime allowlist
與非 root 使用者。

UI 變更須依 `specs/026-django-order-mvp/04-tasks.md` 以桌機、平板、手機及鍵盤檢查；
template/CSS 字串測試不能冒充真實瀏覽器與實體設備驗收。

## 正式部署完成條件

1. 先確認 T470P 正式 checkout、branch、工作樹、備份與可回復版本。
2. 只使用 `docker-compose.django.yml` 與 `docker-compose.django.prod.yml` 部署 Django；
   不因應用更新任意重啟 PostgreSQL、Redis 或同機其他服務。
3. 正式 Web port 只可綁定 loopback，由 Cloudflare Tunnel 對外提供 HTTPS；token 與
   Google Vision 金鑰不得進入 image 或 repo。
4. Django web 與 workers 必須使用非 superuser 的資料庫 app role；PostgreSQL 管理角色
   只供初始化、維護與備份，其帳密不得提供給 application containers。
5. 部署後必須確認 compose health、背景 workers、本機 `/health/`、正式網域 `/health/`
   與至少一個登入後關鍵流程。只有容器 `Up` 不算完成。
6. migration、儲存路徑或重大財務邏輯異動前必須先備份；高風險異動需有可操作的還原
   步驟，不得以 `docker compose down` 或破壞性 Git 指令處理失敗部署。

## 已退役系統

Odoo 與 Metabase 不得重新接回正式流程。新報表依目前 Django 資料與經確認的營運
規則重建，不沿用已刪除的舊報表資料源。備份演練規範見 `docs/RESTORE_DRILL.md`。

不符合以上規則的變更不得標示完成，並應在合併或部署前補正。
