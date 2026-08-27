# AGENTS.md

Guidance for Codex working in the SubTube repository. This file is the project entry point; detailed role instructions live in `.codex/agents/`.

## Project

**SubTube** — AI-driven video language-learning app for iOS. The MVP turns a supported public YouTube URL into synchronized English subtitles and Traditional Chinese translation.

Current status: product definition only. The authoritative product scope is [`PRD.md`](PRD.md); runtime code, build schemes, and deployment scripts have not been established yet.

## MVP Source of Truth

- `PRD.md` defines the MVP hypothesis, scope, API contract, acceptance criteria, metrics, and deferred backlog.
- MVP flow: URL input → caption fetch or STT fallback → sentence translation → synchronized player → sentence seek.
- Supported scope: public, non-live, embeddable English videos up to 15 minutes; English → `zh-Hant-TW`.
- Sentence-level synchronization is the launch gate. Word-level highlighting is optional and must never block a result.

## Architecture Direction

- iOS: SwiftUI + MVVM + `async/await`.
- Backend: REST API + asynchronous task queue; polling is the MVP transport.
- Pipeline: captions first, one STT provider as fallback, one LLM translation provider, JSON Schema validation, idempotent result cache.
- Third-party API keys stay on the server. The client never calls STT/LLM providers directly.

## Agents

Codename files are the single source of truth. Alias files only point to a codename file and must not add rules.

| Role | Default | Pro (`sol` + `high`) | Alias / Pro alias |
| :--- | :--- | :--- | :--- |
| Product Owner | `codex-luffy` | `codex-luffy-pro` | `codex-po` / `codex-po-pro` |
| Project Manager | `codex-jarvis` | `codex-jarvis-pro` | `codex-pm` / `codex-pm-pro` |
| iOS Engineer | `codex-scotty` | `codex-scotty-pro` | `codex-ios` / `codex-ios-pro` |
| Backend / AI Engineer | `codex-uhura` | `codex-uhura-pro` | `codex-backend` / `codex-backend-pro` |
| QA Engineer | `codex-hermione` | `codex-hermione-pro` | `codex-qa` / `codex-qa-pro` |
| Code Reviewer | `codex-spock-review` | `codex-spock-review-pro` | `codex-ios-review` / `codex-ios-review-pro` |
| QA Reviewer | `codex-mcgonagall-review` | `codex-mcgonagall-review-pro` | `codex-qa-review` / `codex-qa-review-pro` |
| UI/UX Designer | `codex-totoro` | `codex-totoro-pro` | `codex-ux` / `codex-ux-pro` |
| DevOps Engineer | `codex-r2d2` | `codex-r2d2-pro` | `codex-devops` / `codex-devops-pro` |
| State Spec Architect | `codex-vitruvius` | `codex-vitruvius-pro` | `codex-spec-arch` / `codex-spec-arch-pro` |
| Spec Gatekeeper | `codex-vigil` | `codex-vigil-pro` | `codex-spec-check` / `codex-spec-check-pro` |

All Pro files use `model = "gpt-5.6-sol"` and `model_reasoning_effort = "high"`. Pro agents inherit the corresponding default role and add deeper architecture, risk, edge-case, or independent-review scrutiny; they do not expand MVP scope by themselves.

The MVP intentionally does not create Anki2-specific SM-2, subscription, child-mode, or persona-QA agents. Add a role only when a SubTube requirement needs it.

## Delivery orchestration

The Anki2-style dispatch and reporting rules are adapted in:

- [`docs/dev/dispatch-points.md`](docs/dev/dispatch-points.md) — point budget, dispatcher authority, gates, stop conditions, and full situation report.
- [`docs/dev/progress-tracker.md`](docs/dev/progress-tracker.md) — GitHub status labels, transition contract, and handoff packet.
- [`docs/dev/dispatch-ledger-template.md`](docs/dev/dispatch-ledger-template.md) — per-dispatch accounting.
- [`docs/dev/github-issue-template.md`](docs/dev/github-issue-template.md) — issue estimate and acceptance-criteria template.

Operational defaults:

