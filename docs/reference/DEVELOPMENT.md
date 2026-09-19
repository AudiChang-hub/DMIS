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

- 合併／正式部署前跑完整 Django 測試；財務、佣金、台數歸屬、結算、併發與鎖定須保留 PostgreSQL 測試，不能只用 SQLite。
- 前端測試依受影響 `tests/frontend/*.test.cjs` 執行；完整清單看 CI，不維護另一份易失效列表。
- 依賴變更跑 `python -m pip_audit -r requirements-django.txt`。
- 設定／容器變更跑 `python manage.py check --deploy`、建置 `Dockerfile.django`、檢查 runtime allowlist 與非 root 使用者。只用測試專用 secret 與 DB，CI 不能使用正式密碼。
- migration 檢查使用 `--check --dry-run`；不因為跑測試順便對正式 DB migrate。
- 財務稽核 `python manage.py audit_financial_consistency --sample-limit 30` 是唯讀；仍須確認目標與授權。
- 純文件／AI 設定修改跑 `python -m unittest discover -s tests/context -v` 與 `python scripts/check_release.py`，不需啟動應用或升應用版號。

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
