# 零停機部署（藍綠雙服務，B 方案）

批准：使用者 2026-10-21 選 B「藍綠雙服務」，同意 migration「先擴充、後收斂」規則；web CPU 先不調。

## 問題

每次部署由 compose 先停舊 web 再啟新 web，新容器啟動時才跑 migrate＋collectstatic，之後再強制重建 tunnel-proxy。
實測（10/21 19:09）對外中斷約 13～14 秒，共編 WebSocket 斷兩次、十幾秒才重連；每天部署 8～14 次，多在營業時段。

## 範圍與接受條件

- 正式站有兩個接流量的服務 `web-blue`、`web-green`（沿用 base 的 `web` 設定、不綁 host port）。tunnel-proxy 讀
  `/srv/dmis-data/dmis-next/proxy/active.conf` 決定送往哪一色，沒有該檔時預設 `web-blue`。
- 部署：建置新版 → `check_migration_compat` → 相容就先套用 migration（舊版照常服務，`lock_timeout` 10 秒）→ 閒置的那色
  啟動新版並通過 healthcheck → 改 active.conf 並 `nginx -s reload` → 排空 15 秒後停止（不刪除）舊的那色 → 更新管理容器與背景工作。
- 部署期間每 0.2 秒打一次 `/health/` 不得出現非 200；共編 WebSocket 只斷一次並在約 1 秒內重連。
- 新版起不來：停在切換前、流量留在舊色，部署失敗並保留 log。
- 秒退：`deploy_django.sh --rollback` 以 `docker start` 啟動上一色（保留上一版 image），就緒後切回，不中斷；只切 web 流量。
- 不相容 migration（刪除／改名欄位或資料表、新增沒有 `db_default` 的必填欄位、改成必填、改型別或欄位名、RunSQL）：
  自動改為短暫停機部署（先停舊色再遷移），nginx 在連不到 Django 時回 503「系統更新中」並自動重新整理；log 標明。
  已確認上一版不再使用的收斂 migration 可標 `zero_downtime_safe = True`。CI 對新增 migration 提示警告，不擋合併。
- 正式站 `web` 改為不接流量的管理指令容器（`sleep infinity`），所以 systemd 排程、維運文件的 `compose exec -T web`、
  還原演練取 `dmis-next-web-1` image 都不用改；本機健康入口 19999 改綁 tunnel-proxy。
- 靜態檔改在建置 image 時 collectstatic；`start_django.sh` 只在 `DMIS_RUN_MIGRATIONS=1`（預設，開發用）時 migrate。
- tunnel-proxy 掛整個 `deployment/nginx` 目錄（單檔掛載在 git 更新後看不到新內容）；只有 compose 設定改變才重建，
  重建時先起同 network alias（odoo）的暫代 nginx 接手。
- 部署前備份、發布標籤核對、HTTP/2 connector 與正式網域驗證、不重啟 DB／Redis、不 compose down：全部照舊。

## 過渡（第一次部署）

正式站上的舊 `deploy_django.sh` 不認得藍綠流程，第一次要用 origin/main 的新腳本執行（OPERATIONS「安全部署腳本」）。
新腳本偵測沒有 active.conf 時：新版放 `web-blue` → 起暫代代理 → 停舊 tunnel-proxy → 舊 web 換成管理容器（讓出 19999）
→ 以新設定重建 tunnel-proxy → 移除暫代代理。這一次沒有上一色可秒退。之後腳本若有更新，合併後會自動改用新版繼續。

## 回復

改回單一 web：revert 本版的 compose／nginx／腳本，用新版腳本最後一次部署會把流量留在某一色；改回舊流程前先確認
19999 由誰綁定。資料不受影響（本變更不含 migration）。

## 驗證

- `sales/tests/test_deployment_config.py`、`sales/tests/test_migration_compat.py`。
- 本機 Docker 演練：舊架構 → 藍 → 綠 → 秒退，全程探測 health、未登入 WebSocket 握手與登入後的共編長連線。
- 正式站第一次部署時在主機上跑同一支探測，結果附在交付回報。
