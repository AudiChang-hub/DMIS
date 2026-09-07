# Tasks — Django 訂單與營運系統

本清單分成「已存在能力」與「每版重新驗證」。前者表示程式已納入目前 Django 系統；
後者必須針對實際待發布 commit 留下結果，不能因過往版本通過就永久勾選。

## 已存在能力

- [x] Django 專案、資料模型、migration 與行動優先介面
- [x] 訂單草稿、證件附件、OCR、正式建立、修改原因與變更紀錄
- [x] 合約／個資文件列印及簽署附件歸檔
- [x] 庫存建立、唯一識別、配車／改配、位置與車況歷程
- [x] 補助、領牌、交付、取消與全額退款流程
- [x] 訂金／尾款／撥款、對帳、成本、收入、支出與單筆淨利
- [x] 車行傭金、單筆台數與傭金歸屬、台數獎金試算／結算／修正
- [x] 多品牌、能源、指定車型、指定車行及多月份／多季度的台數獎金規則
- [x] 車行獎勵品項、成本版本與依車型／生效期間設定的附加獎勵
- [x] 合作車行、網路平台、本店人員、通路類別、車型／售價及其他主檔
- [x] 每月價格表分發、區域批次分工、例外調整、拖拉站序、電話、導航與備註
- [x] 全欄位搜尋、歷史 Excel 預覽／背景匯入、工作日同步與定位套表
- [x] 每帳號手機快速前往設定
- [x] 登入者系統狀態頁及 superuser-only 系統完整性報告入口
- [ ] LicenseWatcher Ubuntu worker（目前維持人工指定號碼流程）

## 每個發布版本都要重新驗證

發布紀錄至少要填：被測 commit、日期、執行環境、命令、通過／失敗／skip 數、人工驗收
裝置，以及未涵蓋範圍。以下項目只可在該版本實際完成後勾選。

### 自動測試與資料庫

- [ ] `python manage.py check`
- [ ] `python manage.py makemigrations --check --dry-run`
- [ ] `python manage.py test sales --noinput`（完整 SQLite 回歸）
- [ ] 關鍵財務、台數歸屬、台數獎金、結算及鎖定測試在 PostgreSQL 通過
- [ ] `node --test tests/frontend/floating-list.test.cjs tests/frontend/bonus-periods.test.cjs tests/frontend/bonus-model-filter.test.cjs`
- [ ] 實際跑過的測試數與失敗／skip 數已記錄；不得把 test method 總數寫成 coverage 百分比

### 安全與正式映像

- [ ] `python -m pip_audit -r requirements-django.txt`
- [ ] 以安全測試環境變數執行 `python manage.py check --deploy`
- [ ] 建置 `Dockerfile.django`，確認非 root、runtime allowlist、空白 media 與 image 內
      `check --deploy`
- [ ] 以一次性 `postgres:16` volume 執行 `scripts/init_django_db.sh`，確認 app role 可登入、
      只擁有指定 database，且沒有 superuser／createdb／createrole／replication 權限；另以
      admin-owned 既有表複驗 ownership 移交、讀寫與 migration 所需的 `ALTER TABLE`
- [ ] 確認 repo 沒有 `.env`、token、secret、資料庫、客戶媒體、log 或備份被追蹤
- [ ] 記錄 GitHub Code scanning、Secret scanning、Dependabot alerts 是否真的啟用；目前三者
      尚未啟用，不得以本機掃描代稱
- [ ] 正式 compose 展開後 Web 僅監聽 `127.0.0.1:${DJANGO_PORT}`，對外只走 Cloudflare Tunnel

### 核心業務流程

