# 實作計畫

1. 以扁平搜尋文件取代跨關聯表 OR JOIN。
2. 透過 model signals 同步單筆索引，另提供全量重建指令。
3. 建立 `IdOcrJob`、RQ worker、建立／狀態／失效 API。
4. 將全畫面 OCR 卡屏改為非阻塞狀態及完成通知。
5. 執行單元測試、搜尋效能測試、Docker smoke test 與 T470P 容量檢查。
