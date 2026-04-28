#!/usr/bin/env python3
"""依「6 大模組 × 子選單」結構產生 Word 進度報告。"""
import datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

OUT_DIR = Path("/home/audi/project/DMIS/output_report")
SHOTS = OUT_DIR / "screenshots_full"
DOCX = OUT_DIR / "DMIS_專案進度報告_v3.docx"

ZH = "Microsoft JhengHei"
NAVY = RGBColor(0x1F, 0x3A, 0x68)
GRAY = RGBColor(0x55, 0x55, 0x55)


def set_zh(run, size=11, bold=False, color=None):
    run.font.name = ZH
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.makeelement(qn("w:rFonts"), {})
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), ZH)
    rFonts.set(qn("w:hAnsi"), ZH)
    rFonts.set(qn("w:ascii"), ZH)
    run.font.size = Pt(size)
    if bold:
        run.font.bold = True
    if color is not None:
        run.font.color.rgb = color


def add_para(doc, text, size=11, bold=False, color=None, align=None, indent=None):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    if indent is not None:
        p.paragraph_format.left_indent = Inches(indent)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_zh(run, size=size, bold=bold, color=color)
    return p


def add_heading(doc, text, level=1):
    sizes = {0: 26, 1: 20, 2: 15, 3: 13}
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14 if level <= 1 else 8)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    set_zh(run, size=sizes.get(level, 12), bold=True, color=NAVY)


def add_image(doc, name, caption, width_in=6.3):
    path = SHOTS / f"{name}.png"
    if not path.exists():
        add_para(doc, f"[缺圖：{name}]", color=GRAY, align=WD_ALIGN_PARAGRAPH.CENTER)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(path), width=Inches(width_in))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(8)
    set_zh(cap.add_run(f"圖：{caption}"), size=9, color=GRAY)


def add_steps(doc, steps):
    for i, s in enumerate(steps, 1):
        add_para(doc, f"{i}. {s}", size=11, indent=0.2)


def add_kv_table(doc, kv):
    t = doc.add_table(rows=len(kv), cols=2)
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (k, v) in enumerate(kv):
        c0, c1 = t.rows[i].cells
        c0.width = Inches(1.6)
        c1.width = Inches(4.5)
        set_zh(c0.paragraphs[0].add_run(k), size=10, bold=True, color=NAVY)
        set_zh(c1.paragraphs[0].add_run(v), size=10)


