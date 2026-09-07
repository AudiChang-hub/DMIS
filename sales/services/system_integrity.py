"""Versioned, administrator-facing snapshot of the latest DMIS integrity audit.

The page deliberately excludes credentials, host addresses, customer records and
raw scanner output. Detailed evidence remains in CI and the protected release
record; this module provides a durable operational summary for administrators.
"""

from datetime import date
from .restore_drill_status import restore_drill_status


AUDIT_COMPLETED_ON = date(2026, 9, 7)
AUDIT_REVISION = "2026-09-07.1"


def build_system_integrity_report():
    """Return the immutable content for the latest completed audit."""

    return {
        "restore_drill": restore_drill_status(),
        "audit_date": AUDIT_COMPLETED_ON,
        "revision": AUDIT_REVISION,
        "conclusion": (
            "核心訂單、庫存、金流與資料維護流程已有自動回歸保護；歷史財務資料仍有缺漏與狀態差異，"
            "營運報表的收清與淨利數字須完成核對後才能作為完整結算依據。"
            "本次也修正部署邊界、管理後台繞過、搜尋佇列降級與多項介面可及性問題；"
            "但這不代表系統百分之百安全或所有實體設備情境均已涵蓋，仍須依下列限制持續追蹤。"
        ),
        "summary": (
            {
                "label": "安全與權限",
                "status": "已強化",
                "tone": "success",
                "detail": "未發現 runtime 高風險程式弱點；正式網路與資料庫權限已收斂",
            },
            {
                "label": "UI／UX",
                "status": "已修正",
                "tone": "success",
                "detail": "以真實瀏覽器巡覽桌機、平板與手機，並修正本次找到的阻斷問題",
            },
            {
                "label": "營運流程",
                "status": "回歸通過",
                "tone": "success",
                "detail": "完整 Django 測試及主要金流、訂單、主檔情境均納入驗證",
            },
            {
                "label": "仍需追蹤",
                "status": "有已知限制",
                "tone": "warning",
                "detail": "職務權限、實體設備、持續掃描與還原演練尚有明列邊界",
            },
        ),
        "evidence": (
            {
                "label": "Django 自動回歸",
                "value": "完整測試通過",
                "detail": "本版完整套件共 783 項案例：779 項通過、4 項依執行環境條件略過。",
            },
            {
                "label": "前端與瀏覽器",
                "value": "多尺寸巡覽",
                "detail": (
                    "43 個功能頁與登入頁的桌機／手機共 88 個情境、6 套主題；"
                    "平板尺寸另針對關鍵路由複驗。"
                ),
            },
            {
                "label": "弱點掃描",
                "value": "套件與 runtime",
                "detail": (
                    "pip-audit 未找到已知套件弱點；Bandit 對 Git 追蹤的非測試 Python 程式"
                    "未留下高風險結果，runtime 中度提示已人工複核。"
                ),
            },
            {
                "label": "正式環境",
                "value": "備份後強化",
                "detail": "部署前完成可讀備份；服務連接埠、資料庫角色與公開健康檢查均另行驗證。",
            },
        ),
        "sections": (
            {
                "id": "security",
                "title": "弱點與權限檢查",
                "eyebrow": "非破壞性安全稽核",
                "status": "已修正高風險暴露",
                "tone": "success",
                "items": (
                    {
                        "label": "Python 套件",
                        "result": "通過",
                        "tone": "success",
                        "detail": "以公開弱點資料庫比對正式 requirements，未發現已知弱點。",
                    },
                    {
                        "label": "Django runtime 程式",
                        "result": "通過",
                        "tone": "success",
                        "detail": (
                            "靜態掃描未發現高風險項目；行事曆下載的中度提示經人工確認已有 HTTPS、"
                            "網域 allowlist、重新導向檢查、5 MB 上限與 timeout。"
                        ),
                    },
                    {
                        "label": "正式環境網路邊界",
                        "result": "已修正",
                        "tone": "success",
                        "detail": (
                            "Django、舊資料庫與 Metabase 的主機連接埠均改為只綁定 loopback，"
                            "對外僅由既有受控 tunnel 轉送；代理會定期重新解析容器位址，避免服務重建後持續 502。"
                        ),
                    },
                    {
                        "label": "資料庫最小權限",
                        "result": "已強化",
                        "tone": "success",
                        "detail": (
                            "Django runtime 已改用非 superuser 應用角色；舊 Odoo 已停用，"
                            "其既有角色降為唯讀，另保留受保護的維運角色。"
                        ),
                    },
                    {
                        "label": "管理後台異動邊界",
                        "result": "已封鎖繞過",
                        "tone": "success",
                        "detail": (
                            "Django admin 中的 sales 主檔、交易資料及 auth 帳號／群組均僅供查看，"
                            "異動統一由具驗證與稽核的系統頁面執行。"
                        ),
                    },
                    {
                        "label": "文件與個資",
                        "result": "通過既有邊界",
                        "tone": "success",
                        "detail": (
                            "上傳檔案會驗證大小、MIME 與實際內容；私密文件需登入並以 no-store 回傳。"
                            "目前仍採內部互信，職務級物件權限列於已知限制。"
                        ),
                    },
                ),
            },
            {
                "id": "ui-ux",
                "title": "UI／UX 與可及性",
                "eyebrow": "真實瀏覽器與靜態檢查",
                "status": "本次缺陷已修正",
                "tone": "success",
                "items": (
                    {
                        "label": "多尺寸版面",
                        "result": "通過目標尺寸",
                        "tone": "success",
                        "detail": (
                            "桌機 1440 × 900、平板 820／768 寬及手機 390 × 844 的關鍵頁面"
                            "均檢查整頁溢出、內容裁切與固定操作列遮擋。"
                        ),
                    },
                    {
                        "label": "下拉選單與鍵盤",
                        "result": "已修正",
                        "tone": "success",
                        "detail": (
                            "可搜尋下拉選單不再讓隱藏原生欄位重複進入 Tab 順序，"
                            "可視 combobox 保留正確標籤與焦點。"
                        ),
                    },
                    {
                        "label": "表單與日曆語意",
                        "result": "已修正",
                        "tone": "success",
                        "detail": "補齊快速進車欄位標籤，並修正工作日日曆的不完整 ARIA grid 結構。",
                    },
                    {
                        "label": "對比與窄版通路頁",
                        "result": "已修正",
                        "tone": "success",
                        "detail": "改善提示文字與跨月日期對比，通路篩選在 768px 不再超出畫面。",
                    },
                    {
                        "label": "共享浮層與手機操作",
                        "result": "通過",
                        "tone": "success",
                        "detail": "下拉浮層、手機底部導覽、固定儲存列與更多選單均通過互動巡覽。",
                    },
                ),
            },
            {
                "id": "workflows",
                "title": "系統使用與資料一致性",
                "eyebrow": "自動化回歸與交易情境",
                "status": "核心營運流程通過",
                "tone": "success",
                "items": (
                    {
                        "label": "訂單生命週期",
                        "result": "通過",
                        "tone": "success",
                        "detail": "涵蓋建立與修改、草稿、配車／換車、補助、領牌、交付、取消與退款。",
                    },
                    {
                        "label": "金流與財務",
                        "result": "通過",
                        "tone": "success",
                        "detail": (
                            "涵蓋收款、對帳、淨利、結算成本、原廠獎勵、車行傭金、台數歸屬"
                            "與台數獎金；關鍵 transaction 另以 PostgreSQL 驗證。"
                        ),
                    },
                    {
                        "label": "主檔與庫存",
                        "result": "通過",
                        "tone": "success",
                        "detail": (
                            "涵蓋品牌／機種／售價、通路、配件、庫存、獎勵品項、工作日、"
                            "價格表分發與啟停用行為。"
                        ),
                    },
                    {
                        "label": "搜尋佇列故障降級",
                        "result": "已修正",
                        "tone": "success",
                        "detail": (
                            "訂單已提交後若 Redis enqueue 失敗，系統會記錄錯誤並同步重建索引；"
                            "不再讓使用者誤以為訂單儲存失敗而重送。"
                        ),
                    },
                    {
                        "label": "資料庫結構",
                        "result": "通過",
                        "tone": "success",
                        "detail": "Django system check 通過，且沒有尚未建立或未提交的 migration。",
                    },
                ),
            },
            {
                "id": "documentation",
                "title": "說明與維運文件",
                "eyebrow": "與目前 Django 系統同步",
                "status": "本次已更新",
                "tone": "success",
                "items": (
                    {
                        "label": "畫面使用說明",
                        "result": "已更新",
                        "tone": "success",
                        "detail": "新增即時系統狀態、管理者完整性報告及目前限制的解讀方式。",
                    },
                    {
                        "label": "使用者操作手冊",
                        "result": "已更新",
                        "tone": "success",
                        "detail": "同步手機捷徑、價格表分發、台數歸屬與獎金、附加獎勵及管理者操作。",
                    },
                    {
                        "label": "README、CI 與治理文件",
                        "result": "已更新",
                        "tone": "success",
                        "detail": "CI 改驗目前 Django image，並補上驗證命令、部署邊界與舊 Odoo 定位。",
                    },
                ),
            },
        ),
        "limitations": (
            {
                "title": "正式歷史財務資料尚待核對",
                "detail": (
                    "2026/09/07 唯讀盤點 1,744 張訂單：1,720 張缺實際撥款、1,459 張收清狀態"
                    "與逐筆收款不一致、21 張已領牌但成本為零。不同項目可能是同一張訂單；"
                    "包含歷史匯入缺漏，尚未逐張確認原因，沒有自動改寫任何金額。"
                ),
            },
            {
                "title": "歷史程式及規格的適用範圍",
                "detail": (
                    "Odoo 與 Metabase 的部署入口、模組及報表維護工具已退役移除；Git 歷史與舊規格不代表目前功能。"
                ),
            },
            {
                "title": "目前仍採內部互信權限",
                "detail": (
                    "除管理者專用功能外，多數營運頁面尚未依接單、庫存、會計等職務細分；"
                    "已登入人員對私密文件也尚未做物件級權限切割。"
                ),
            },
            {
                "title": "非現金附加獎勵尚未自動入帳",
                "detail": (
                    "機油、輪胎、紅包、禮券與旅遊點數可依車型維護，但目前不會自動形成收支或改變淨利。"
                ),
            },
            {
                "title": "舊報表退役，未來報表須重新設計",
                "detail": (
                    "依管理者決定移除舊 Odoo、Metabase 及其資料源，不沿用舊報表；目前 Django 營運資料維持不變。"
                ),
            },
            {
                "title": "GitHub 代管弱點功能目前未啟用",
                "detail": (
                    "此 repo 的 Code scanning、Secret scanning 與 Dependabot alerts API 目前不可用；"
                    "本次以本機套件、程式及敏感字串掃描替代，尚無持續告警。"
                ),
            },
            {
                "title": "測試不是完整滲透測試或覆蓋率證明",
                "detail": (
                    "未對正式資料做暴力破解、壓力或破壞測試，也尚未建立程式碼 coverage 百分比；"
                    "因此結果只能代表本次測試範圍。"
                ),
            },
            {
                "title": "實體設備與跨瀏覽器仍需人工驗收",
                "detail": (
                    "相機品質、手機分享、Google Maps、電話、實體列印、拖拉手感及不同瀏覽器原生控制項"
                    "無法由本次單一 Chromium 環境完整代表。"
                ),
            },
            {
                "title": "還原演練範圍與限制",
                "detail": (
                    "每週以正式每日備份在隔離容器還原，核對每張表筆數、附件 SHA-256、遷移狀態與 Django 健康檢查。"
                    "實際結果見本頁即時紀錄；不覆寫正式庫，不代表異地主機、DNS 切換或零資料損失演練。"
                ),
            },
        ),
        "method_notes": (
            "弱點掃描不等於永久安全；套件、部署環境或營運流程變更後都應重跑。",
            "此頁是版本化稽核快照；即時服務是否正常請看「系統狀態檢查」。",
            "「目前載入版本」供辨識正在執行的程式，不代表日後版本自動沿用本次稽核結論。",
            "報告刻意不顯示主機位址、密碼、token、客戶內容或原始掃描輸出。",
        ),
    }