- [ ] 新增訂單：草稿、來源、車主、車型、價格、附件與錯誤回復
- [ ] 已存訂單：修改原因、同時編輯防護、台數與傭金歸屬及搜尋索引更新
- [ ] 配車／改配：唯一鎖定、換車限制、庫存位置與車況歷程
- [ ] 補助／領牌／交付／取消退款：前置條件、文件、期限、狀態鎖定與稽核紀錄
- [ ] 收款／撥款／對帳／營運資料：實收不被預估覆寫、快照、財務刷新與單筆淨利
- [ ] 車行傭金／台數獎金：歸屬車行、規則期間、結算鎖定、調整與避免重複付款
- [ ] 車行附加獎勵：品項、單位、成本版本、車型期間與非現金不自動入帳的邊界
- [ ] 價格表分發：月底建隔月、台鈴電車 only 排除、分工例外、拖拉順序、確認、電話、
      Google Maps、完成與歷史月份唯讀
- [ ] 資料維護：啟用／停用分頁、受引用資料刪除保護、Google Maps 與快速開關
- [ ] OCR、搜尋、歷史匯入與背景 queue 的成功、失敗、重試及不重複寫入
- [ ] 一般帳號無法進入帳號管理與系統完整性報告；管理後台不提供繞過正式流程的寫入入口

## UI／UX 版面與導覽驗收

- [ ] 桌機 `1440×900`：受影響頁面無重疊、裁切、不合理留白或整頁水平捲動
- [ ] 平板 `820×1180`：多欄正確降欄，表單、篩選、下拉選單與操作列不超出容器
- [ ] 手機 `390×844`：底部導覽不遮內容，鍵盤出現後仍能看見欄位與主要動作
- [ ] 網址加入 `?ui_audit=1`，受測頁面的 `data-ui-layout-issues="0"`
- [ ] 下拉選單與搜尋候選不被父層 `overflow`、彈窗或固定操作列裁切
- [ ] 浮動／固定按鈕不遮最後一列、手機導覽或錯誤訊息；不需捲到底才可儲存長表單
- [ ] 拖拉提供清楚把手、儲存狀態與可理解的限制；鍵盤或無法拖拉時有可完成工作的替代路徑
- [ ] 返回入口清楚且可回到合理清單；有未儲存內容時離開前提醒
- [ ] 互動元件觸控範圍至少 `44×44px`，焦點樣式、label、標題層級與對比可辨識
- [ ] 以鍵盤完成主要流程，檢查 focus order、dialog focus、Escape／關閉與錯誤焦點
- [ ] 不移除已確認的證件對照、照片刪除、動態列刪除及必要操作按鈕
- [ ] 實體手機相機、電話、Google Maps、分享，以及實體印表機偏移另行人工驗收

## 文件與管理者報告同步

- [ ] 登入後「使用說明」、`docs/USER_MANUAL.md`、`README.md`、安全文件及相關 spec 與
      實際畫面、路由和規則一致
- [ ] superuser-only「系統完整性報告」列出版本、日期、已執行證據、限制與待人工確認，
      且沒有帳密、token、主機內部資訊、客戶內容或未處理的原始掃描輸出
- [ ] 「系統完整性報告」不把未執行的測試、瀏覽器尺寸或正式部署寫成通過，也不把靜態
      頁面檢查冒充實機 UI／UX 驗收
- [ ] 「系統狀態檢查」明確區分執行中、等待、待命、服務離線；不以工作數呈現人員 KPI

## 正式部署與回復

2026/09/07 修正：Tunnel proxy 使用 Docker DNS 每 5 秒重新解析 web，避免重建容器後
仍連到舊 IP 而持續回傳 502；發布時須同時驗證代理及正式網址。

- [ ] 確認 T470P checkout、branch、乾淨工作樹、遠端 fast-forward 與回復 commit
- [ ] PostgreSQL 與媒體備份成功，且重大 migration／儲存異動已驗證還原方式
- [ ] 部署腳本完成，資料庫、Redis 與同機其他服務未被不必要重啟
- [ ] compose health、背景 workers、本機 `/health/` 及正式網域 `/health/` 正常
- [ ] 以正式登入帳號驗證至少一條受影響的實際流程；容器只有 `Up` 不算完成
- [ ] 部署失敗時依 log 修復或回到前一個已驗證版本，不使用破壞性 Git／Docker 指令繞過
