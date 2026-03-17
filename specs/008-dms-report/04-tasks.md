# 04 — Tasks：報表分析模組開發任務

## Sprint 1（本 PR）

- [x] 建立 `addons/dms_report/` 模組骨架
- [x] 建立銷售報表 Pivot + Graph 視圖（`dms.sale.order`）
- [x] 建立利潤報表 Pivot + Graph 視圖（`dms.sale.finance`）
- [x] 建立傭金報表 Pivot 視圖（`dms.sale.order` 篩選 dealer）
- [x] 建立「報表分析」主選單與三個子選單
- [x] 建立 `specs/008-dms-report/` 五份文件

## Sprint 2（下一 PR）

- [ ] 精品報表：以 `dms.sale.order.line` 為資料來源
- [ ] 報表快篩：在搜尋視圖中加入「本月」「本季」快篩按鈕
- [ ] 權限細分：加入 group_id 限制特定角色才可查看報表
- [ ] 儀表板：使用 Odoo 16 Community `board` 模組（若可用）建立首頁儀表板
