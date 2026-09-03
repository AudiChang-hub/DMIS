# 共用下拉選單層級與回歸驗證

## 規則

- 全站可搜尋單選、複選，以及「最近輸入」建議統一使用 `floating-list.js`。
- 選項必須屬於目前開啟的 dialog；支援 Popover API 時提升至瀏覽器頂層，避免被彈窗、固定操作列或裁切容器遮住。舊版瀏覽器降級為所屬 dialog 內的固定定位。
- 視窗下方空間不足時向上展開，依 visualViewport 調整寬高；不為展開選單捲動整頁。
- 同時只開一份浮動選單。點外部、離開焦點、Tab、關閉彈窗或移除欄位均清理；Escape 優先關選單，不關尚未儲存的彈窗。
- 原生 select、業務欄位、資料儲存及最近輸入的使用者隔離規則不變。

## 全站盤點範圍

`templates/base.html` 統一載入。已檢查 Excel 匯入的車型與通路對應／新增彈窗、車型年份抽屜、分期方案彈窗、訂單、庫存、合作車行與其他資料維護篩選。自製可搜尋選項與最近輸入只有上述兩個共用實作；其他一般選單由瀏覽器原生處理，不以提高 z-index 改動全站卡片。

## 驗證方式

```powershell
node --test tests/frontend/floating-list.test.cjs
python manage.py test sales.tests.test_recent_field_values sales.tests.test_product_experience --noinput
```

瀏覽器驗證：先於 `127.0.0.1:8012` 啟動本機 Django，再執行：

```powershell
python -m http.server 8013 --bind 127.0.0.1 --directory tests/browser
```

開啟 `http://127.0.0.1:8013/floating-lists.html`，按「執行回歸測試」。分別使用桌機及 390×844 手機尺寸確認八項通過，並目視點選測試彈窗。測試使用虛構資料，不呼叫正式儲存路由。測試完成關閉此臨時 HTTP server。

涵蓋裁切容器、原生模態 dialog 頂層、搜尋選取、Escape、多選勾選樣式、最近輸入、關窗清理、無 Popover API 降級與動態移除。幾何單元測試另外涵蓋向上展開、窄視窗、縮放及軟鍵盤可見範圍；手機模擬不能取代實機 iOS 鍵盤測試。
