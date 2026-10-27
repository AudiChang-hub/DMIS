# 後續優化與擴充規劃（Roadmap Backlog）

> 本文件對應 `output_report/DMIS_後續優化與擴充規劃_v1.docx`，是 DMIS 在六大模組基礎建置完成後，後續可投入的工作項目清單。
>
> **使用方式**：本文件僅作為候選清單（backlog），不代表已排程開工。任一項目要進入開發前，仍須依專案規範於 `specs/NNN-<topic>/` 建立完整 spec（charter、scope、design、test、release）後才可動工。
>
> 撰寫日期：2026-04-30

---

## 0. 規劃原則

- 採「最小可用 → 數據驅動 → 智能輔助」三段式心智模型推進。
- `addons/dms_core/` 為凍結模組，所有擴充以 `_inherit` 或新建獨立模組實作。
- 任一資料結構變更必須附 migration script，並通過 `make smoke`。
- 對外整合一律走 API 中介層，避免 Odoo 直接耦合外部系統。
- 所有後續報表優先使用 Metabase；Odoo 僅做資料維護與快速查詢。

---

## 1. 技術面優化（Tech Backlog）

### 1.1 效能與資料庫
- [ ] PostgreSQL 索引盤點（dms.sale、dms.commission.record、dms.visit），導入 `pg_stat_statements`。
- [ ] 大型資料表分區（partitioning）：`dms.sale`、`dms.audit.log`、`dms.report.*` 依年月分區。
- [ ] 銷售／傭金月報導入 PostgreSQL Materialized View，cron 定時 refresh。
- [ ] Redis 快取層（Odoo session、ir.attachment、Metabase 查詢）。
- [ ] Excel 匯入優化：批次 insert + 暫存表 + 校驗報告。

### 1.2 架構與模組化
- [ ] 對外 API Gateway（FastAPI / Nginx + JWT），統一介接點。
- [ ] 事件驅動：Outbox Pattern + Redis Streams／RabbitMQ。
- [ ] 計算邏輯抽離為獨立服務（傭金、報表規則、虛擬欄位）。
- [ ] Multi-company / 多租戶強化（record rule 與資料隔離測試）。

### 1.3 部署、CI/CD 與監控
- [ ] dev / staging / prod 三層 docker compose；prod 加 read-replica。
- [ ] GitHub Actions：lint → smoke → build → deploy（manual approve to prod）。
- [ ] Prometheus + Grafana + Loki + Sentry 觀測性堆疊。
- [ ] WAL-G 異地備份；RPO ≤ 15min、RTO ≤ 1h 還原演練。
- [ ] Cloudflare Access Policy（OTP / SSO）保護 Odoo / Metabase。

### 1.4 資安與合規
- [ ] PR 觸發 SAST（bandit）+ 相依套件掃描（pip-audit、Trivy）。
- [ ] 敏感資料（身分證、電話）顯示與匯出皆套用遮罩。
- [ ] `user_management.audit.log` 補「變更前後值」欄位。
- [ ] Odoo 接 auth_oauth（Google / Azure AD），管理者群組強制 MFA。
- [ ] 每季自動產出 ACL／record rule 差異報告。

---

## 2. 功能面加強（Feature Backlog）

### 2.1 車行管理（dms_core / dms_visit）
- [ ] 車行健檢儀表板（成交、傭金、回款、訪店頻率彙整 + 異常標紅）。
- [ ] 訪店行程最佳化（地理位置 + 上次訪店日 + 業務日曆 → TSP）。
- [ ] 行動端拍照 + GPS 簽到 + 經緯度水印。
- [ ] 合約／附件版本管理 + 到期提醒 + 電子簽章（DocuSign / TWID）。
- [ ] 車行 A/B/C 級自動評等，連動傭金與供貨優先序。

### 2.2 車銷管理（dms_sale / dms_product）
- [ ] 報價 → 訂單 → 交車三段式流程，狀態同步傭金。
- [ ] 車型組態器（顏色、選配、貸款方案 + PDF 報價）。
- [ ] 庫存／配車模組：與 OEM 串 VIN、預計到車日、配車排程。
- [ ] 二手車收購／媒合（估價工具 + 以舊換新連動）。
- [ ] 信用查詢／徵信整合（聯徵中心或第三方）。
- [ ] 客製化報價樣板（依品牌／車系／活動切換）。

### 2.3 銷售分析（dms_report / dms_report_rule / dms_report_virtual）
- [ ] 銷售漏斗分析（來客 → 試車 → 報價 → 成交）。
- [ ] 車型／顏色／配備熱度圖回饋 OEM。
- [ ] 預測報表（Prophet / ARIMA 區間預測）。
- [ ] 規則引擎拖拉式條件編輯器。
- [ ] 虛擬欄位 SQL 即時試算與錯誤提示。

