# SubTube Dispatch Points

這份文件把 Anki2 的「派工 N 點，直到完成或明確阻塞」模式縮成適合 SubTube MVP 的交付控制規則。它只管理工作如何被選取、派送、驗證與回報，不改變 [`PRD.md`](/Users/link/Source/subtube/PRD.md) 的產品範圍。

## 1. 觸發語法

主工作階段收到以下語意時，啟動一次 dispatch loop：

```text
派工 10 點
派工 10 點，直到任務完成
dispatch 10 points for Release A
```

SubTube 的點數規則：

- 只使用 `1 / 2 / 3 / 5` SP。
- 單一可執行 ticket 不得超過 5 SP；超過就先拆成子 ticket。
- 10 點不是一張 10 點 ticket，而是可平行或串行的子 ticket 工作包，例如 `5 + 5`。
- 父 ticket 只做追蹤與依賴，不填 Estimate；子 ticket 才是可派工單位。
- SP 是排程工作量，不等於模型 token、工時或實際費用。可取得的 token／時間另列在 closeout evidence。
- Hard budget 必須包含目標 ticket 的未完成 prerequisite；目前 #1725 + #1727 是 10 SP target，但因依賴 #1717（5 SP），完整 dispatch closure 需要 15 SP。
- Dependency 只控制「何時可以派工」，不把 ticket 綁成一個共同完成事件。#1717、#1725、#1727 都是獨立 closeout unit；每張 ticket 都要各自走完 writer → review → QA → closeout，完成後 controller 才選下一張可執行 ticket。
- Review／QA 的 FAIL 是 rework feedback，不是工項結束。ticket 只要尚未 close，就必須留在 queue 中持續修正；目前採 `review_policy=rework_until_closed`。只有 `completed` 或明確外部 `blocked` 才能停止該 ticket。

預設命令可寫成：

```text
派工 10 點；專案 SubTube MVP；只執行 Release A P0；
單一 ticket 上限 5 點；直到點數耗盡、工項完成或全部 blocked；
每個狀態變更回報 issue、agent、AC、證據、下一步與停止原因。
```

## 2. 誰可以派工

主工作階段是唯一 dispatcher，負責實際呼叫 agent、等待結果、扣／退 SP、處理依賴與最後回報。

| 角色 | 可以做 | 不可以做 |
| :--- | :--- | :--- |
| PO (`codex-luffy-pro`) | 凍結 MVP scope、AC、open decision、Release gate | 代替 writer 實作；遞迴派生另一輪 agent |
| PM (`codex-jarvis-pro`) | 建立 queue、估點、排序、依賴、handoff packet | 直接修改工程；自行宣稱完成；遞迴派工 |
| Spec (`vitruvius` → `vigil`) | 產出與 gate state／error／async contract | 把未決產品選擇當成已決定 |
| Writer (`scotty`／`uhura`／其他 owner) | 只修改自己負責的 work item | 與另一 writer 共用同一工作目錄 |
| Reviewer (`spock-review`) | 唯讀檢查 diff、PRD、AC、風險與證據 | 自己修 code；審查自己的實作 |
| QA (`hermione`) | 執行測試、fixture、AC matrix、回報實測結果 | 把未執行的 build／provider／latency 寫成 PASS |

PO 與 PM 可以被主工作階段呼叫提供決策或排程，但不應自行 spawn 下一層 agent。這避免「agent 派 agent」造成重複扣點、責任不明與無法收斂的背景工作。

## 3. Dispatch loop

每一輪都按下列順序執行；任何一步失敗都要在同一個 issue 留下原因與下一步。

1. **Preflight**：確認 GitHub auth、ticket repo、Project、Estimate、目前 status、依賴 closure、runtime／test command 與 ledger 可用。
2. **Budget closure**：先把目標 ticket 的所有未完成前置依賴加入 queue；target budget、prerequisite budget、required total 分開記錄。若 required total 超過 hard budget，回報 `NEEDS_BUDGET`，不得只留下永遠等待的 reservation。這是派工預算檢查，不代表三張 ticket 共用一個 closeout。
3. **Queue**：PM 只提出 queue；主工作階段選擇最高優先、依賴已滿足、`SP <= 5` 的 issue。依賴未滿足時，先 dispatch 依賴，不把 `waiting_dependency` 當成停止。
4. **Reserve**：確認 dependency closure 可執行後，在 ledger 記錄 `budgeted / reserved / remaining`，再建立 `planned` comment；尚未 claim 前不得宣稱已開工。
5. **Claim**：writer 將 issue 設為 `status:in_progress`、`app:codex`，並回報 owner、branch/worktree、第一個 AC 與預計 evidence。
6. **Implement**：writer 只處理明確 scope；若發現新工作，建立 derived issue，原 ticket 標記 `blocked` 或保留未完成 AC，不偷偷擴 scope。
7. **Handoff**：writer 以 `review_ready` 交接，必須附 commit／diff、測試結果、AC 完成／未完成、已知風險與 reviewer。
8. **Review**：獨立 reviewer 唯讀審查；有 finding 就回 writer，沒有 evidence 不得進 QA。
9. **QA**：Hermione 執行可重跑測試或 fixture；runtime 尚未建立時，明確標 `NOT RUN`，以 contract／fixture／readback 取代，不假造 build。
10. **Closeout**：每張 ticket 只有在自己的 AC、review、QA evidence 完成後才關閉該 issue，記錄 actual usage、未使用 SP、derived issue 與風險；接著立即回到 Queue。整輪 dispatch 只有在 dependency closure 內的每張 ticket 都已個別關閉後才算完成。

### Gate 順序

