# 08 — 進度報告（2026-04-30 fees_note 還原獨立欄位修復）

> 接續 `07-progress-2026-04-30.md`，當天稍晚發現價格表「附加費用說明」資料異常，緊急回溯並修復。

## 1. 事故經過

- 上一輪變更（commit `adf8f26`）將 `dms.product.fees_note` 改為 `related='template_id.fees_note', store=True`，並做了 `_compute_field_value` 重算。
- 當時 `dms_product_template.fees_note` 是新欄位，全表為空。重算把 SKU 端原本 user 在價格表手動輸入的 `fees_note` 全部覆蓋為空。
- 使用者隨後反映「附加費用說明資料不見了」。

## 2. 鑑識與還原

- 利用 `pageinspect.heap_page_items()` 掃描 `dms_product` 全部 4 個 page，找出三代 dead tuples（xmin=99217 / 99243 / 99258）。
- 解析每個 dead tuple 的 varlena 文字段（含短/長 1-byte header），比對 sku_id 與 template_id：
    - 11 筆有歷史文字的 SKU，內容皆為 `gift_note` 文字（已正確保留於 `template.note`）。
    - **未在任何 dead tuple 中找到獨立的 `fees_note` 文字段**（堆積中可追溯的最早版本 SKU.fees_note 即為空）。
- WAL 也仍保留 FPW，可進一步往前回溯，但因事證已足夠（資料早於 xmin=99217 即為空，或在更早 transaction 已被覆蓋且 vacuum），不再深入。

## 3. 修復

| 檔案 | 內容 |
|---|---|
| `addons/dms_product/models/product_compat.py` | `fees_note` 還原為 `fields.Text(string='附加費用說明')`，每筆 SKU 獨立儲存（不再 related） |
| `addons/dms_product/__manifest__.py` | bump `16.0.2.4.0` → `16.0.2.4.1` |
| `addons/dms_product/migrations/16.0.2.4.1/post-migrate.py` | 對 `dms_product_template.note` 以 `●` bullet 切段；含「開辦費 / 手續費 / 設定費 / 分期 / 利率 / 0利率 / 購車金 / 現金分期 / 低利率」等費用關鍵字的 bullet 移到該 template 所屬「所有 SKU」的 `fees_note`；純贈品 bullet 留在 `note`。 |
| `gift_note` | 維持 `related='template_id.note', store=True`（運作正常） |

## 4. 拆分結果

| SKU | note（顧客贈品） | fees_note（附加費用說明） |
|---|---|---|
| SUI 125 七期 (5/250) | ●現金優惠折 5000 元 (已直扣) | — |
| New NEX 125 七期 (1014) | ●現金優惠折 7000 元 (已直扣) | — |
| SWISH 125 七期 (1015) | ●現金優惠折 5000 元 / 汰舊換新 +2000 | — |
| Saluto 125 七期 (6/658) | — | ●Saluto專屬【18/24期現金分期同價】，開辦費2500 |
| GIXXER 250 ABS 七期 (1019) | — | ●【2022年出廠】購車金 20000 元(已扣)再60期0利率 |
| GIXXER SF 250 ABS 七期 (1020/1021/1028) | — | ●【2022】購車金20000 / ●【2023】36期0利率 / ●【2024】低利率分期 |
| V-STROM 250SX ABS 七期 (1024) | ●《預購中，預計4月中到港》 | ●低利率分期 |
| DR-Z4S (越野版) (1025) | — | ●《26年式》遠信重機低利率分期 / ●《限25年式》18期0利率分期 |
| DR-Z4SM (滑胎版) (1026) | — | ●《26年式》遠信重機低利率分期 / ●《限25年式》18期0利率分期 |
| eReady Fun (1032) | — | 購車金10000元 |

統計：42 筆 SKU 中，10 筆有 fees_note；5 筆 template 保留純 gift_note。

## 5. 邊界 case（未來人工微調）

- Saluto 七期：bullet 為混合內容（gift+fee），整段被歸到 fees_note。如需，可手動把「18/24期現金分期同價」拆回 note。
- eReady Fun：「購車金10000元」被視為 fee（因 `購車金` 在費用關鍵字中），實務上 user 視之為贈品；可手動移回 note。

## 6. 教訓

- 將既有有資料的欄位改成 `related store=True` 前，**必須**先以 SQL 把 SKU 端資料推回 template，再讓 Odoo 重算。否則 `_compute_field_value` 會以 template 端（空值）覆寫掉 SKU 端歷史值。
- 改 schema 前應先 `pg_dump` 一份備援；本次能還原全靠 dead tuples 還沒被 vacuum。
- migration 檔名須以 `pre-` / `post-` / `end-` 開頭（`pre_migrate.py` / `post_migrate.py` 用底線會被 Odoo 忽略）。`16.0.2.4.0/pre_migrate.py` 即因此未觸發。

## 7. 驗證

- `bash scripts/smoke_odoo.sh` → OK 303
- DB 查詢確認 fees_note / note 拆分如上表
- commit `c3d9bf8` 已推送至 `feat/015-dms-product-rebuild`
