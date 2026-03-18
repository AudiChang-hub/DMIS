# 04 — Tasks：拜訪紀錄模組（dms_visit）

## Phase 1：規格與骨架

- [x] 建立 `specs/011-dms-visit/` 完整規格文件（00~05）
- [x] 建立 git 分支 `feat/dms_visit`
- [x] 建立模組目錄結構 `addons/dms_visit/`

## Phase 2：模型

- [ ] `addons/dms_visit/models/visit_purpose.py` — dms.visit.purpose
- [ ] `addons/dms_visit/models/visit_item.py` — dms.visit.item
- [ ] `addons/dms_visit/models/visit.py` — dms.visit（含 state 流轉、computed name、onchange）
- [ ] `addons/dms_visit/models/dealer_visit.py` — dms.dealer 繼承（visit_ids、visit_count、action_open_visits）
- [ ] `addons/dms_visit/models/__init__.py`
- [ ] `addons/dms_visit/__init__.py`
- [ ] `addons/dms_visit/__manifest__.py`

## Phase 3：安全設定

- [ ] `addons/dms_visit/security/dms_visit_security.xml` — 群組定義
- [ ] `addons/dms_visit/security/ir.model.access.csv` — 存取控制
- [ ] `addons/dms_visit/security/record_rules.xml` — Record Rules

## Phase 4：視圖

- [ ] `addons/dms_visit/views/visit_views.xml` — Tree + Form + Calendar + Search + Actions + Menus
- [ ] `addons/dms_visit/views/visit_purpose_views.xml` — 拜訪目的管理視圖
- [ ] `addons/dms_visit/views/dealer_visit_inherit.xml` — Dealer form Smart Button

## Phase 5：測試

- [ ] `addons/dms_visit/tests/__init__.py`
- [ ] `addons/dms_visit/tests/test_visit.py`
  - [ ] test_01：必填欄位驗證
  - [ ] test_02：車行拜訪計數
  - [ ] test_03：送出物品明細
  - [ ] test_04：Record Rule — user 只見自己的拜訪
  - [ ] test_05：Record Rule — admin 可見所有拜訪

## Phase 6：收尾

- [ ] 更新 `docs/erd.md`（新增 dms.visit 相關模型）
- [ ] Commit 1：規格文件
- [ ] Commit 2：模組程式碼
- [ ] Commit 3：測試完成
- [ ] Push 並建立 PR
