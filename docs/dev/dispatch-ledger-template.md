# SubTube Dispatch Ledger Template

複製本模板建立每一輪 dispatch 的紀錄。SP 只代表工作量；實際 token、時間與費用若沒有工具證據，填 `NOT AVAILABLE`。

```yaml
dispatch_id: dispatch-YYYYMMDD-HHMM
project: SubTube MVP
repo: ${SUBTUBE_GITHUB_REPO}
github_project: "SubTube MVP #2"
scope: Release A P0
budget_sp: 15
target_budget_sp: 10
prerequisite_budget_sp: 5
budget_status: ready
max_ticket_sp: 5
max_in_flight: 2
max_retries: 3
review_policy: rework_until_closed
started_at: YYYY-MM-DDTHH:MM:SS+08:00
controller_state: planned
stop_reason: null

items:
  - issue: 1717
    parent: 1716
    title: Release A API/state/error contract prerequisite
    estimate_sp: 5
    reserved_sp: 5
    actual_sp: null
    refunded_sp: 0
    owner: codex-vitruvius-pro
    reviewer: codex-vigil-pro
    qa: codex-hermione-pro
    dependencies: []
    state: todo
    controller_state: dispatch_writer
    attempts: 0
    review_cycles: 0
    ac: [MVP-02, AC-05]
    evidence: null
    tried_and_failed: null
    exception: null
    handoff_to: null

  - issue: 1725
    parent: 1716
    title: URL normalization and preflight
    estimate_sp: 5
    reserved_sp: 5
    actual_sp: null
    refunded_sp: 0
    owner: codex-uhura-pro
    reviewer: codex-spock-review-pro
    qa: codex-hermione-pro
    dependencies: [1717]
    state: todo
    controller_state: waiting_dependency
    attempts: 0
    review_cycles: 0
    labels: [agent:codex-uhura-pro, status:todo]
    ac: [MVP-01, AC-01, AC-04]
    evidence: null
    tried_and_failed: null
    exception: null
    handoff_to: null

  - issue: 1727
    parent: 1716
    title: Caption parse job state and polling lifecycle
    estimate_sp: 5
    reserved_sp: 5
    actual_sp: null
    refunded_sp: 0
    owner: codex-uhura-pro
    reviewer: codex-spock-review-pro
    qa: codex-hermione-pro
    dependencies: [1717, 1725]
    state: todo
    controller_state: waiting_dependency
    attempts: 0
    review_cycles: 0
    labels: [agent:codex-uhura-pro, status:todo]
    ac: [MVP-02, AC-01, AC-05]
    evidence: null
    tried_and_failed: null
    exception: null
    handoff_to: null

summary:
  reserved_sp: 15
  actual_sp: 0
  refunded_sp: 0
  remaining_sp: 0
  completed_issues: []
  derived_issues: []
  blocked_decisions: []
  not_run: []
```