def cover(doc):
    for _ in range(3):
        doc.add_paragraph()
    add_para(doc, "DMIS 車輛經銷管理系統", size=30, bold=True, color=NAVY,
             align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "操作手冊與進度報告（v3）", size=18, bold=True, color=NAVY,
             align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()
    add_para(doc, "六大模組｜逐子選單操作說明｜實機畫面", size=13, color=GRAY,
             align=WD_ALIGN_PARAGRAPH.CENTER)
    for _ in range(5):
        doc.add_paragraph()
    add_para(doc, f"產出日期：{datetime.date.today().isoformat()}", size=12,
             align=WD_ALIGN_PARAGRAPH.CENTER, color=GRAY)
    add_para(doc, "技術架構：Odoo 16 Community｜PostgreSQL 15｜Docker Compose", size=11,
             align=WD_ALIGN_PARAGRAPH.CENTER, color=GRAY)
    doc.add_page_break()


def section_overview(doc):
    add_heading(doc, "1. 專案總覽", level=1)
    add_para(doc,
             "DMIS（Dealer Management Information System）為一套服務於汽機車經銷"
             "體系的營運管理平台，整合「車行」、「銷售」、「傭金」、「零件」、"
             "「報表分析」與「使用者權限」六大領域，協助總部與經銷商即時掌握第一線業務脈動。"
             "本報告依實際選單逐一說明六大模組底下每個子選單的用途與操作步驟，"
             "並附上實機截圖以利使用者按圖索驥。", size=11)

    add_heading(doc, "1.1 系統登入", level=2)
    add_steps(doc, [
        "於瀏覽器開啟 http://localhost:8069 進入登入頁。",
        "輸入帳號（預設 admin）、密碼（預設 admin）後按「登入」。",
        "登入後將進入主應用程式列表，點選對應應用即可使用。",
    ])
    add_image(doc, "00_login", "Odoo 登入畫面")
    add_image(doc, "00_apps", "登入後的應用程式列表")

    add_heading(doc, "1.2 環境與技術", level=2)
    add_kv_table(doc, [
        ("ERP 框架", "Odoo 16 Community（容器化部署）"),
        ("資料庫", "PostgreSQL 15"),
        ("部署方式", "Docker Compose（odoo / db / nginx 三服務）"),
        ("自製模組", "dms_core / dms_sale / dms_commission / dms_parts / "
                     "dms_report / user_management 等"),
        ("BI 報表整合", "Metabase 一鍵建表與儀表板自動部署"),
    ])

    add_heading(doc, "1.3 報告涵蓋範圍", level=2)
    add_para(doc, "本報告聚焦六大功能選單，每個子選單均提供「用途說明 + 操作步驟 + 實機畫面」。")
    add_kv_table(doc, [
        ("(2) 車行管理", "車行主檔、品牌、類型、拜訪、行事曆、目的、假日、批次與政府同步"),
        ("(3) 車銷管理", "車型價格表、車輛銷售、銷售分析、Excel 匯入、同步紀錄"),
        ("(4) 銷售分析", "銷售報表、利潤、傭金、自定報表規則、虛擬欄位"),
        ("(5) 傭金管理", "基礎/車行/車種規則、台數獎勵、激勵品項、傭金記錄、核銷、月結"),
        ("(6) 零件管理", "零件主檔、分類、目錄、查詢工具、CSV 匯入"),
        ("(7) 使用者管理系統", "存取群組設定、操作歷程稽核"),
    ])
    doc.add_page_break()


SECTIONS = [
    {
        "title": "2. 車行管理（DMS Core）",
        "intro": "車行管理是 DMIS 的主檔來源，所有銷售、傭金、零件、拜訪都會引用此模組的「車行」為維度。"
                 "底下涵蓋主檔資料、拜訪紀錄與行事曆、節假日設定等實務作業。",
        "items": [
            {"h": "2.1 車行（Dealer）",
             "brief": "管理所有合作經銷商之主檔，包含名稱、編號、地址、聯絡人、品牌與類型。",
             "steps": ["從左上角選單進入「車行管理 → 車行」。",
                       "在清單畫面可使用上方搜尋列以名稱、品牌、城市快速過濾。",
                       "點擊任一列開啟車行表單可檢視/編輯詳細資料；點「建立」可新增車行。",
                       "編輯完成後按「儲存」，異動會自動寫入操作歷程。"],
             "shots": [("11_dealers_list", "車行清單"), ("11_dealers_form", "車行表單")]},
            {"h": "2.2 品牌（Brand）",
             "brief": "維護車行所屬品牌（如 KYMCO、SYM、YAMAHA 等），供主檔下拉選擇。",
             "steps": ["進入「車行管理 → 品牌」。", "點「建立」輸入品牌名稱與顯示順序後儲存。",
                       "品牌資料會在車行、車型、價格表等多處被引用。"],
             "shots": [("12_brands_list", "品牌清單"), ("12_brands_form", "品牌表單")]},
            {"h": "2.3 車行類型（Store Type）",
             "brief": "定義車行型態（如總代理、經銷、加盟、衛星店）；用於分群統計。",
             "steps": ["進入「車行管理 → 車行類型」。",
                       "新增類型並指定編碼，於車行主檔可選擇套用。"],
             "shots": [("13_storetype_list", "車行類型清單"), ("13_storetype_form", "車行類型表單")]},
            {"h": "2.4 拜訪紀錄（Visit）",
             "brief": "業務人員親訪車行時建立的工作紀錄，含日期、目的、結論、附件。",
             "steps": ["進入「車行管理 → 拜訪紀錄」。",
                       "點「建立」開啟新拜訪表單，依序填入車行、日期、拜訪人、目的。",
                       "在「備註」輸入結論與後續事項；可上傳照片或文件。",
                       "送出後會以草稿/完成/取消三狀態流轉，方便主管追蹤。"],
             "shots": [("14_visit_list", "拜訪紀錄清單"), ("14_visit_form", "拜訪紀錄表單")]},
            {"h": "2.5 拜訪行事曆（Calendar）",
             "brief": "以行事曆方式檢視拜訪安排，便於排程與資源調度。",
             "steps": ["進入「車行管理 → 拜訪行事曆」。",
                       "可切換月/週/日視圖；直接點空白格新增拜訪。"],
             "shots": [("15_visit_calendar", "拜訪行事曆視圖")]},
            {"h": "2.6 拜訪目的類別",
             "brief": "標準化拜訪原因（例：例行訪、新品介紹、催收、稽核）。",
             "steps": ["進入「車行管理 → 拜訪目的類別」並建立常用類別。"],
             "shots": [("16_visit_purpose", "拜訪目的類別清單")]},
            {"h": "2.7 台灣假日設定",
             "brief": "存放國定假日與調整工作日，影響拜訪頻次與工作天計算。",
             "steps": ["進入「車行管理 → 台灣假日設定」。",
                       "可手動新增單筆假日，或使用下一節「同步政府假日」批次匯入。"],
             "shots": [("17_holiday_list", "台灣假日清單")]},
            {"h": "2.8 同步政府假日",
             "brief": "從政府開放資料平台一鍵抓取年度假期到本系統。",
             "steps": ["點選「車行管理 → 同步政府假日」開啟精靈。",
                       "選擇要同步的年度，按「執行」即會抓取並寫入。"],
             "shots": [("18_holiday_sync_wizard", "同步政府假日精靈")]},
            {"h": "2.9 批次建立拜訪",
             "brief": "依條件（區域、車行清單、頻率）一次產生多筆拜訪計畫。",
             "steps": ["進入「車行管理 → 批次建立拜訪」精靈。",
                       "選擇車行範圍、預設拜訪人、起訖日期、間隔。",
                       "預覽後確認執行，系統將大量建立草稿拜訪供後續編輯。"],
             "shots": [("19_visit_bulk_wizard", "批次建立拜訪精靈")]},
        ],
    },
    {
        "title": "3. 車銷管理（DMS Sale）",
        "intro": "車銷管理涵蓋價格主檔、銷售單據、Excel 匯入與同步紀錄，是業績與傭金的計算來源。",
        "items": [
            {"h": "3.1 車型價格表（Price Table）",
             "brief": "管理各車型在不同期間/車行的售價、補助、配件含括，供銷售單套用。",
             "steps": ["進入「車銷管理 → 車型價格表」。",
                       "建立或開啟價格表，設定生效區間、品牌、車型與售價。",
                       "可設定多階補助（環保/汰舊/政府）與標配清單。"],
             "shots": [("21_pricetable_list", "車型價格表清單"), ("21_pricetable_form", "車型價格表表單")]},
            {"h": "3.2 車輛銷售（Sale Order）",
             "brief": "經銷商成交時建立的車輛銷售單，是傭金與報表的核心紀錄。",
             "steps": ["進入「車銷管理 → 車輛銷售」。",
                       "點「建立」並選車行、車型、車架/引擎號、客戶資訊、售價。",
                       "系統會根據價格表自動帶入售價與補助；確認後送出狀態流轉。"],
             "shots": [("22_sale_list", "車輛銷售清單"), ("22_sale_form", "車輛銷售表單")]},
            {"h": "3.3 車款銷售分析",
             "brief": "彙整各車款在期間內的銷售數量與金額分布，內建樞紐表/長條圖。",
             "steps": ["進入「車銷管理 → 車款銷售分析」。",
                       "可切換樞紐/圖表視圖並按品牌、車行、月份切片觀察。"],
             "shots": [("23_sale_analysis", "車款銷售分析")]},
            {"h": "3.4 同步紀錄（Sync Log）",
             "brief": "記錄外部系統（如 OrderProcessor）資料同步的成功/失敗紀錄。",
             "steps": ["進入「車銷管理 → 同步紀錄」檢視最新同步結果。",
                       "可開啟單筆查看請求/回應內容，便於除錯。"],
             "shots": [("24_sync_log", "同步紀錄清單")]},
            {"h": "3.5 Excel 銷貨匯入",
             "brief": "支援以 Excel 檔上傳大批銷售單據，系統會驗證並建檔。",
             "steps": ["進入「車銷管理 → Excel 銷貨匯入」精靈。",
                       "下載樣板填寫後上傳；系統預覽資料行並回報錯誤列。",
                       "確認無誤後執行匯入，成功筆數會反映在車輛銷售清單。"],
             "shots": [("25_excel_import", "Excel 銷貨匯入精靈")]},
        ],
    },
    {
        "title": "4. 銷售分析（DMS Report）",
        "intro": "銷售分析提供業績、利潤與傭金等核心指標的多維檢視，並支援自訂報表規則與虛擬欄位擴充。",
        "items": [
            {"h": "4.1 銷售報表（樞紐 / 圖表）",
             "brief": "依品牌、車行、月份、車型多維度檢視銷售台數與金額。",
             "steps": ["進入「銷售分析 → 銷售報表」。",
                       "切換樞紐 / 圖表視圖，左右拖拉欄位調整分析維度。",
                       "可使用搜尋列鎖定區間或品牌後再分析。"],
             "shots": [("31_report_sales_pivot", "銷售報表（樞紐）"), ("31_report_sales_graph", "銷售報表（圖表）")]},
            {"h": "4.2 利潤報表",
             "brief": "結合售價、成本、補助計算每筆交易的毛利與毛利率。",
             "steps": ["進入「銷售分析 → 利潤報表」並選擇期間後產出。"],
             "shots": [("32_report_profit", "利潤報表")]},
            {"h": "4.3 傭金報表",
             "brief": "彙總業務或經銷商在特定期間的傭金總額。",
             "steps": ["進入「銷售分析 → 傭金報表」即可瀏覽。"],
             "shots": [("33_report_commission", "傭金報表")]},
            {"h": "4.4 報表規則（自定）",
             "brief": "可由管理者建立自訂報表規則，定義條件、欄位與產出格式。",
             "steps": ["進入「銷售分析 → 報表規則」。",
                       "點「建立」設定資料來源、過濾條件、輸出欄位。",
                       "儲存後即可在對應選單呼叫產出。"],
             "shots": [("34_report_rule", "報表規則清單")]},
            {"h": "4.5 虛擬欄位",
             "brief": "為報表新增運算欄位（如毛利率、客單價）而不改動資料表。",
             "steps": ["進入「銷售分析 → 虛擬欄位」並建立計算公式。"],
             "shots": [("35_report_virtual", "虛擬欄位清單")]},
        ],
    },
    {
        "title": "5. 傭金管理（DMS Commission）",
        "intro": "傭金管理採「規則 → 結果 → 核銷」的三層模型，支援基礎傭金、車行/車種覆蓋、台數獎勵與多種激勵品。",
        "items": [
            {"h": "5.1 基礎傭金規則（依車型）",
             "brief": "依車型設定每台基礎傭金金額；為傭金計算的最底層規則。",
             "steps": ["進入「傭金管理 → 基礎傭金規則」。",
                       "建立規則並選擇車型、生效區間、傭金金額。",
                       "成交銷售單時系統會自動套用此規則。"],
             "shots": [("41_cm_product_rule", "基礎傭金規則清單"),
                       ("41_cm_product_rule_form", "基礎傭金規則表單")]},
            {"h": "5.2 車行覆蓋規則",
             "brief": "為特定車行客製傭金（疊加或取代基礎金額）。",
             "steps": ["進入「傭金管理 → 車行覆蓋規則」並指定車行 + 加碼/取代金額。"],
             "shots": [("42_cm_dealer_rule", "車行覆蓋規則清單")]},
            {"h": "5.3 車種覆蓋規則",
             "brief": "針對特定車型再加碼，例如新車促銷期間的單車型加碼。",
             "steps": ["進入「傭金管理 → 車種覆蓋規則」設定車型與加碼金額。"],
             "shots": [("43_cm_vehicle_rule", "車種覆蓋規則清單")]},
            {"h": "5.4 台數現金獎勵規則（Volume Rule）",
             "brief": "依當月達成台數階梯給予額外現金獎勵（如 ≥10 台加 1,000/台）。",
             "steps": ["進入「傭金管理 → 台數現金獎勵規則」。",
                       "建立階梯：起點台數、結束台數、單台/總額獎勵。"],
             "shots": [("44_cm_volume_rule", "台數現金獎勵規則清單")]},
            {"h": "5.5 台數實物獎勵規則",
             "brief": "達到指定台數時送出實物（如禮品、零件、提貨券）。",
             "steps": ["進入「傭金管理 → 台數實物獎勵規則」並指定品項與門檻。"],
             "shots": [("45_cm_volume_gift", "台數實物獎勵規則清單")]},
            {"h": "5.6 激勵品項定義",
             "brief": "建立可發放的激勵品（提貨券、零件、配件）主檔。",
             "steps": ["進入「傭金管理 → 激勵品項定義」並建立品項與單位。"],
             "shots": [("46_incentive_type", "激勵品項定義清單")]},
            {"h": "5.7 激勵觸發規則",
             "brief": "定義何種銷售條件觸發何種激勵品（連結銷售單與品項）。",
             "steps": ["進入「傭金管理 → 激勵觸發規則」設定觸發條件、品項、數量。"],
             "shots": [("47_incentive_rule", "激勵觸發規則清單")]},
            {"h": "5.8 傭金記錄（Commission Record）",
             "brief": "系統依規則自動產生的每筆傭金結果，可檢視/結案。",
             "steps": ["進入「傭金管理 → 傭金記錄」。",
                       "篩選車行/月份檢視結果；確認金額無誤後改為「結案」。"],
             "shots": [("48_cm_record", "傭金記錄清單"), ("48_cm_record_form", "傭金記錄表單")]},
            {"h": "5.9 激勵核銷（Incentive Delivery）",
             "brief": "管理實物激勵的給付狀態（待出貨/已出貨/作廢）。",
             "steps": ["進入「傭金管理 → 激勵核銷」。",
                       "選擇待出貨記錄，填入出貨日期、人員、追蹤號後狀態變更。"],
             "shots": [("49_incentive_delivery", "激勵核銷清單"),
                       ("49_incentive_delivery_form", "激勵核銷表單")]},
            {"h": "5.10 月結傭金報表",
             "brief": "依結案月份彙總所有傭金結果，作為對帳/出帳依據。",
             "steps": ["進入「傭金管理 → 月結傭金報表」即可瀏覽。"],
             "shots": [("4a_cm_monthly", "月結傭金報表")]},
            {"h": "5.11 傭金總報表",
             "brief": "跨期間檢視傭金總額並可依車行/業務切片。",
             "steps": ["進入「傭金管理 → 傭金總報表」。"],
             "shots": [("4b_cm_summary", "傭金總報表")]},
        ],
    },
    {
        "title": "6. 零件管理（DMS Parts）",
        "intro": "零件管理涵蓋零件主檔、分類、目錄與批次匯入工具，可同時支撐銷售贈品與激勵品的領用流程。",
        "items": [
            {"h": "6.1 零件清單",
             "brief": "管理所有零件之主檔（品號、名稱、適用車型、單價、庫存）。",
             "steps": ["進入「零件管理 → 零件清單」。",
                       "點「建立」輸入品號、名稱、適用車型、單位、單價後儲存。",
                       "可在搜尋列以品號或名稱快速定位。"],
             "shots": [("51_part_list", "零件清單"), ("51_part_form", "零件表單")]},
            {"h": "6.2 零件分類",
             "brief": "分類維護（傳動、剎車、燈具、保養品 …）便於統計與目錄整理。",
             "steps": ["進入「零件管理 → 零件分類」並建立樹狀分類。"],
             "shots": [("52_part_category", "零件分類")]},
            {"h": "6.3 零件目錄（Catalog）",
             "brief": "依品牌/車型編製零件目錄，支援版本管理與發佈。",
             "steps": ["進入「零件管理 → 零件目錄」。",
                       "建立或開啟目錄；新增明細並關聯零件主檔。"],
             "shots": [("53_catalog_list", "零件目錄清單"), ("53_catalog_form", "零件目錄表單")]},
            {"h": "6.4 零件查詢工具",
             "brief": "供前線人員快速查詢適用零件之精靈。",
             "steps": ["進入「零件管理 → 零件查詢」精靈，輸入車型/年份即顯示適用品。"],
             "shots": [("54_catalog_search_wizard", "零件查詢工具")]},
            {"h": "6.5 CSV 批次匯入",
             "brief": "提供中文表頭、含 UTF-8 BOM 的標準 CSV 樣板（Excel 雙擊不亂碼），一次大量新增/更新零件與目錄明細。",
             "steps": ["進入「零件管理 → CSV 批次匯入」精靈。",
                       "點「下載樣板」按鈕取得『零件目錄匯入樣板.csv』，表頭為：目錄名稱 / 分區代碼 / 分區名稱 / 分區類別 / 序號 / 零件編號 / 零件名稱 / 單位 / 數量 / 建議售價。",
                       "填寫完成後上傳檔案；系統會驗證每筆資料格式並回報。表頭可採中文或英文（catalog_name, section_code…）。",
                       "確認無誤後執行匯入，新增/更新筆數於完成頁顯示。"],
             "shots": [("55_catalog_import_wizard", "CSV 批次匯入精靈（內含「下載樣板」按鈕）")]},
        ],
    },
    {
        "title": "7. 使用者管理系統（User Management）",
        "intro": "使用者管理系統負責功能權限分組以及全系統的操作稽核，是合規與資安的關鍵環節。",
        "items": [
            {"h": "7.1 存取群組管理",
             "brief": "依角色（總部、區主管、業務、經銷商）建立功能/資料權限群組。",
             "steps": ["進入「使用者管理系統 → 存取群組管理」。",
                       "建立群組並勾選可用模組與資料範圍。",
                       "在 Odoo 使用者主檔將其加入相應群組生效。"],
             "shots": [("61_access_group_list", "存取群組清單"),
                       ("61_access_group_form", "存取群組表單")]},
            {"h": "7.2 操作歷程（Audit Log）",
             "brief": "完整記錄系統內 CRUD 動作，包含操作人、時間、模型、舊/新值。",
             "steps": ["進入「使用者管理系統 → 操作歷程」。",
                       "可使用搜尋列鎖定使用者、模型或時段；點開單筆檢視差異內容。"],
             "shots": [("62_audit_log_list", "操作歷程清單"),
                       ("62_audit_log_form", "操作歷程詳細")]},
            {"h": "7.3 介面精簡（隱藏未使用之根選單）",
             "brief": "為簡化日常操作，已透過 user_management 模組將以下選單隱藏："
                      "「討論」「財務結算」「庫存」三個根選單，以及「銷售分析 → 原始數據查詢」子選單。",
             "steps": ["所有隱藏設定統一寫於 addons/user_management/data/hide_menus.xml；",
                       "若日後需重新顯示，將對應 record 的 active 改為 True 並升級 user_management 即可；",
                       "此調整僅影響選單可見性，不刪除任何資料或模組功能。"],
             "shots": []},
        ],
    },
]


def section_module(doc, sec):
    add_heading(doc, sec["title"], level=1)
    add_para(doc, sec["intro"], size=11)
    for item in sec["items"]:
        add_heading(doc, item["h"], level=2)
        add_para(doc, item["brief"], size=11, color=GRAY)
        add_heading(doc, "操作步驟", level=3)
        add_steps(doc, item["steps"])
        add_heading(doc, "畫面截圖", level=3)
        for n, cap in item["shots"]:
            add_image(doc, n, cap)
    doc.add_page_break()


def section_validation(doc):
    add_heading(doc, "8. 驗證與重現步驟", level=1)
    add_para(doc, "使用者可依下列指令於本機重現此報告所有畫面與資料來源：")
    add_kv_table(doc, [
        ("啟動服務", "make up"),
        ("健康檢查", "make smoke 或 bash scripts/smoke_odoo.sh"),
        ("檢視容器", "docker compose ps"),
        ("登入網址", "http://localhost:8069  (帳號 admin / 密碼 admin)"),
        ("重新產報告", "python3 scripts/seed_temp_for_report.py seed → "
                       "python3 scripts/capture_ui_full.py → "
                       "python3 scripts/build_progress_report.py → "
                       "python3 scripts/seed_temp_for_report.py cleanup"),
    ])

    add_heading(doc, "9. 結論", level=1)
    add_para(doc,
             "DMIS 已完成「車行 → 銷售 → 傭金 → 零件 → 報表 → 使用者」六大主軸的端到端能力，"
             "並完整支援 Excel/CSV 大量匯入、多層傭金規則、操作稽核與 BI 整合。"
             "後續將持續優化效能、報表自動化與與外部 OrderProcessor 的雙向同步。")


def main():
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.8)
    sec.bottom_margin = Inches(0.8)
    sec.left_margin = Inches(0.9)
    sec.right_margin = Inches(0.9)

    cover(doc)
    section_overview(doc)
    for s in SECTIONS:
        section_module(doc, s)
    section_validation(doc)

    doc.save(DOCX)
    print(f"DONE -> {DOCX}")


if __name__ == "__main__":
    main()
