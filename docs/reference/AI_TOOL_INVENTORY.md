# Skills 與 MCP 盤點（Warm，只在工具維護時讀）

核對日期：2026-09-19。磁碟快取、新 CLI 掃描、桌面本輪注入是三種不同範圍，不相加當作有效工具數。
本機磁碟找到 39 份 SKILL.md；調整後新 CLI skills/list 列出 12 份且無載入錯誤。桌面／遠端服務額外注入者不保證能用本地設定完全移除。

## Skill 清單

大小為 UTF-8 bytes；R/S 是 references/scripts 檔案數。default 表示未宣告 implicit policy，不代表每次要讀完整內容。
無需常駐載入全文的 Core Skill：一般 Django 開發直接用檔案／shell／Git。

| 名稱 | 分級與用途判斷 | bytes | R/S | implicit |
| --- | --- | ---: | --- | --- |
| imagegen | Rare；仅對應工具／技能／影像需求；review-agent 已為 explicit-only | 19516 | 5/2 | default |
| openai-docs | On Demand；僅 OpenAI／Codex 問題，不用於一般 Django bug | 5475 | 9/3 | default |
| plugin-creator | Rare；仅對應工具／技能／影像需求；review-agent 已為 explicit-only | 11716 | 2/5 | default |
| review-agent | Rare；仅對應工具／技能／影像需求；review-agent 已為 explicit-only | 2718 | 0/0 | false |
| skill-creator | Rare；仅對應工具／技能／影像需求；review-agent 已為 explicit-only | 15540 | 1/3 | default |
| skill-installer | Rare；仅對應工具／技能／影像需求；review-agent 已為 explicit-only | 3425 | 0/3 | default |
| computer-use | On Demand；只有 UI 操作；不因除錯就開瀏覽器 | 1497 | 0/0 | default |
| visualize | Disable（本專案）；已停用插件；其他專案全域可用，需求改變時再啟用 | 32281 | 0/1 | default |
| gh-address-comments | On Demand；快取不代表目前暴露；只限 GitHub 任務，yeet 需明確發布請求 | 3580 | 0/1 | default |
| gh-fix-ci | On Demand；快取不代表目前暴露；只限 GitHub 任務，yeet 需明確發布請求 | 4407 | 0/1 | default |
| github | On Demand；快取不代表目前暴露；只限 GitHub 任務，yeet 需明確發布請求 | 4430 | 0/0 | default |
| yeet | On Demand；快取不代表目前暴露；只限 GitHub 任務，yeet 需明確發布請求 | 4089 | 0/0 | default |
| artifact-template-analytics-dashboard | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1497 | 0/0 | false |
| artifact-template-business-review | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1475 | 0/0 | false |
| artifact-template-design-report | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1437 | 0/0 | false |
| artifact-template-experiment-analysis | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1456 | 0/0 | false |
| artifact-template-financial-budget | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1486 | 0/0 | false |
| artifact-template-investment-committee-memo | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1496 | 0/0 | false |
| artifact-template-legal-memorandum | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1434 | 0/0 | false |
| artifact-template-market-trends-report | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1498 | 0/0 | false |
| artifact-template-minimal-letterhead | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1470 | 0/0 | false |
| artifact-template-operating-calendar | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1500 | 0/0 | false |
| artifact-template-operating-review | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1483 | 0/0 | false |
| artifact-template-project-kickoff | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1463 | 0/0 | false |
| artifact-template-project-tracker | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1484 | 0/0 | false |
| artifact-template-sales-pipeline | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1482 | 0/0 | false |
| artifact-template-simple-dark-mode | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1478 | 0/0 | false |
| artifact-template-simple-light-mode | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1487 | 0/0 | false |
| artifact-template-strategy-memorandum | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1446 | 0/0 | false |
| artifact-template-system-design | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1445 | 0/0 | false |
| artifact-template-team-alignment | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1473 | 0/0 | false |
| artifact-template-three-statement-forecast | Rare；未列入新 CLI skill 清單；模板明確指定才載入 | 1552 | 0/0 | false |
| plugin-management | Rare；仅對應工具／技能／影像需求；review-agent 已為 explicit-only | 2983 | 0/0 | default |
| documents | On Demand；Office／PDF 任務保留；Excel 匯入程式 bug 不等於製作試算表 | 42053 | 1/36 | default |
| pdf | On Demand；Office／PDF 任務保留；Excel 匯入程式 bug 不等於製作試算表 | 8076 | 0/0 | default |
| Presentations | On Demand；Office／PDF 任務保留；Excel 匯入程式 bug 不等於製作試算表 | 28828 | 7/0 | default |
| excel-live-control | On Demand；Office／PDF 任務保留；Excel 匯入程式 bug 不等於製作試算表 | 72132 | 2/0 | default |
| Spreadsheets | On Demand；Office／PDF 任務保留；Excel 匯入程式 bug 不等於製作試算表 | 65182 | 3/0 | default |
| template-creator | Disable（本專案）；已停用插件；其他專案全域可用，需求改變時再啟用 | 19242 | 0/1 | true |

