from odoo import api, fields, models


_MODULE_LIST = [
    ('dms_core',           'DMS 車行管理'),
    ('dms_customer',       '客戶管理'),
    ('dms_sale',           '銷售管理'),
    ('dms_product',        '產品管理'),
    ('dms_visit',          '拜訪紀錄'),
    ('dms_finance',        '財務結算'),
    ('dms_report',         '銷售 BI 報表'),
    ('dms_report_rule',    '報表規則設定'),
    ('dms_report_virtual', '報表虛擬欄位'),
    ('user_management',    '使用者管理'),
]

_CHANGELOG_HTML = '''
<h5 class="mt-2">2026-04-02</h5>
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


class DmsSystemAbout(models.TransientModel):
    _name = 'dms.system.about'
    _description = '系統版本資訊'

    version_html = fields.Html(string='模組版本', readonly=True, sanitize=False)
    changelog_html = fields.Html(string='版本歷程', readonly=True, sanitize=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'version_html' in fields_list:
            res['version_html'] = self._build_version_html()
        if 'changelog_html' in fields_list:
            res['changelog_html'] = _CHANGELOG_HTML
        return res

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
