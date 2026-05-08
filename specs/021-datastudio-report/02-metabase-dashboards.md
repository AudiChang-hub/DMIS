# Metabase Dashboard 建置說明

> **對應規格**：`specs/021-datastudio-report/01-datastudio-extraction.md`
> **Metabase URL**：`http://localhost:3000`（Docker profile: metabase）
> **Collection**：SUZUKI銷售統計（id=5）
> **資料來源**：PostgreSQL ds_sales_report SQL View（`addons/dms_report_ds`）

---

## 一、存取方式

| 項目 | 值 |
|------|-----|
| 管理帳號 | `admin@dmis.local` |
| 管理密碼 | `Dmis2026!` |
| 啟動指令 | `docker compose --profile metabase up -d metabase` |
| 停止指令 | `docker compose --profile metabase stop metabase` |
| Health check | `curl http://localhost:3000/api/health` |

---

## 二、Dashboard 總覽（對應 DataStudio 22 頁）

| Dashboard | 對應頁面 | 圖表數 | 圖表類型 |
|-----------|---------|--------|---------|
| P1 總車輛銷售 | P1 | 5 | 2 bar (堆疊) + 2 pie + 1 table |
| P2 銷售機種統計 | P2 | 3 | 2 bar (堆疊) + 1 table |
| P3 電動車銷售統計 | P3 | 4 | 2 bar (堆疊) + 1 pie + 1 table |
| P4 基隆公益青年 | P4 | 2 | 1 bar (堆疊, BrandType) + 1 table |
| P5 電動車-網路平台銷售統計 | P5 | 2 | 1 bar (堆疊) + 1 table |
| P6 電動車-車行銷售統計 | P6 | 2 | 1 bar (堆疊) + 1 table |
| P7 電動車-佣金明細表 | P7 | 2 | 1 summary table + 1 detail table (cross-filter) |
| P8 電動車-台數統計 | P8 | 2 | 1 summary table + 1 detail table (cross-filter) |
| P9 油車銷售統計 | P9 | 4 | 2 bar (堆疊) + 1 pie + 1 table |
| P10 油車-網路平台銷售統計 | P10 | 2 | 1 bar (堆疊) + 1 table |
| P11 油車-車行銷售統計 | P11 | 2 | 1 bar (堆疊) + 1 table |
| P12 油車-佣金明細表 | P12 | 2 | 1 summary table + 1 detail table (cross-filter) |
| P13 油車-台數統計 | P13 | 2 | 1 summary table + 1 detail table (cross-filter) |
| P14 地區×銷量（基隆公益） | P14 | 2 | 1 bar (堆疊) + 1 table |
| P15 區域×車型（基隆公益） | P15 | 2 | 1 bar (堆疊) + 1 table |
| P16 性別×年齡 | P16 | 2 | 1 pie + 1 bar (堆疊) |
| P17 車型X性別 | P17 | 10 | 10 pie (各電動車型×性別) |
| P18 車型X顏色 | P18 | 6 | 6 bar (各車型×顏色) |
| P19 性別X車型顏色 | P19 | 6 | 6 bar (各車型×顏色×性別) |
| P20 通路銷售統計 | P20 | 1 | 1 bar (堆疊) |
| P21 基隆公益青年統計（複本） | P21 | 1 | 1 table |
| P22 客群×車型分析（基隆公益） | P22 | 6 | 6 pie (年齡×性別分群) |

**合計**：22 個 Dashboard、62 個 Question（圖表/表格）

---

## 三、所有 Dashboard 公開連結

已啟用 Public Sharing。所有 Dashboard 可透過公開 URL 存取（不需登入）：