### 原始 description（僅稽核用途，非啟動指令）

- **imagegen**：Generate or edit raster images when the task benefits from AI-created bitmap visuals such as photos, illustrations, textures, sprites, mockups, or transparent-background cutouts. Use when Codex should create a brand-new image, transform an existing image, or derive visual variants from references, and the output should be a bitmap asset rather than repo-native code or vector. Do not use when the task is better handled by editing existing SVG/vector/code-native assets, extending an established icon or logo system, or building the visual directly in HTML/CSS/canvas.
- **openai-docs**：Use for Codex models/pricing, scheduled tasks, skills, settings, setup, troubleshooting, customization, automations, and self-knowledge—including 'you,' 'your,' 'this app,' or 'this coding agent' when they refer to Codex—and for OpenAI APIs/products and ChatGPT Work. Also use for model choice/migration, prompting, SDKs, Responses, Realtime, agents, evals, and Chat/Work/Codex comparisons. Do not use for generic app/software tasks that merely mention Codex.
- **plugin-creator**：Create and scaffold plugin directories for Codex with a required `.codex-plugin/plugin.json`, optional plugin folders/files, valid manifest defaults, and personal-marketplace entries by default. Use when Codex needs to create a new personal plugin, add optional plugin structure, generate or update marketplace entries for plugin ordering and availability metadata, or update an existing local plugin during development with the CLI-driven cachebuster and reinstall flow.
- **review-agent**：Perform a read-only, defect-first review of a specified code change and return every actionable finding. Use when another agent delegates review of uncommitted changes, a base-branch diff, a commit, or custom review instructions.
- **skill-creator**：Create or update a Codex skill with appropriately scoped instructions and any needed supporting resources.
- **skill-installer**：Install Codex skills into $CODEX_HOME/skills from a curated list or a GitHub repo path. Use when a user asks to list installable skills, install a curated skill, or install a skill from another repo (including private repos).
- **computer-use**：Control Windows apps from ChatGPT
- **visualize**：Create visualizations and interactive tools directly in conversation. Proactively use to show how something works; explore 'what happens when', 'what changes', or 'help me understand'; compare or inspect; create simulations, maps, charts, graphs, and mockups. Use standard tools for static scientific figures.
- **gh-address-comments**：Address actionable GitHub pull request review feedback. Use when the user wants to inspect unresolved review threads, requested changes, or inline review comments on a PR, then implement selected fixes. Use the GitHub app for PR metadata and flat comment reads, and use the bundled GraphQL script via `gh` whenever thread-level state, resolution status, or inline review context matters.
- **gh-fix-ci**：Use when a user asks to debug or fix failing GitHub PR checks that run in GitHub Actions. Use the GitHub app from this plugin for PR metadata and patch context, and use `gh` for Actions check and log inspection before implementing any approved fix.
- **github**：Triage and orient GitHub repository, pull request, and issue work through the connected GitHub app. Use when the user asks for general GitHub help, wants PR or issue summaries, or needs repository context before choosing a more specific GitHub workflow.
- **yeet**：Publish local changes to GitHub by confirming scope, committing intentionally, pushing the branch, and opening a draft PR through the GitHub app from this plugin, with `gh` used only as a fallback where connector coverage is insufficient.
- **artifact-template-analytics-dashboard**：Create a spreadsheet using the Analytics Dashboard template and its retained reference file. Use when the user selects or names Analytics Dashboard. Monitor acquisition, engagement, retention, revenue, and conversion funnel KPIs with charts.
- **artifact-template-business-review**：Create a presentation using the Business Review template and its retained reference file. Use when the user selects or names Business Review. Review business performance, KPIs, segment results, strategic priorities, decisions, and outlook.
- **artifact-template-design-report**：Create a document using the Design Report template and its retained reference file. Use when the user selects or names Design Report. Produce design reports with an executive summary, key findings, implications, recommendations, and appendix.
- **artifact-template-experiment-analysis**：Create a document using the Experiment Analysis template and its retained reference file. Use when the user selects or names Experiment Analysis. Analyze experiments with hypotheses, methodology, results, interpretation, limitations, and next steps.
- **artifact-template-financial-budget**：Create a spreadsheet using the Financial Budget template and its retained reference file. Use when the user selects or names Financial Budget. Model actuals, budget and scenario forecasts, variances, cash runway, and departmental plans.
- **artifact-template-investment-committee-memo**：Create a document using the Investment Committee Memo template and its retained reference file. Use when the user selects or names Investment Committee Memo. Prepare investment committee memos with the thesis, transaction details, financial analysis, risks, and recommendation.
- **artifact-template-legal-memorandum**：Create a document using the Legal Memorandum template and its retained reference file. Use when the user selects or names Legal Memorandum. Draft legal memoranda with the issue, brief answer, relevant facts, analysis, and conclusion.
- **artifact-template-market-trends-report**：Create a presentation using the Market Trends Report template and its retained reference file. Use when the user selects or names Market Trends Report. Communicate market or industry trends, supporting evidence, implications, and recommended responses.
- **artifact-template-minimal-letterhead**：Create a document using the Minimal Letterhead template and its retained reference file. Use when the user selects or names Minimal Letterhead. Write professional business letters with sender, recipient, message, and signature fields in a minimal letterhead layout.
- **artifact-template-operating-calendar**：Create a spreadsheet using the Operating Calendar template and its retained reference file. Use when the user selects or names Operating Calendar. Plan annual and monthly operating milestones, campaigns, launches, deadlines, and recurring events.
- **artifact-template-operating-review**：Create a presentation using the Operating Review template and its retained reference file. Use when the user selects or names Operating Review. Run weekly operating reviews with scorecards, functional updates, risks, decisions, and action items.
- **artifact-template-project-kickoff**：Create a presentation using the Project Kickoff template and its retained reference file. Use when the user selects or names Project Kickoff. Align teams on project goals, scope, roles, milestones, risks, and the working model.
- **artifact-template-project-tracker**：Create a spreadsheet using the Project Tracker template and its retained reference file. Use when the user selects or names Project Tracker. Manage workstreams, tasks, owners, status, priority, dates, launch pulse, and a Gantt schedule.
- **artifact-template-sales-pipeline**：Create a spreadsheet using the Sales Pipeline template and its retained reference file. Use when the user selects or names Sales Pipeline. Track opportunities, stages, owners, deal sizes, probabilities, forecasts, next steps, and risks.
- **artifact-template-simple-dark-mode**：Create a presentation using the Simple Dark Mode template and its retained reference file. Use when the user selects or names Simple Dark Mode. Create clean dark-mode presentations with bold typography, simple sections, charts, and imagery.
- **artifact-template-simple-light-mode**：Create a presentation using the Simple Light Mode template and its retained reference file. Use when the user selects or names Simple Light Mode. Create clean light-mode presentations with spacious typography, simple sections, charts, and imagery.
- **artifact-template-strategy-memorandum**：Create a document using the Strategy Memorandum template and its retained reference file. Use when the user selects or names Strategy Memorandum. Present strategic context, choices, rationale, risks, milestones, and a clear recommendation.
- **artifact-template-system-design**：Create a document using the System Design template and its retained reference file. Use when the user selects or names System Design. Document system architecture, requirements, components, data flows, APIs, tradeoffs, and operational considerations.
- **artifact-template-team-alignment**：Create a presentation using the Team Alignment template and its retained reference file. Use when the user selects or names Team Alignment. Facilitate team offsites and planning with context, goals, priorities, decisions, and action items.
- **artifact-template-three-statement-forecast**：Create a spreadsheet using the Three-Statement Forecast template and its retained reference file. Use when the user selects or names Three-Statement Forecast. Build an integrated income statement, balance sheet, and cash flow forecast with assumptions, checks, and an executive summary.
- **plugin-management**：Discover and suggest relevant plugins, inspect app permissions and dependencies, and manage plugin connections or removal. Use when the user asks about plugins or when a task would materially benefit from an external app, account, service, or data source that available tools cannot access.
- **documents**：Create, edit, redline, and comment on `.docx`, Word, and Google Docs-targeted document artifacts inside the container, with a strict render-and-verify workflow. Use `render_docx.py` to generate page PNGs (and optional PDF) for visual QA, then iterate until layout is flawless before delivering the final document.
- **pdf**：Read, create, inspect, render, and verify PDF files where visual layout matters, including fillable AcroForms. Use Poppler rendering plus Python tools such as reportlab, pdfplumber, and pypdf for generation and extraction.
- **Presentations**：Read, create or edit PowerPoint or Google Slides decks. Use for presentation, slide deck, PowerPoint, PPT, PPTX, or Google Slides requests.
- **excel-live-control**：Control an open or active Microsoft Excel workbook through the ChatGPT add-in or connected session. Use when the user tags the Microsoft Excel app in Codex or follows up on an established live Excel task. Do not use for standalone spreadsheet files or Google Sheets.
- **Spreadsheets**：Use skill when user requests to create, modify, analyze, visualize, or work with spreadsheet files (`.xlsx`, `.xls`, `.csv`, `.tsv`) or Google Sheets with formulas, formatting, charts, tables, and recalculation. Do not use for live controlling Microsoft Excel app or a live Excel session.
- **template-creator**：Create or update a reusable personal Codex artifact-template skill. Use when the user invokes $template-creator or asks in natural language to create a reusable template from a reference document, presentation, spreadsheet, Google Docs, Slides, or Sheets link, ImageGen or Product Design image, email, Slack message, or Site project, or explicitly asks to edit or update a passed artifact-template skill. Do not use for one-off creation from an existing template.

