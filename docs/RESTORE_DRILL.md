# 正式備份還原演練與舊系統退役

## 自動演練

- 每週日 05:00（主機 Asia/Taipei，隨機延遲至多 5 分鐘）執行；漏跑會在開機後補跑。
- 使用 audi 的 systemd user timer，Linger=yes 保證登出後仍可執行。
- 先執行既有正式每日備份，再持備份鎖取得資料庫與媒體鏡像快照。
- PostgreSQL 備份不攜帶原主機 owner/ACL，還原時遇錯立即失敗。
- 在 internal Docker network、無對外埠的 PostgreSQL 16 暫存庫實際還原 SQL。
- 每張資料表筆數對照 dump 同一快照的 COPY 行數，避免正式庫同時新增造成誤判。
- 媒體封存後解壓，逐檔核對 SHA-256；用正式 Django image 檢查 migration、健康路由及 ORM。
- 不載入正式密碼、Vision secret、Redis、Tunnel 或寄信設定；不啟動正式背景工作。
- 完成或失敗均清除本輪 UUID 容器、網路及暫存檔。殘留清理失敗視為演練失敗。
- 摘要保存在 `/srv/dmis-data/dmis-next/restore-drills/latest.json`，僅掛載給 web 唯讀。
- admin 的「系統完整性報告」顯示最近結果；一般帳號回應 403，不可查看摘要。
- 超過 8 天未有結果或執行中超過 1 小時，介面顯示逾期；systemd 失敗可由 journal 查驗。

安裝（audi 帳號）：

```bash
mkdir -p /home/audi/.config/systemd/user
install -m 0644 deployment/systemd/dmis-next-restore-drill.{service,timer} /home/audi/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dmis-next-restore-drill.timer
systemctl --user start dmis-next-restore-drill.service
systemctl --user status dmis-next-restore-drill.service
journalctl --user -u dmis-next-restore-drill.service -n 40
```

停止排程：`systemctl --user disable --now dmis-next-restore-drill.timer`。
手動演練：`python3 scripts/restore_drill.py`。不可以對正式 compose 執行 `down -v`。

## 驗證範圍

這是正式備份的隔離還原，不是覆寫正式資料的演習。資料庫與媒體同步不是跨儲存系統
原子快照，因此不宣稱零 RPO；尚未演練異地主機重建、DNS 切換、外部憑證與實體設備。
媒體雜湊核對只能驗證現有備份檔案，不能證明歷史資料沒有遺失附件。

## 舊系統退役範圍

移除 dmis 專案的 Odoo、PostgreSQL 15、Metabase 及兩個舊 cloudflared 容器，
`dmis_db_data`、`dmis_odoo_data`、`dmis_metabase_data` 三卷及其舊備份。
不動 dmis-next 的 PostgreSQL、媒體、備份、Redis，也不移除 OrderProcessor 的備份。
舊 addons、Odoo Dockerfile、compose、Makefile、啟動排程與報表工具自目前版本刪除。
Git 歷史仍可追溯程式；已刪除的資料庫及舊報表沒有保留還原副本。

目前 Tunnel 的 `odoo:8069` 是既有 Cloudflare ingress 的相容別名，實際服務為 nginx
轉接 Django，沒有 Odoo 程式或資料庫依賴。勿僅因名稱而刪除此正式入口。
雲端 Metabase Tunnel/DNS 設定若仍保留，需另外在 Cloudflare 管理後台刪除；停止舊
connector 不等於已刪除雲端帳戶資源。
