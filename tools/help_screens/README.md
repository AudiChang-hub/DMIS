# 使用說明截圖（T-197）

說明文章在 `sales/help/articles.py`，截圖在 `static/help/screens/`。截圖由這裡的腳本操作真實畫面產生，資料全是合成的。

## 重拍

```bash
python tools/help_screens/run.py              # 全部
python tools/help_screens/run.py reports      # 只拍一組：reports／create_order／mainline／topics／basics／manage
```

需要 Playwright（`pip install playwright`、`python -m playwright install chromium`），和 `tools/tutorials` 共用。

流程：
1. 在 `tmp/help-screens/` 建暫存設定與 SQLite。
2. migrate，再執行 `seed_help_demo --confirm-demo-database`。
3. 啟動示範伺服器 `serve.py`：證件辨識改回傳合成結果，自動裁切照用正式程式。
4. 用隨機密碼登入示範 admin，依 `scenarios/` 的順序操作並截圖。
5. 拍 basics、manage 之前，先執行 `seed_help_demo --manage` 補設定與管理篇的資料（示範業務、示範會計帳號、公告、官網比對、刪除申請），日常篇的畫面與數字不受影響。
6. 改完文章後執行 `python manage.py build_user_manual`，`docs/USER_MANUAL.md` 由文章資料產生，不要直接改。

## 什麼時候要重拍

- 改到文章 `depends` 列出的模板時。
- 腳本報錯停下時，例如「找不到要標註的元件」或「應收不是 $1,400」。這代表畫面或計算變了，對應的文章文字也要跟著改。

## 安全

`seed_help_demo` 在以下情況會直接拒絕：
- 正式環境
- PostgreSQL
- 專案預設的 `db.sqlite3`
- 沒加 `--confirm-demo-database`
- 資料庫裡已有非合成訂單

全部資料都是虛構的：
- 客人：王小明、示範客戶01–33，電話 0900-000- 開頭
- 帳號：admin、示範業務（demo.sales）、示範會計（demo.finance），密碼每次隨機產生
- 公司抬頭：示範機車行（暫存資料庫裡的本店公司資料會被換成合成資料）
- 車行：示範車行甲乙丙
- 引擎號碼：DEMOE 開頭
