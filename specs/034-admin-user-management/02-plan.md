# 實作計畫

1. 延用 Django `User`，新增一對一安全設定與帳號異動紀錄，避免更換使用者模型造成高風險 migration。
2. 建立 superuser-only views、forms、routes 與資料維護區入口。
3. 加入臨時密碼產生器、首次登入變更密碼 middleware 及工作階段失效機制。
4. 建立桌機列表與手機堆疊式 UI。
5. 自動測試權限、密碼、防呆、稽核與導覽可見性。
6. 完成 Git、T470P migration／部署、正式健康檢查與實際頁面驗證。
