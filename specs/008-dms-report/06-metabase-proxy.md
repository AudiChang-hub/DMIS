# 06 — Metabase 反向代理架構與維護

## 架構概覽

Metabase (v0.60.1.1) 以 Docker 容器運行（`metabase:3000`），透過 Odoo 自訂
Controller (`addons/dms_report_ds/controllers/main.py`) 反向代理至 `/metabase/*`。

```
使用者 → Cloudflare → Odoo:8069 → /metabase/* → metabase:3000
                                   ↑
                            HTML/CSS/JS 改寫
```

### 路由

| 路徑 | auth | 說明 |
|------|------|------|
| `/metabase/<path>` | user | 主反向代理，所有 Metabase 請求經此轉送 |
| `/dms_report_ds/metabase_config` | user (JSON-RPC) | 前端取得 base_url (`/metabase`) |

### HTML 注入

代理回應 `text/html` 時自動：

1. **移除** Metabase 原生 `<base href="/">`
2. **注入** `<base href="/metabase/">` — 讓相對路徑（JS/CSS/API）正確解析
3. **注入** `insertRule()` monkey-patch 腳本 — 攔截 Metabase Emotion CSS-in-JS
   動態注入的 `@font-face` 規則，將 `url("/app/fonts/...")` 改寫為
   `url("/metabase/app/fonts/...")`

### 字體路徑問題（2026-04-17 修復，commit 9ad7780）

**問題**：Metabase 透過 `CSSStyleSheet.insertRule()` 動態注入 `@font-face`
規則（Lato/PT Serif/Merriweather 等字體），URL 為絕對路徑 `/app/fonts/...`。
此路徑經 Cloudflare 時返回 404（Cloudflare 不轉發 `/app/` 路徑至 Odoo）。

**嘗試過但無效的方案**：
- CSS url() rewrite — 字體 URL 不在靜態 CSS 中（在 JS 裡）
- `/app/` 獨立 Odoo 路由 — Cloudflare Tunnel 不轉發 `/app/` 路徑
- JS bundle rewrite — 過於脆弱，可能破壞功能
- 修改 Metabase site-url — 會破壞公開 Dashboard 存取

**最終方案**：monkey-patch `CSSStyleSheet.prototype.insertRule()`，在規則
插入 CSSOM 前將 `/app/fonts/` 替換為 `/metabase/app/fonts/`，走已有的
`/metabase/<path>` 反向代理路由。

### 前端（OWL Component）

`addons/dms_report_ds/static/src/js/metabase_dashboard.js`：
- 透過 JSON-RPC 取得 `base_url`（預設 `/metabase`）
- 以 iframe 載入 `{base_url}/public/dashboard/{uuid}#bordered=false&titled=false`
- 22 個 `ir.actions.client`（`action_mb_p1` ~ `action_mb_p22`）對應 22 個 Dashboard

### 已知無害警告

| 警告 | 原因 | 影響 |
|------|------|------|
| site URL basename "/" ≠ "/metabase/" | Metabase site-url 設為根路徑 | 無（不可改，否則破壞公開 Dashboard） |
| resolveFontSizeToPx: fontSize "12.5px" | Metabase 內部像素計算 | 無 |
| cdn-cgi/rum ERR_ABORTED | Cloudflare RUM 被 ad-blocker 擋 | 無 |

## Metabase 設定

| 設定項 | 值 | 備註 |
|--------|-----|------|
| Site URL | `https://dmis.moto-core.com` | 不可改為 `/metabase`，否則 public dashboard 404 |
| Database | `dmis_dev` (host=db, port=5432) | |
| Collection | SUZUKI銷售統計 (id=5) | 21 個 Dashboard (D2-D21, D23) |
| Dashboard width | `full` | 所有 21 個 Dashboard |

## 驗證指令

```bash
# 服務健康
make up && make smoke

# 字體載入（需登入 session）
SID=$(curl -s -c - 'http://localhost:8069/web/session/authenticate' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","params":{"db":"dmis_dev","login":"admin","password":"admin"}}' \
  | grep session_id | awk '{print $NF}')
curl -s -b "session_id=$SID" -o /dev/null -w "%{http_code}" \
  "http://localhost:8069/metabase/app/fonts/Lato/lato-v16-latin-700.woff2"
# 預期：200

# insertRule patch 注入確認
curl -s -b "session_id=$SID" "http://localhost:8069/metabase/" | \
  grep -o 'CSSStyleSheet.prototype.insertRule' | head -1
# 預期：CSSStyleSheet.prototype.insertRule
```
