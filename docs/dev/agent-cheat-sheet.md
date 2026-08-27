# SubTube Agent Cheat Sheet

這份文件是 `.codex/agents/` 的快速索引；角色規則以各 codename TOML 為準。

## 1. 角色對照

| 要做的事 | Default | Pro | 主要產出 |
| :--- | :--- | :--- | :--- |
| MVP 需求、優先級、驗收 | `codex-luffy` / `codex-po` | `codex-luffy-pro` / `codex-po-pro` | PRD 決策、P0/P1、AC |
| 排程、依賴、風險、交接 | `codex-jarvis` / `codex-pm` | `codex-jarvis-pro` / `codex-pm-pro` | 工作拆分與里程碑 |
| iOS UI、播放器、Client API | `codex-scotty` / `codex-ios` | `codex-scotty-pro` / `codex-ios-pro` | SwiftUI/MVVM 實作與測試 |
| API、任務佇列、STT/LLM 管線 | `codex-uhura` / `codex-backend` | `codex-uhura-pro` / `codex-backend-pro` | Backend/AI 實作與契約測試 |
| 測試、回歸、錯誤路徑 | `codex-hermione` / `codex-qa` | `codex-hermione-pro` / `codex-qa-pro` | Given-When-Then 測試與證據 |
| 程式審查 | `codex-spock-review` / `codex-ios-review` | `codex-spock-review-pro` / `codex-ios-review-pro` | 唯讀 review、阻擋項目 |
| 測試審查 | `codex-mcgonagall-review` / `codex-qa-review` | `codex-mcgonagall-review-pro` / `codex-qa-review-pro` | 測試覆蓋與品質 gate |
| 使用者流程、狀態、可及性 | `codex-totoro` / `codex-ux` | `codex-totoro-pro` / `codex-ux-pro` | UX flow、空態與錯誤態規格 |
| CI、部署、Secrets、成本 | `codex-r2d2` / `codex-devops` | `codex-r2d2-pro` / `codex-devops-pro` | Infra/CI/observability |
| 狀態規格 | `codex-vitruvius` / `codex-spec-arch` | `codex-vitruvius-pro` / `codex-spec-arch-pro` | State map、interaction matrix |
| 狀態規格格式守門 | `codex-vigil` / `codex-spec-check` | `codex-vigil-pro` / `codex-spec-check-pro` | PASS/FAIL 與缺漏清單 |

## 2. Model tiers

- **Default**：沿用各 agent 的日常模型設定。
- **Pro**：所有 `-pro` 設定統一為 `gpt-5.6-sol` + `model_reasoning_effort = "high"`。
- Pro 只提高分析深度與審查嚴格度；仍受同一份 PRD、MVP red lines 與角色邊界約束。

## 3. MVP 協作流程

```text
PRD / 產品決策
      ↓
PO（luffy）定義範圍與 AC
      ↓
PM（jarvis）拆工作與依賴
      ↓
Spec（vitruvius → vigil，可選）
      ↓
實作（scotty / uhura）
      ↓
QA（hermione）驗證
      ↓
獨立 review（spock / mcgonagall）
```

## 4. MVP 驗證優先序

1. 有字幕影片可完成整條流程。
2. 無字幕影片可走 STT fallback，或明確失敗。
3. 句子同步與點擊跳轉符合 `PRD.md` 的 ±300ms 目標。
4. 網路中斷、背景恢復、重試與快取不產生重複任務。
5. 只有在核心閉環穩定後，才評估 word-level、A-B Loop、生詞本與口說功能。

## 5. 角色邊界

- Writer 可以修改自己負責的產物；reviewer 唯讀，不直接修檔。
- PO 可以修改 PRD／產品決策，不代替工程師實作。
- PM 負責調度與交接，不偷偷改 scope。
- UX 描述使用者可見行為與狀態，不替工程師決定未驗證的後端能力。
- QA 只報告實測或可重現的結果；無法執行時標記 `NOT RUN`，不推測通過。

## 6. Dispatch points 與完整回報

- 觸發語法：`派工 N 點`；SubTube 只允許 `1 / 2 / 3 / 5` SP。
- 單一 ticket 上限 5 SP；10 點工作包必須拆成至少兩張子 ticket。
- 派工是執行命令，不是只建立 reservation；先計算 dependency closure，完成一張才自動選下一張。
- 總預算包含未完成 prerequisite；10 SP target 若有 5 SP prerequisite，hard budget 必須是 15 SP。
- 主工作階段是唯一 dispatcher；PO／PM 可以提供決策與 queue，但不遞迴派工。
- 預設最多 2 個 in-flight work item，直到 runtime、CI 與可重跑驗證命令建立。
- 流程：`planned → in_progress → review_ready → qa → closed`；Review／QA feedback 回到 `in_progress` 持續修正，不是 `blocked`；只有明確外部阻塞才進 `status:blocked`，不得假裝完成。
- `waiting_dependency`、`wait_for_agent` 不是終止狀態；主工作階段必須繼續 spawn／wait／transition。單一 work item 最多重試 3 次。
- GitHub status labels：`status:todo`、`status:in_progress`、`status:review_ready`、`status:qa`、`status:blocked`、`status:drifted`；目前責任另加 `app:codex`。
- 每次 transition 都要有 issue comment：issue、agent、owner/reviewer、SP、AC、commit／fixture／測試證據、未執行項目、下一步、failure trace。
- Closeout 要回報 `budget / reserved / actual / refunded / remaining`、完成／進行中／blocked／derived issues、open decisions、NOT RUN 與 stop reason。

完整規則與模板：

- [`dispatch-points.md`](dispatch-points.md)
- [`progress-tracker.md`](progress-tracker.md)
- [`dispatch-ledger-template.md`](dispatch-ledger-template.md)
- [`github-issue-template.md`](github-issue-template.md)
