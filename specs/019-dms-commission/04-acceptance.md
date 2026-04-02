# 019-dms-commission 驗收條件（04-acceptance）

## 環境

- `make up` / `docker compose up -d` 一鍵啟動
- `make smoke` / `bash scripts/smoke_odoo.sh` 在 180 秒內回應 200

---

## 傭金規則設定

- [ ] 可新增基礎傭金規則，同一車型只能有一條（重複時系統阻擋）
- [ ] 車行覆蓋規則：`formula_type = base_plus_fixed`，`base + addon` 計算結果正確
- [ ] 車行覆蓋規則：`formula_type = base_times_percent`，`base × percent` 計算結果正確
- [ ] `result_preview` 欄位能即時顯示試算結果
- [ ] 台數獎金規則：可設定 `dealer_ids` 限定車行（空 = 全部）
- [ ] 台數獎金規則：可設定 `energy_type` 限定能源型式（空 = 不分）
- [ ] 台數獎金規則：可設定 `date_from / date_to`，過期規則不觸發

---

## 激勵設定

- [ ] 可新增激勵品項類型（機油、紅包、刮刮卡 等）
- [ ] 激勵觸發規則：`trigger = per_unit` 時，每台結案自動產生 delivery 記錄
- [ ] 激勵觸發規則：`trigger = volume` 時，達到 `min_qty` 後才產生 delivery 記錄
- [ ] `dealer_ids` 空 = 全部車行適用

---

## 結案流程

- [ ] `sale.order` 表單出現「結案」按鈕（`is_closed=False` 時）
- [ ] 點擊「結案」後：`is_closed=True`，`closed_date` 自動填入當時時間
- [ ] 結案後自動產生 `dms.commission.record`（base_commission、total_commission 正確）
- [ ] 結案後依 `dms.incentive.rule` 自動產生 `dms.incentive.delivery`（state=pending）
- [ ] 「撤銷結案」按鈕於 `is_closed=True` 時出現
- [ ] 撤銷結案後：`dms.commission.record.state = voided`，pending 的 delivery 也設為 voided
- [ ] 已 delivered 的 incentive.delivery 撤銷結案後**不被改動**

---

## 台數獎金重算（方案 X）

- [ ] 同車行同月份第 3 台結案後，前 2 台的 `volume_bonus` 自動補算（若規則門檻=3）
- [ ] 撤銷第 2 台結案後，剩 2 台，未達門檻，所有當月 `volume_bonus` 自動清零
- [ ] 規則有 `energy_type` 限制時，不同能源別的訂單不計入台數

---

## 激勵核銷

- [ ] 「激勵核銷」列表可看到所有 pending 記錄
- [ ] 可將 pending → delivered，填寫 `delivery_method`、`delivered_date`
- [ ] 已 delivered 記錄可查看，但不可再改回 pending
- [ ] 月底用「激勵核銷」列表可清楚看到 待給 / 已給 狀態

---

## 報表

- [ ] 月結報表：輸入月份後，列出該月所有結案訂單（車行、車型、訂單號、基礎傭金、台數獎金、合計）
- [ ] 月結報表可匯出 Excel，欄位完整，金額正確
- [ ] 總報表：輸入起迄日期後，可跨月查看
- [ ] 總報表可匯出 Excel

---

## 權限

- [ ] `base.group_user` 可查看傭金記錄與激勵核銷
- [ ] `dms_commission.group_manager` 可設定規則、匯出報表
- [ ] 群組可在 `user_management` 使用者設定頁面中勾選

---

## 技術品質

- [ ] `dms_sale`、`dms_product`、`dms_core` 原始檔案無任何直接修改
- [ ] `make smoke` 通過
- [ ] git commit + push 完成，遠端同步
