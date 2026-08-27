# SubTube Progress Tracker

Issue comment 是交付狀態的 source of truth；Project view 與本地 `progress/` 檔案只是查詢／快取。每次狀態轉換都要同時更新 GitHub labels、寫 progress comment，並 readback 驗證 issue。

Controller state 與 GitHub status label 分開：`waiting_dependency`、`wait_for_agent`、`needs_budget`、`review_feedback` 是本地 dispatch state；只有真正 blocked 的外部阻擋才映射到 `status:blocked`。Review／QA FAIL 只建立 feedback，ticket 維持 open/in_progress 並持續處理。

## Status labels

每張可執行 ticket 最多一個 `status:*` 與一個 `app:*`：

```text
status:todo
status:in_progress
status:review_ready
status:qa
status:blocked
status:drifted
app:codex
```

`agent:codex-*-pro` 是角色／owner metadata，不取代 `app:codex` 的目前責任。完成時關閉 issue，不建立 `status:completed`。

## Transition contract

| 狀態 | 必填內容 |
| :--- | :--- |
| `planned` → `status:todo` | scope、SP、owner、reviewer、依賴、AC、尚未 claim 的聲明 |
| `in_progress` | writer、branch/worktree、第一個 AC、預計 evidence |
| `review_ready` | from/to、commit／diff、AC done/remaining、測試、風險 |
| `review_feedback` | reviewer／QA findings、修正範圍、rework writer、目前 cycle；非終止狀態 |
| `qa` | reviewer verdict、QA scope、fixture／command、目前 evidence |
| `blocked` | error／blocker、已嘗試、影響、需要誰決策、解除條件 |
| `completed` | commit／PR、review PASS、QA PASS、AC matrix、closeout、未用 SP |

若尚未有 runtime，`test_result` 必須是 `NOT RUN — runtime/build command not defined`，並附目前可做的 contract／fixture／readback 證據。

## Standard dispatch packet

```text
REPO
PROJECT
ISSUE
APP
ROLE
PAIR (writer / reviewer / QA)
MODE (default / pro)
SOURCE (PRD section / decision / parent issue)
GOAL
SCOPE
AC
DEPENDENCIES
ESTIMATE_SP
BUDGET_REMAINING
BRANCH
WORKTREE
LAST_COMMIT
CURRENT_STATUS
TEST_RESULT
TRIED_AND_FAILED
EXCEPTION
HANDOFF_TO
REPORT
STOP
```

## Local and GitHub commands

本地只記錄交接事件：

```bash
bash scripts/progress/log_progress.sh \
  --agent codex-uhura-pro \
  --task "URL normalization and preflight" \
  --task-id issue-1725 \
  --status in_progress \
  --issue 1725 \
  --repo eaiccc/SubTube \
  --points 5 \
  --ac "MVP-01; AC-01" \
  --evidence "NOT RUN — runtime not established"
```

只需同步 GitHub comment／labels 時：

```bash
bash scripts/progress/update_github_issue.sh \
  --repo eaiccc/SubTube \
  --issue 1725 \
  --status review_ready \
  --agent codex-uhura-pro \
  --handoff-to codex-spock-review-pro \
  --commit '<sha-or-NOT-AVAILABLE>' \
  --test-result 'NOT RUN — runtime not established'
```

沒有指定 `--repo` 且沒有 `SUBTUBE_GITHUB_REPO` 時，script 應停止而不是猜 repo。

## Continuous loop

使用 [`dispatch_loop.py`](../../scripts/progress/dispatch_loop.py) 先驗證 dependency closure，再由主工作階段執行 agent lifecycle。dependency closure 是 queue／預算範圍；每張 ticket 仍須獨立完成自己的 review、QA 與 closeout：

```bash
python3 scripts/progress/dispatch_loop.py \
  --plan docs/dev/dispatch-plan.example.json --validate

python3 scripts/progress/dispatch_loop.py \
  --plan docs/dev/dispatch-plan.example.json --next
```

`--next` 回傳 `dispatch_writer`、`resolve_dependency`、`wait_for_agent`、`needs_budget` 或 `completed`。Review／QA FAIL 時先用 `--transition ISSUE review_feedback --note ...` 記錄 feedback；下一個 `--next` 會回傳 `dispatch_writer` 重新處理，不會停止。只有 dependency closure 內所有 ticket 都個別完成時，才回傳 `completed`。

Controller exit codes：`0` = 可繼續或已完成；`3` = `needs_budget`，需補充 hard budget；`4` = `blocked`，需 PO／外部決策；`2` = plan/config 不合法。

## Failure trace

阻塞回報必須回答：

1. 失敗發生在哪一個 command／gate／AC？
2. 實際錯誤或觀察到的結果是什麼？
3. 已嘗試哪些替代方案？
4. 哪些 SP 應退回 ledger？
5. 下一步需要哪個 agent 或 PO decision？
