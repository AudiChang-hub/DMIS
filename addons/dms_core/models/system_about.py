from odoo import api, fields, models


_MODULE_LIST = [
    ('dms_core',           'DMS 車行管理'),
    ('dms_customer',       '客戶管理'),
    ('dms_sale',           '銷售管理'),
    ('dms_product',        '產品及零件管理'),
    ('dms_parts',          '零件管理（EPC）'),
    ('dms_commission',     '傭金管理'),
    ('dms_visit',          '拜訪紀錄'),
    ('dms_finance',        '財務結算'),
    ('dms_report',         '銷售 BI 報表'),
    ('dms_report_rule',    '報表規則設定'),
    ('dms_report_virtual', '報表虛擬欄位'),
    ('dms_report_ds',      '銷售分析（Metabase）'),
    ('user_management',    '使用者管理'),
]

_CHANGELOG_HTML = '''
<h5 class="mt-2">2026-04-30</h5>
<ul>
  <li>feat(dms_commission)：合併 dms_parts 至產品及零件管理選單；新增車行傭金合約（Plan A）、車行覆蓋規則升級、台數現金/實物獎勵規則、結案/撤銷結案工作流</li>
  <li>feat(dms_commission)：激勵觸發規則列表新增適用車行/限定車種欄位；列表/表單多項版面修正</li>
  <li>feat(dms_sale)：新增 Excel 銷貨資料匯入 Wizard；車行名稱比對加入大小寫不敏感、包含比對與括號附註剝除 fallback</li>
  <li>feat(dms_sale)：OrderProcessor 同步整合（result.json 新格式 + 空檔 fallback 讀 xlsx）；列表新增「重新同步」批次動作與 dms.sync.log UI 重試按鈕</li>
  <li>feat(dms_sale)：新增舊車資訊頁籤、電車資訊頁籤（含密碼遮罩 + 解鎖 wizard）、新增交易類型「網路平台」依車行類型自動帶入</li>
  <li>feat(dms_sale)：訂單複製重置草稿、Kanban/列表 state 標籤更新、新增結案/撤銷結案按鈕與 closed 狀態</li>
  <li>feat(dms_sale)：新增「車款銷售分析」選單與 Pivot/Graph 視圖、product_brand_id 欄位</li>
  <li>feat(dms_product)：新增「產品頁面」獨立 menu/action；產品頁面 / 價格表 tree 新增「開啟詳細資料」按鈕</li>
  <li>feat(dms_product)：新增改為 Wizard 彈窗、禁止 inline 新增；wizard 新增型號欄位、備註欄位上下排列支援換行</li>
  <li>style(dms_product)：價格表標題不截斷、資料列換行、欄寬最佳化；車色／顧客贈品／附加費用說明改完整顯示</li>
  <li>fix(dms_product)：價格表品牌下拉被遮擋；EV0 開頭車型品牌改為台鈴；pricelist_sticky MutationObserver 修復</li>
  <li>feat(dms_report_ds)：銷售分析改用 Metabase iframe 嵌入（Cloudflare tunnel + Odoo 反向代理）</li>
  <li>feat(dms_report_ds)：motor_type / sales_source / sales_type / brand_type 規則重構為動態資料表（dms.motor.type.rule 等），新增單元測試</li>
  <li>feat(dms_report_ds)：新增 motor_type / brand_type 未命中診斷 wizard；報表加「重設」按鈕重載 iframe；啟用 Dashboard titled=true</li>
  <li>fix(dms_report_ds)：修正 EV 開頭車型品牌（宏佳騰→台鈴、e-moving→eReady）；Metabase Lato 字體 404 修復</li>
  <li>feat(dms_parts)：實作 EPC 零件目錄；PDF 自動建立分區與零件清單；wizard 新增分區頁縮圖預覽與樣板下載按鈕</li>
  <li>fix(dms_parts)：PDF 解析多項缺陷修正（換行幽靈列、頁底頁碼過濾、第 6 頁外觀件停用）；CSV 樣板改中文表頭 + UTF-8 BOM</li>
  <li>feat(dms_core)：新增系統版本資訊頁面，所有登入使用者可查看模組版號與版本歷程；模組清單擴充至 13 個</li>
  <li>fix(dms_core)：品牌／車行類型選單限管理員可見；brand tree 圖片用 options size 取代非法 width 屬性</li>
  <li>feat(user_management)：隱藏討論／財務結算／庫存三個根選單；額外隱藏銷售分析下的「原始數據查詢」選單</li>
  <li>fix(dms_customer)：改名車銷管理／價格表，新增車輛銷售子項，隱藏銷售管理／客戶管理頂層</li>
  <li>fix(dms_report_virtual)：金額欄位統一為整數位（台灣貨幣無小數）</li>
  <li>chore：新增「DMIS 後續優化與擴充規劃 v1」交付物與 specs/000-roadmap/04-future-enhancements.md</li>
</ul>
<h5 class="mt-3">2026-04-02</h5>
<ul>
  <li>fix(dms_sale)：訂單顏色欄位禁止直接新建，避免顏色資料被污染（spec 018）</li>
  <li>feat(dms_product)：產品頁面列表新增備註欄位（optional show）</li>
  <li>fix(dms_product)：產品頁面 SKU 列表改用「開啟」按鈕，儲存後立即更新金額</li>
  <li>chore：清除 dms_sale / dms_product 所有過渡期遺留選單代碼（共 13 個）</li>
  <li>fix(dms_product)：異動說明欄位改 store=False+inverse，儲存後自動清空（根本修正）</li>
  <li>fix(dms_product)：修正對話框儲存後疊加新視窗的問題</li>
  <li>feat(dms_product)：對話框儲存後停留不關閉視窗（action_save_and_stay）</li>
  <li>fix(dms_product)：修正 create()/write() 異動說明未清空且 log 未建立</li>
  <li>fix(dms_product)：月付金改用年金現值公式 PMT = PV × r / (1-(1+r)^-n)</li>
  <li>fix(dms_product)：年利率改為百分比輸入（1=1%），加 migration 16.0.2.0.5</li>
  <li>feat(dms_product)：分期方案異動日誌完整追蹤（5 個欄位）</li>
  <li>feat(dms_product)：活動特殊價變動記入價格日誌</li>
  <li>feat(dms_product)：產品項詳細資料改為單一 4-Tab 對話框（定價/分期/顏色/日誌）</li>
</ul>
<h5 class="mt-3">2026-03-27</h5>
<ul>
  <li>feat(015)：重建 dms_product 產品管理模組（模板 / SKU / 價目版本 / 分期規則 / 費用規則）</li>
  <li>feat(016)：新增拜訪批次建立 Wizard，一次建立多筆拜訪紀錄</li>
  <li>feat(015)：價目版本支援複製並帶出價格基準</li>
  <li>feat(015)：產品項快速複製、顏色維護、批次加入流程</li>
  <li>fix(015)：多項 UX 改善（breadcrumb 堆疊、年份格式、代碼重複判斷）</li>
  <li>feat(017)：產品定價簡化 Phase 2-8</li>
  <li>chore(014)：移除舊 dms_product / dms_pricelist / dms_catalog，清理頂層選單</li>
  <li>feat(012)：使用者管理模組（菜單白名單＋群組指派）</li>
  <li>feat(011)：拜訪紀錄模組（行事曆 / 送出物品 / 狀態機）</li>
  <li>feat(010)：報表虛擬欄位 dms_report_virtual（11 AC 全過）</li>
  <li>feat(009)：動態報表規則 dms_report_rule（10 AC 全過）</li>
  <li>feat(008)：銷售 BI 報表 dms_report（Pivot / Graph）</li>
  <li>feat(007)：財務結算 dms_finance（收支明細 / 淨利計算）</li>
  <li>feat(006)：銷售訂單 dms_sale（訂單主檔 / 精品明細 / 牌險費 / 傭金）</li>
  <li>feat(004)：客戶管理 dms_customer（繼承 res.partner / 舊車資訊）</li>
  <li>feat(001)：車行管理 dms_core（車行 / 品牌 / 車行類型 / 種子資料）</li>
</ul>
'''