- The main work session is the sole dispatcher. PO and PM provide product decisions and queue proposals; they do not recursively spawn implementation agents.
- `派工 N 點` is an execution command, not a planning-only command. After reservation, the main session stays in the loop until every ticket in the dependency closure has independently closed or an explicit stop condition is reached.
- Use `1 / 2 / 3 / 5` SP only. A ticket over 5 SP must be split; a 10-point work package is `5 + 5` (or smaller), never one 10-point ticket.
- Resolve the full dependency closure before reserving work. The hard budget includes unfinished prerequisites; a 10-SP target with a 5-SP prerequisite requires 15 SP. Never silently overspend or silently drop the prerequisite.
- Dependencies gate dispatch order only. Every ticket in the closure must independently complete writer → review → QA → closeout; do not treat a three-ticket chain as one shared completion event.
- Review／QA FAIL is non-terminal feedback. Keep the issue open/in progress, route findings back to the Writer, and continue until the issue is closed; only explicit external blockage may become `blocked`.
- Issue comments are the source of truth. Each transition updates one `status:*` label, optional `app:codex`, and a progress comment with agent, AC, evidence, next step, and failure trace.
- One writer owns a work item. Reviewer and QA use independent contexts and do not modify the writer's files.
- With no runtime or CI in this checkout, keep at most two in-flight items and report build, provider, latency, and TestFlight checks as `NOT RUN` unless evidence exists.
- Release A gates Release B. Do not dispatch STT implementation while D1/D2/D3 or the API/state contract gate is unresolved.
- `planned`, `waiting_dependency`, and `wait_for_agent` are non-terminal controller states. The main session must dispatch the dependency, call the agent wait mechanism, consume the final evidence, and continue; it must not return a final response merely because a plan was created.

The SubTube source and GitHub ticket repository is `eaiccc/SubTube`; the SubTube tickets were migrated from the temporary `eaiccc/Anki2` location. Scripts must receive `--repo` or `SUBTUBE_GITHUB_REPO`; never infer a repository from the folder name.

## Working Rules

1. Before acting, read `AGENTS.md` and the relevant sections of `PRD.md`.
2. Keep one writer per work item. The implementation writer and reviewer must be different agents.
3. Every implementation change includes a verification plan and evidence. If code does not yet exist, use fixtures and contract tests rather than inventing production behavior.
4. Do not silently expand the MVP. New behavior must be marked P0, Post-MVP, or an explicit product decision.
5. External-policy, provider, cost, or source-access uncertainty must be reported as an open decision; do not hide it behind a workaround.
6. Keep user-visible strings, error states, loading states, retry behavior, and background/resume behavior explicit.
7. Do not claim that an agent has started work until the issue has a writer claim and an `in_progress` progress comment.
8. Do not close an issue until independent review, QA evidence, AC coverage, and closeout usage are recorded; blocked work must refund reserved SP in the ledger.
9. Derived work must become a separately estimated child issue; do not hide scope expansion in the current ticket.
10. When an agent reaches a final result, immediately perform the next state transition and dispatch the next runnable writer/reviewer/QA; do not wait for a new user message.
11. Missing runtime/build tooling blocks only runtime-specific evidence. It does not block contract, fixture, documentation, or state-machine work that can be independently verified.

## Red Lines

- Do not support private, login-gated, live, DRM, or non-embeddable videos in the MVP.
- Do not use IP rotation or another mechanism to bypass source restrictions.
- Do not put STT/LLM/API secrets in iOS code, logs, or local learning data.
- Do not retain raw audio permanently; the PRD sets a maximum 24-hour processing TTL.
- Do not require microphone or speech-recognition permission in the MVP.
- Do not make word-level timestamps a prerequisite for a successful learning document.
- Parse-job retries must be idempotent and must not duplicate STT/LLM work.
- Do not claim build, test, latency, or provider success without running or clearly labeling the evidence as unavailable.

## Commands

No build or test command is defined yet because this checkout contains only the PRD. Once implementation is added, document the canonical commands here before assigning build or QA work.

Progress commands are available for the current documentation-only phase:

```bash
bash scripts/progress/log_progress.sh --help
bash scripts/progress/update_github_issue.sh --help
python3 scripts/progress/dispatch_loop.py --plan docs/dev/dispatch-plan.example.json --validate
python3 scripts/progress/dispatch_loop.py --plan docs/dev/dispatch-plan.example.json --next
```

For GitHub updates, set `SUBTUBE_GITHUB_REPO` or pass `--repo`; the scripts preserve non-workflow labels and replace only `status:*` / `app:*` labels.

## Response

Reply in Traditional Chinese unless the user writes in English. Reference files with paths and line numbers when available.
