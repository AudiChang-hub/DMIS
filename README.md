# DMIS｜車輛銷售管理系統

整合選車接待、訂單、配車／領牌／交付、收支與補助、合作車行和報表。
目前狀態與版號見 [CURRENT_STATE](docs/context/CURRENT_STATE.md)，不在多處重複維護。

## 架構

Django 網站與背景 workers，PostgreSQL 保存正式資料、Redis 支援工作佇列。
本機可用 SQLite；正式由 Docker 與 Cloudflare Tunnel 提供服務。
Odoo／Metabase 已退役，歷史文件不能作為啟動指令。

## 本機安裝與啟動

需求：Python 3.12、Node.js（前端測試）及繁中文字型。以下只適用本機測試環境，先確認沒有連到正式資料庫。

```powershell
python -m pip install -r requirements-django.txt
python manage.py migrate
python manage.py seed_demo --username admin --password 請設定測試專用密碼
python manage.py runserver
```

開啟 http://127.0.0.1:8000/ 。由首頁進入建立訂單、全部訂單、營運總表、報表或資料維護；
可見內容依帳號授權。正式環境部署不得使用 demo 指令。

## 文件入口

| 需要什麼 | 文件 |
| --- | --- |
| AI 永久規則與定位 | [AGENTS](AGENTS.md) |
| 當前狀態／續作 | [CURRENT_STATE](docs/context/CURRENT_STATE.md)／[HANDOFF](docs/context/HANDOFF.md) |
| 有效業務規則／決策 | [BUSINESS_RULES](docs/context/BUSINESS_RULES.md)／[DECISIONS](docs/context/DECISIONS.md) |
| 模組定位 | [MODULE_MAP](docs/architecture/MODULE_MAP.md) |
| 開發與驗證 | [DEVELOPMENT](docs/reference/DEVELOPMENT.md) |
| 部署、備份、排程 | [OPERATIONS](docs/reference/OPERATIONS.md) |
| 正式版本與發布 | [RELEASE_POLICY](docs/RELEASE_POLICY.md) |
| Skills／MCP／回復設定 | [AI_TOOL_POLICY](docs/reference/AI_TOOL_POLICY.md) |
| 規格時效／歷史文件 | [specs](specs/README.md)／[archive](docs/archive/README.md) |

只閱讀與當前任務有關的文件。完整驗證清單以 CI 與上述按需文件為準。