class DmsSystemAbout(models.Model):
    """系統版本資訊（singleton）。

    使用一般 Model + 固定 singleton record，搭配 form view 以 res_id 開啟，
    breadcrumb 顯示 name 而非 "New"。
    """
    _name = 'dms.system.about'
    _description = '系統版本資訊'
    _rec_name = 'name'

    name = fields.Char(default='系統版本資訊', required=True, readonly=True)
    version_html = fields.Html(string='模組版本', compute='_compute_html', sanitize=False)
    changelog_html = fields.Html(string='版本歷程', compute='_compute_html', sanitize=False)

    def _compute_html(self):
        for rec in self:
            rec.version_html = rec._build_version_html()
            rec.changelog_html = _CHANGELOG_HTML

    @api.model
    def _get_singleton(self):
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({'name': '系統版本資訊'})
        return rec

    @api.model
    def action_open(self):
        rec = self._get_singleton()
        view = self.env.ref('dms_core.view_system_about_form')
        return {
            'type': 'ir.actions.act_window',
            'name': '系統版本資訊',
            'res_model': 'dms.system.about',
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'res_id': rec.id,
            'target': 'current',
        }

    def _build_version_html(self):
        IrModule = self.env['ir.module.module'].sudo()
        rows = ''
        for tech_name, display_name in _MODULE_LIST:
            mod = IrModule.search([('name', '=', tech_name)], limit=1)
            version = mod.latest_version if mod else '—'
            rows += (
                f'<tr>'
                f'<td>{display_name}</td>'
                f'<td><code>{tech_name}</code></td>'
                f'<td><strong>{version}</strong></td>'
                f'</tr>'
            )
        return (
            '<table class="table table-sm table-bordered table-striped">'
            '<thead class="thead-light">'
            '<tr><th>模組名稱</th><th>技術名稱</th><th>已安裝版本</th></tr>'
            '</thead>'
            f'<tbody>{rows}</tbody>'
            '</table>'
        )
