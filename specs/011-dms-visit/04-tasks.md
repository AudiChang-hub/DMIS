# 04 — Tasks：拜訪紀錄模組（dms_visit）

## Phase 1：規格與骨架

- [x] 建立 `specs/011-dms-visit/` 完整規格文件（00~05）
- [x] 建立 git 分支 `feat/dms_visit`
- [x] 建立模組目錄結構 `addons/dms_visit/`

## Phase 2：模型

- [x] `addons/dms_visit/models/visit_purpose.py` — dms.visit.purpose
- [x] `addons/dms_visit/models/visit_item.py` — dms.visit.item
- [x] `addons/dms_visit/models/visit.py` — dms.visit（含 state 流轉、computed name、onchange）
- [x] `addons/dms_visit/models/dealer_visit.py` — dms.dealer 繼承（visit_ids、visit_count、action_open_visits）
- [x] `addons/dms_visit/models/__init__.py`
- [x] `addons/dms_visit/__init__.py`
- [x] `addons/dms_visit/__manifest__.py`

## Phase 3：安全設定

- [x] `addons/dms_visit/security/dms_visit_security.xml` — 群組定義
- [x] `addons/dms_visit/security/ir.model.access.csv` — 存取控制
- [x] `addons/dms_visit/security/record_rules.xml` — Record Rules

## Phase 4：視圖

- [x] `addons/dms_visit/views/visit_views.xml` — Tree + Form + Calendar + Search + Actions + Menus
- [x] `addons/dms_visit/views/visit_purpose_views.xml` — 拜訪目的管理視圖
- [x] `addons/dms_visit/views/dealer_visit_inherit.xml` — Dealer form Smart Button

## Phase 5：測試

- [x] `addons/dms_visit/tests/__init__.py`
- [x] `addons/dms_visit/tests/test_visit.py`
  - [x] test_01：必填欄位驗證
  - [x] test_02：車行拜訪計數
  - [x] test_03：送出物品明細
  - [x] test_04：Record Rule — user 只見自己的拜訪
  - [x] test_05：Record Rule — admin 可見所有拜訪

## Phase 6：收尾

- [x] 更新 `docs/erd.md`（新增 dms.visit 相關模型）
- [x] Commit 1：規格文件
- [x] Commit 2：模組程式碼
- [x] Commit 3：測試完成
- [x] Push 並建立 PR