- P1: `/public/dashboard/905078c7-f139-4b6a-8434-ed2b0f6a98b1`
- P2: `/public/dashboard/be4022e0-1435-4b8f-8b05-dbf3fa140b18`
- P3: `/public/dashboard/8cbc7d44-628c-4a70-ba74-7bda1559a8f7`
- P4: `/public/dashboard/8f75637a-1e68-4ff1-b406-2e302b62a547`
- P5: `/public/dashboard/e4a83a40-8712-4f7d-8638-a5fc588029be`
- P6: `/public/dashboard/88bcf37a-64e4-4552-94cc-7cafb7d5a3f1`
- P7: `/public/dashboard/75ae17a4-5deb-40d7-b124-523d14528cda`
- P8: `/public/dashboard/e3192aab-a617-4c93-806e-601786308f20`
- P9: `/public/dashboard/1bb5a0e4-2d15-4d17-91dd-d2ad087fb53a`
- P10: `/public/dashboard/f9ad7c76-eb04-49f4-b3c2-a28ae6a6b5eb`
- P11: `/public/dashboard/508884db-28f6-4dd1-ae52-c89e46fc3577`
- P12: `/public/dashboard/95770575-0aa5-4ef3-8a1d-8699047be9e4`
- P13: `/public/dashboard/23ce259e-c7a5-4f4c-bea5-0e9269af42c7`
- P14: `/public/dashboard/71de9578-68f8-4391-a2cc-ecb08309774a`
- P15: `/public/dashboard/51ae6a82-52ef-47c2-bd2a-78ccf1e3cdf2`
- P16: `/public/dashboard/377904bf-595e-46a1-9a40-debc412ef721`
- P17: `/public/dashboard/5e33871b-5350-4a9d-97a6-2c1fff8cb425`
- P18: `/public/dashboard/76c45736-8322-4b15-b989-3b4e98aca925`
- P19: `/public/dashboard/353bcdf6-de5b-4ca4-8571-f3d2d0800758`
- P20: `/public/dashboard/7afe6e64-0df8-4dc3-a660-7b1d3c66e266`
- P21: `/public/dashboard/cfade0d2-6dbe-4db8-adb6-1bedc4e36560`
- P22: `/public/dashboard/5b8a2815-9ec3-4ca6-b96e-ff5cd2a83ad5`

---

## 四、自動化建置腳本

- `scripts/metabase_setup_dashboards.py` — 可重複執行（需先清除既有資料）
- 使用 Metabase REST API 建立 Question + Dashboard + Public Link
- 所有長條圖啟用 `graph.show_values: true`（資料標籤）
- 所有圓餅圖啟用 `pie.show_data_labels` + `pie.percent_visibility`

---

## 五、Odoo 嵌入（iframe）

已透過 OWL Component 將 22 個 Metabase Dashboard 嵌入 Odoo 選單中。

### 架構

| 檔案 | 說明 |
|------|------|
| `controllers/main.py` | JSON RPC `/dms_report_ds/metabase_config`，回傳 Metabase base URL |
| `static/src/js/metabase_dashboard.js` | OWL Component，讀取 `dashboard_uuid` 參數載入 iframe |
| `static/src/xml/metabase_dashboard.xml` | OWL Template，全高 iframe + loading/error 狀態 |
| `data/metabase_config.xml` | `ir.config_parameter` key=`dms_report_ds.metabase_url`（空值=自動偵測同主機:3000） |
| `views/metabase_actions.xml` | 22 個 `ir.actions.client` + 選單重新組織 |

### 選單結構（銷售分析）

```
銷售分析
├── 總車輛銷售（P1）          ← Metabase iframe
├── 銷售機種統計（P2）
├── 電動車
│   ├── 銷售統計（P3）
│   ├── 網路平台（P5）
│   ├── 車行（P6）
│   ├── 佣金明細（P7）
│   ├── 台數統計（P8）
│   ├── 地區分析
│   │   ├── 地區×銷量（基隆公益）（P14）
│   │   └── 區域×車型（基隆公益）（P15）
│   ├── 客群分析
│       ├── 性別×年齡（P16）
│       ├── 車型×性別（P17）
│       ├── 車型×顏色（P18）
│       ├── 性別×車型顏色（P19）
│       └── 客群×車型分析（基隆公益）（P22）
│   └── 基隆公益青年
│       ├── 總覽（P4）
│       └── 統計表（P21）
├── 油車
│   ├── 銷售統計（P9）
│   ├── 網路平台（P10）
│   ├── 車行（P11）
│   ├── 佣金明細（P12）
│   └── 台數統計（P13）
├── 通路銷售統計（P20）
├── 銷售報表（原 Odoo）
├── 利潤報表（原 Odoo）
├── 傭金報表（原 Odoo）
├── 報表規則（原 Odoo）
├── 虛擬欄位（原 Odoo）
└── 原始數據查詢
    ├── 電動車/油車/車行/網路平台
    ├── 客群/地區/通路/佣金
    └── （Odoo Pivot/Graph/Tree 視圖）
```

### 設定方式

Metabase URL 預設為空（自動偵測 `window.location.hostname:3000`）。若部署環境不同，可在「設定 > 技術 > 系統參數」設定 `dms_report_ds.metabase_url`，例如 `http://metabase.example.com:3000`。

---

## 六、後續工作

- [x] 從 Odoo 嵌入 Metabase Dashboard（iframe OWL Component）
- [ ] motor_type 正規式調整（目前大量資料分類為「其他」）
- [ ] Dashboard filter 連動（領牌日期範圍、銷售來源下拉）