```text
PRD / PO decision
      ↓
PM queue + estimate
      ↓
Vitruvius contract
      ↓
Vigil PASS
      ↓
Writer
      ↓
Spock review PASS
      ↓
Hermione QA
      ↓
Closeout / next dispatch
```

Release A 必須先於 Release B；沒有 D1／D2／D3 gate，不得因為 queue 有空間就派 STT 工作。M1 的 API／state contract（目前對應 #1717）未 PASS 時，#1725／#1727 只能做 readiness，不能報 implementation complete。

### Continuous controller contract

`planned`、`waiting_dependency`、`wait_for_agent`、`review_feedback` 不是 final state。主工作階段必須持有同一個 `dispatch_id`，反覆執行；每一張 ticket 都有自己的完整生命週期：

```text
resolve dependency → spawn writer → wait → review
    ├─ feedback → rework writer ─┐
    └─ PASS → QA ────────────────┴→ close ticket → select next
```

- 每個 `spawn` 都要取得 agent id；每個 `wait` 都要等 final result 或明確 timeout／error。
- agent final 後，主工作階段不得回覆使用者等待下一步；要先更新 issue、ledger，再啟動下一個 runnable item。
- `waiting_dependency` 只能轉成 `resolve_dependency`、`needs_budget` 或 `blocked`；不可直接結束 dispatch。
- `needs_budget` 是唯一允許回到使用者請求補充預算的排程狀態；其餘狀態由 controller 自行繼續。
- `completion_mode=each_ticket` 是目前唯一模式：依賴完成是下一張 ticket 的啟動 gate，不是前一張 ticket 的 closeout gate；整輪完成條件是 dependency closure 內所有 ticket 都個別 `completed`。
- `review_feedback` 只記錄 reviewer／QA findings，接著自動回到 Writer；不映射成 GitHub `status:blocked`，也不消耗 agent retry 次數。`max_retries=3` 只限制新的 agent/process dispatch failure；review／QA rework cycle 不設自動終止上限。
- `blocked` 只能由明確外部阻塞或 PO decision 產生；不能只因 reviewer／QA 回報 FAIL 就結束。
- 目前可用的 deterministic queue／budget validator 是 [`dispatch_loop.py`](../../scripts/progress/dispatch_loop.py)，agent spawn／wait 仍由主工作階段的 multi-agent tool 執行。

## 4. 點數與停止條件

### Ledger 欄位

每輪至少記錄：

```text
dispatch_id, issue, parent, estimate_sp, reserved_sp,
actual_sp, refunded_sp, remaining_sp, status,
owner, reviewer, dependencies, evidence, stop_reason
```

`actual_sp` 只在 closeout 計算；若 issue 被 blocked，未消耗的 reserved SP 必須退回本輪 remaining。若只完成部分 AC，不能把整張 ticket 設為 done，應保留 remaining work 或建立 derived issue。

### 預設並行度

- 目前沒有 runtime repository、build command 或 CI：最多 2 個 in-flight work item，且不得同時修改同一份文件／契約。
- runtime 與 CI 建立後，經 PM／PO 確認才可提高至最多 3 個。
- 每個 work item 只允許一個 writer；reviewer、QA 使用新的 context。

### 結束條件

Dispatch loop 只可在下列情況停止，且 final report 必須指出是哪一種：

- budget 已用完；
- 本輪 ticket 全部完成並通過 review／QA；
- 剩餘 ticket 都被同一個明確依賴阻擋，已建立 open decision；
- auth、repo、權限或外部政策使下一步不可安全執行；
- PRD／PO 明確改變 scope。

「agent 尚未回覆」不是完成，也不是停止理由；主工作階段要等待或重試並留下 failure trace。Review／QA feedback 也不是停止理由，必須回到 Writer 持續處理；只有明確外部阻塞才可標記 blocked。`waiting_dependency` 也不是停止理由，除非 dependency 已被明確標記 `blocked` 或 required budget 不足。

## 5. SubTube 現況與 GitHub 邊界

目前 SubTube source checkout 已連結獨立 repository `eaiccc/SubTube`，但仍沒有 runtime、build scheme 或部署腳本。既有 GitHub ticket 暫放在 `eaiccc/Anki2`，Project 為使用者的 `SubTube MVP` #2；這是權限下的暫時 ticket repo，不代表 SubTube 與 Anki2 共用產品程式碼。

所有 script 都要求明確提供：

```bash
export SUBTUBE_GITHUB_REPO=eaiccc/Anki2
```

即使工單暫放在 Anki2，也不得把 Anki2 的 iOS build command、SwiftData、訂閱、SM-2、child-mode 或其他 Anki2 專案規則複製進 SubTube。

## 6. Full situation report

每輪 final report 至少包含：

```text
Dispatch: <id>
Budget: <N SP>; reserved=<N>; actual=<N>; refunded=<N>; remaining=<N>
Scope: Release A / Release B; PO decision=<issue/comment>

Completed:
- #<issue> <title> — <SP> — owner=<agent> — reviewer=<agent>
  AC=<PASS/PARTIAL>; evidence=<commit/test/fixture/file:line>

In progress:
- #<issue> — <status> — current agent — next action — dependency

Blocked / open decisions:
- #<issue or decision> — blocker — tried — owner — unblock condition

Not run:
- build / integration / provider / latency / TestFlight: reason

Next dispatch:
- <issue>, <SP>, dependency, intended writer/reviewer/QA
Stop reason: <budget_exhausted | completed | blocked | auth | scope_change>
```

沒有 evidence 的項目必須寫 `NOT RUN` 或 `NOT VERIFIED`，不可只寫「agent 已處理」。
