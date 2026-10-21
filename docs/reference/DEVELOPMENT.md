# 開發與驗證（按需）

安裝與啟動見 [README](../../README.md)。本檔只管測試，不重複商業規則。
目前測試清單以 [.github/workflows/ci.yml](../../.github/workflows/ci.yml) 為準。

## 最低驗證

只做初始定位：`python tools/context_lookup.py catalog` 或 `python tools/context_lookup.py importer`。
它只讀三個指定檔案、輸出命中規則與函式，沒有 DB／網路操作；路由過時或輸出過大會報錯，不退回全站掃描。

一般程式異動：

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test <受影響測試> --noinput
```

- 合併／正式部署前跑完整 Django 測試：`python manage.py test sales --noinput --parallel auto --exclude-tag migration`；財務、佣金、台數歸屬、結算、併發與鎖定須保留 PostgreSQL 測試，不能只用 SQLite。
- 驗證資料轉換的 migration 測試標記 `@tag("migration")`，每個要倒退重跑上百個 migration（單個 1–2 分鐘），預設排除。新增或修改 migration、或改到 migration 引用的服務時才跑 `--tag migration`；CI 依變更範圍自動執行，另每週日完整補跑。
- 測試套件（`sales/tests/__init__.py`）改用 MD5 密碼雜湊，只影響測試；正式環境仍為 PBKDF2。
- 讀取 `docs/USER_MANUAL.md` 的測試標記 `@tag("docs")`；只改文件時 CI 只跑版本／context 檢查與這些測試，不重跑整套 Django 測試。
- 前端測試依受影響 `tests/frontend/*.test.cjs` 執行；完整清單看 CI，不維護另一份易失效列表。
- 依賴變更跑 `python -m pip_audit -r requirements-django.txt`。
- 設定／容器變更跑 `python manage.py check --deploy`、建置 `Dockerfile.django`、檢查 runtime allowlist 與非 root 使用者。只用測試專用 secret 與 DB，CI 不能使用正式密碼。
- migration 檢查使用 `--check --dry-run`；不因為跑測試順便對正式 DB migrate。
- 財務稽核 `python manage.py audit_financial_consistency --sample-limit 30` 是唯讀；仍須確認目標與授權。
- 純文件／AI 設定修改跑 `python -m unittest discover -s tests/context -v` 與 `python scripts/check_release.py`，不需啟動應用或升應用版號。

## Migration：先擴充、後收斂（2026-10-21 使用者同意）

正式站採藍綠部署：先套用 migration、新版就緒才切換，這幾秒舊版仍在讀寫資料庫。所以 migration 必須讓**上一版程式**照常運作：

- 可以直接做：新增資料表、索引、約束；新增可空（`null=True`）或有 `db_default` 的欄位；放寬欄位（改成可空、加長、改選項文字或說明）；RunPython 資料修正。
- 新增必填欄位一律加 `db_default`（例如 `CharField(blank=True, default="", db_default="")`），只有 `default` 的話舊版新增資料會失敗。
- 刪除／改名欄位或資料表要拆兩版：第一版程式不再使用，model 用 `SeparateDatabaseAndState` 只移除狀態（必填欄位同時在資料庫改成可空或補 `db_default`）；下一版才真正刪除，並在該 Migration 類別加 `zero_downtime_safe = True` 表示已確認上一版不再使用。改名＝新增新欄位、回填、改用新欄位，下一版刪舊欄位。
- 檢查：`python manage.py check_migration_compat sales.<migration 名稱>`（不指定時查資料庫尚未套用的）。CI 對新增的 migration 自動檢查並標出警告。
- 違反時不會出錯：部署腳本偵測到不相容 migration，自動改用短暫停機部署（先停舊版再遷移，使用者看到約 15～20 秒「系統更新中」），並在部署紀錄標明。能拆兩版就拆，不把降級當常態。

## UI 驗收

桌機 1440×900、平板 820×1180、手機 390×844；網址加 `?ui_audit=1` 時檢查根元素 `data-ui-layout-issues=0`。
檢查鍵盤焦點、選單、彈窗、固定操作列、拖拉替代操作與放大；驗收見 [026 tasks](../../specs/026-django-order-mvp/04-tasks.md)。
模板字串與 CSS 靜態測試不等於瀏覽器／實體手機、相機、分享、印表機驗收。

## 規格與發布

runtime／部署行為變更更新相符 specs，保留舊資料相容性、交易、鎖定、唯一鍵、FK、可重跑及回復策略。
升版、不可變更的已發布歷程與 CI 後標籤依 [RELEASE_POLICY](../RELEASE_POLICY.md)。
如實列出未跑、skip 與失敗，不能把「準備執行」寫成通過。代管安全掃描是否啟用需即時查證，不能以本機稽核替代。

## 已知限制的查證

舊 README 提及附加獎勵的庫存／應付款連動與 LicenseWatcher worker 限制，尚未在此次文件整理重新驗證；
處理相關需求時以服務實作與實際部署核對，不把舊描述當成現況。原文保留於封存快照。