### 2.4 傭金管理（dms_commission）
- [ ] 業務／主管即時傭金試算器。
- [ ] 多階獎金（個人 / 組長 / 店長 / 區經理）+ 級距獎金。
- [ ] 傭金結算工作流（月結 → 主管覆核 → 財務確認 → 匯款檔）。
- [ ] 個人獎金說明書 PDF + Email 自動發送。
- [ ] 傭金爭議申訴單 + SLA。

### 2.5 零件管理（dms_parts）
- [ ] 庫存即時化 + 安全庫存自動補貨建議。
- [ ] 圖型零件查詢（EPC 點選爆炸圖帶料號）。
- [ ] 通用件交叉表（跨車型／品牌相容料號）。
- [ ] 工時／工單系統雛形（連動客戶車輛保養履歷）。
- [ ] 多供應商比價 + 自動產生採購單。

### 2.6 使用者管理（user_management）
- [ ] 群組權限模板（業務 / 店長 / 財務 / 總部 BI）。
- [ ] 離職／調動工作流（HR 通知 → 自動停權 → 主管確認）。
- [ ] App / Web 雙裝置 session 管理（遠端登出、登入歷史）。
- [ ] 操作行為熱力圖回饋 UI 改版優先序。

---

## 3. 使用者體驗、行動裝置、離線
- [ ] 行動端業務 App（Odoo Mobile / Flutter）覆蓋訪店、報價、簽到、相片、傭金。
- [ ] Offline-first：訪店與報價支援離線暫存 + 上線同步。
- [ ] 語音／OCR 輸入（身分證、行照、訪店摘要）。
- [ ] 通知中心（Web Push / LINE Notify / Email）。
- [ ] 深色模式與大字級。
- [ ] i18n（繁中／英文／越南／印尼）。

---

## 4. ERP / 會計 / 第三方整合
- [ ] 標準化交換格式（JSON Schema / OpenAPI），文件版控於 `specs/`。
- [ ] ERP 對接（鼎新 / SAP / Oracle）：客戶、訂單、發票、應收應付。
- [ ] 電子發票（財政部 B2C / B2B API）。
- [ ] 會計傳票自動化（成交 / 退車 / 傭金）。
- [ ] 金流（信用卡、ATM、街口、Line Pay）回饋付款狀態。
- [ ] OEM EDI / API：配車、保固、召回、零件目錄更新。
- [ ] CRM / 客服整合（LINE OA、線上預約）。
- [ ] HR / 出勤系統雙向同步（請假連動傭金結算）。

---

## 5. BI 與 AI 強化
- [ ] Metabase 高層／區業／OEM 三類儀表板。
- [ ] DW（dms_dw）導入：dbt / Airbyte → PostgreSQL DW（或 ClickHouse）。
- [ ] Star Schema：fact_sale、fact_commission、fact_visit + dim_*。
- [ ] 銷售預測（時間序列）。
- [ ] 流失客戶預測（分類模型）。
- [ ] 最佳促銷組合（Uplift Modeling）。
- [ ] 文件智能化（self-hosted LLM 處理合約 / FAQ / 話術）。
- [ ] 影像辨識（車牌、VIN、行照、駕照、訪店相片防偽）。

---

## 6. 標桿系統參考（功能對照，非採購計畫）

### 國際 DMS
- CDK Global、Reynolds & Reynolds、Dealertrack DMS（Cox）、Tekion ARC、Autoline（Keyloop）

### 中文／亞洲
- 中華汽車 e-DMS、Yamaha／三陽 經銷管理、和泰 T-Connect、中國 4S 店系統（ePlus、車智匯）

### 開源／自託管
- Odoo Enterprise（CRM、Sign、Studio、Documents）
- ERPNext、Frappe Insights、Apache Superset
- Apache Airflow / Dagster、MinIO / S3

---

## 7. 治理建議
- [ ] 月度 Roadmap 評審：PM / IT / 業務 / 財務 共同決定優先序。
- [ ] 每項排程前必先建立 `specs/NNN-<topic>/` 五份規格文件。
- [ ] 對外整合先簽 NDA + API 規格書。
- [ ] AI／資料分析項目需預先設定成功指標。
- [ ] 持續維護 `docs/CHANGELOG.md`、`docs/USER_MANUAL.md`。

---

## 8. 文件交叉參考
- 對應 Word：`output_report/DMIS_後續優化與擴充規劃_v1.docx`
- 產生器：`scripts/build_roadmap_report.py`
- 進度現況：`output_report/DMIS_專案進度報告_v5.docx`
- 主 Checklist：`specs/000-roadmap/02-master-checklist.md`
- 系統願景：`specs/000-roadmap/00-system-vision.md`
