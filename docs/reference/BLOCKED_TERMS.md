# 禁用詞掃描（公開 repo 防護）

repo 是公開的。CI 的「禁用詞掃描」job 擋下把真實客戶、車行、平台、分期公司、人員帳號寫進
repo 或 commit 訊息。本文件不放任何真實名稱。

## CI 怎麼掃

- 清單在 repo secret `BLOCKED_TERMS`，一行一詞，`#` 開頭是註解。
- 只掃本次推送或 PR 新增／修改的行、新增檔案的檔名，以及範圍內的 commit 訊息；既有內容不掃。
- 比對前做 NFKC 正規化與忽略大小寫。中文詞用子字串比對；純英數的詞只比對完整單字。
- 命中時 job 失敗，只印檔名與行號（commit 訊息印 commit 與第幾行），不印命中的詞或該行內容；
  檔名本身含禁用詞時連檔名都不印。
- 找不到 secret：push 到 main、同 repo 的 PR、排程、手動觸發都失敗；fork 的 PR 拿不到
  secret，只警告略過。
- 找不到比較基準（新分支、force push、排程）時只檢查最新一個 commit。
- 腳本：`tools/check_blocked_terms.py`；行為測試（只用假詞）：`tests/tools/`。

## 命中了怎麼辦

1. 本機設定同一份清單後重跑：`BLOCKED_TERMS="$(cat 清單檔)" python tools/check_blocked_terms.py --base <基準 SHA>`。
2. 檔案內容改成假名（例如「王小明」「測試客戶甲」）或通用寫法（「某車行」「分期公司 A」）。
3. 還沒推的 commit 訊息用 `git commit --amend` 或重新提交修正；已經推上 main 的訊息不改寫歷史、
   不 force push，回報 PM 另案處理。

## 清單怎麼建

用 `tools/export_blocked_terms.py` 從正式站唯讀匯出（只做 SELECT）。主機、金鑰、專案目錄由參數或
環境變數 `DMIS_PROD_SSH_HOST`、`DMIS_PROD_SSH_KEY`、`DMIS_PROD_PROJECT_DIR` 提供，不寫進 repo。
在 Git Bash 執行要加 `MSYS_NO_PATHCONV=1`，否則 `/` 開頭的專案目錄會被改寫成 Windows 路徑。

輸出到 repo 外（預設系統暫存資料夾的 `dmis-blocked-terms/`），腳本拒絕寫進 repo：

- `blocked_terms.txt`：整份貼進 secret（GitHub secret 上限 48 KB）。
- `review.md`：每個詞的類別、在目前 repo 出現幾個檔案，以及被排除的詞和原因。
- `exclude.txt`、`include.txt`（選用，同一資料夾）：人工排除／一定要收的詞。

規則：

- **收**：客戶姓名（車主、舊車主）、車行與網路平台名稱、本店來源名稱、通路聯絡人與負責人、
  分期公司、人員帳號與姓名。
- **不收**：
  - 本店門市與開單公司名稱：系統本身的身分，程式與文件到處都有。
  - 一般詞：例如「安全」「展場」「朋友推薦」「本人」「待確認」，以及台灣縣市區名。
  - 中文少於 2 字；英文少於 4 字或常見英文字（例如 `admin`、`audi`、`test`）；純數字與電話。
  - 目前 repo 已出現在 20 個以上檔案的詞：先排除並列進 `review.md`，人工確認是一般詞還是
    該收的名稱，要收就寫進 `include.txt`。
- **剛好是一般詞的店名**（某車行就叫某個常用詞）放 `exclude.txt`，不要寫進 repo 的程式或文件，
  以免 repo 反過來透露名單。

更新流程：新增大量車行或客戶後重新匯出 → 看 `review.md` → 由 PM 經使用者同意後更新 secret →
刪除暫存資料夾。