### 桌面額外提供的 Sites

Sites building／hosting／preview-troubleshooting 用於 Sites 管理，不是本 repo 的 Django 開發或 T470P 部署。
本專案同時停用 Sites 插件與其 connector；未刪除技能或改供應商檔案。先前桌面目錄回報的大小分別為 35,468／8,609／8,219 bytes，
R/S 分別 11/0、2/2、0/0；這些是初始目錄快照，不屬於本次本機 39 份掃描結果。不可將遠端技能路徑不存在解讀成已卸載所有遠端能力。

## MCP 與 Connector

| 名稱 | 狀態／分類 | 工具數與 instructions | 策略 |
| --- | --- | --- | --- |
| node_repl | enabled；runtime 保留、按需呼叫 | 清單 3 個操作工具，另保留 turn_ended lifecycle；會提供 runtime instructions | 白名單 js、js_reset、js_add_node_module_dir、turn_ended；不因存在就用 |
| cua_repl | enabled；UI On Demand | js、js_reset，加 lifecycle；選取 browser 才載入進一步操作文件 | 3 名白名單，js 輸出上限 6000；保留 Chrome／IAB |
| codex_app 插件 server | manifest disabled | 初始目錄另有約 35 個 app MCP 方法；核心也有原生 app 方法，不能當作該 server 已 enabled | 不強行啟動，也不刪 runtime 依賴 |
| GitHub connector | On Demand，保留既有連線 | 初始工具目錄 89 個；非本機 mcp_servers.gitHub | 僅 PR／Issue 任務搜尋需要的工具；不用虛構 search/read 白名單 |
| Sites connector | 本專案 disabled | 初始工具目錄 23 個；server instructions 未取得 | 不是本 repo 部署工具 |
| plugin-management | Rare | 初始目錄 6 個；由平台注入，未取得 server instructions | 只在插件管理需求用 |
| PostgreSQL／Context7 | 未配置 | 無可核對的活躍 server | 不安裝、不宣稱存在 |

工具數是本次目錄快照，版本變動會變；未初始化的 server instructions 不冒稱已完整審閱。
MCP 白名單控制暴露，不是權限提升；核心平台工具與遠端注入仍受產品控制。語意「On Demand」表示工作中按需使用，**不聲稱產品會自動啟停 server**。
