# #1705 Decision memo — D1-D6 and Release A provider/corpus gate

- Date: 2026-08-27 (Asia/Taipei)
- Writer: `codex-luffy-pro`
- Reviewer handoff: `codex-vigil-pro`
- Scope: Release A product decisions and fixtures only
- Machine-readable source: [`decision-ledger.json`](../../contracts/release-a-gates/fixtures/decision-ledger.json)
- Corpus source: [`release-a-corpus.json`](../../contracts/release-a-gates/fixtures/release-a-corpus.json)
- Canonical check: `python3 contracts/release-a-gates/verify_gates.py`

The canonical command applies both strict JSON schemas with a Python-stdlib
validator and then runs cross-file product semantics; loading a schema without
applying it is not accepted. Its deterministic suite currently rejects 34/34
invalid mutations, including the nine classes returned by `codex-vigil-pro`.
Passing this command proves package consistency only, not provider or runtime
execution.

## Decision

Release A remains **BLOCKED / NO-GO for real provider execution**. The
translation provider, model snapshot, token budget, timeout envelope, pipeline
version and direct-provider cost cap are frozen, but no approved provider can
retrieve caption text from arbitrary public YouTube videos. The official
YouTube `captions.download` method requires permission to edit the video; using
it as if a public caption badge granted download access would be a false
assumption. D3-A therefore has 20 traceable candidates but zero verified corpus
members and no quality, latency or provider PASS.

Release B remains **OPEN / NO-GO**. This change does not enable audio,
`transcribing`, STT or `transcriptSource=stt`.

## D1-D6 ledger

| ID | Status | Decision / release impact | Owner | Deadline | Evidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| D1 | OPEN / NO-GO | No approved captionless-video audio path; blocks B only. | PO + named legal counsel (identity OPEN) | 2026-09-30 17:00 +08:00 or before M3 | `PRD.md:55-62,367-375,526-539`; YouTube API Terms |
| D2 | BLOCKED / NO-GO | D2-A metadata and LLM choices frozen; caption-text provider absent, so A provider execution is blocked. D2-B remains OPEN. | PO + Uhura + R2D2 | 2026-09-05 17:00 +08:00 or before M1 | `decision-ledger.json`; official YouTube/OpenAI sources below |
| D3 | BLOCKED / NO-GO | 20 candidates, two reviewer roles and rubric exist; verified=0 and staging/quality NOT RUN. B corpus is not included. | PO + Hermione | 2026-09-08 17:00 +08:00 or before M1 gate | `release-a-corpus.json`; validator |
| D4 | DECIDED; runtime NOT RUN | Freeze 5/installation/24h, 20/IP/24h and one in-flight job; enforcement still blocks M2. | PO + R2D2 | 2026-09-30 17:00 +08:00 or before M2 RC | `PRD.md:376-382,437-441,526-539` |
| D5 | OPEN / NO-GO | Raw audio ≤24h and learning cache 7d are frozen values; purge/runtime proof absent and blocks M2. | Uhura + R2D2 | 2026-09-30 17:00 +08:00 or before M2 RC | `PRD.md:367-375,526-539`; release contract evidence status |
| D6 | DECIDED | The 900-second cap applies. All 20 page-observed candidate durations are ≤646s; replacements may not relax the limit. API recheck remains part of D3-A. | PO | 2026-08-27 | corpus + validator |

The JSON ledger is normative for full owner, deadline, unblock conditions,
evidence and release-impact fields.

## D2-A frozen choices and blocker

| Field | Decision | Evidence status |
| :--- | :--- | :--- |
| Metadata source/provider | YouTube Data API v3 `videos.list`; read duration, caption indicator, live state, audio language, privacy and embeddability. | Official capability documented; API call NOT RUN (no credential/runtime). |
| Caption source | English creator-provided or YouTube automatic captions on an otherwise supported video. | Product source fixed; retrieval NOT VERIFIED. |
| Caption-text provider | **None approved.** `captions.list` needs OAuth and does not return text; `captions.download` requires edit permission. | BLOCKED; Release A M1 NO-GO. |
| Translation provider/model | OpenAI Responses API, `gpt-5.4-mini-2026-03-17`, `reasoning_effort=none`, Structured Outputs, `zh-Hant-TW`. The older `gpt-5-mini-2025-08-07` was rejected because its current model page marks it deprecated. | Official model/version/price documented; provider call and quality NOT RUN. |
| Pipeline version | `release-a-caption-v1`; reserved but deployment forbidden while caption provider is blocked. Provider/model/prompt/schema/segmentation changes require a new version. | Decision PASS; runtime NOT RUN. |
| Timeout | Preflight hard 2s; caption step 15s; LLM attempt 20s; job hard 60s; at most one automatic translation retry. | Decision PASS; latency NOT RUN. |
| Cost cap | Direct provider usage ≤USD 0.15/job; infrastructure excluded and YouTube quota recorded separately. | Formula readback PASS; metering NOT RUN. |

Cost calculation uses non-cached standard pricing and the aggregate per-attempt
limits, so it does not depend on a cache discount:

```text
2 attempts × ((12,000 input / 1,000,000 × USD 0.75)
            + (12,000 output / 1,000,000 × USD 4.50))
= USD 0.126 base LLM worst case

USD 0.126 × 1.10 maximum documented regional-processing uplift
= USD 0.1386 conservative LLM worst case

USD 0.150 hard cap - USD 0.1386 = USD 0.0114 maximum remaining allowance
for an eventual caption-text provider.
```

The cap covers direct task-level provider charges only. No USD value is invented
for YouTube quota units. If an approved caption provider cannot fit the remaining
USD 0.0114, D2-A must be reopened instead of silently exceeding the cap.

## Official external evidence

All pages were accessed 2026-08-27. Scope and limitations are preserved here;
documentation readback is not a provider execution test.

| Source | Applicable fact | Limitation |
| :--- | :--- | :--- |
| <https://developers.google.com/youtube/v3/docs/videos> | `videos` exposes duration, caption availability indicator, live state, default audio language and embeddable status. | No API credential/runtime call was made. `contentDetails.caption=true` does not prove caption text is retrievable. |
| <https://developers.google.com/youtube/v3/docs/captions/list> | Lists tracks, costs 50 quota units, requires OAuth; response does not contain caption text. | Does not solve arbitrary-public caption retrieval. |
| <https://developers.google.com/youtube/v3/docs/captions/download> | Downloads a track, costs 200 quota units, and requires permission to edit the video. | Blocks use for arbitrary third-party public videos without owner authorization. |
| <https://developers.google.com/youtube/v3/determine_quota_cost> | `videos.list=1`, `captions.list=50`; download page states `captions.download=200`. | Quota units are not USD pricing or authorization. |
| <https://developers.google.com/youtube/terms/api-services-terms-of-service> | API clients must comply with YouTube API terms. | Legal interpretation still needs the named D1 legal owner. |
| <https://developers.openai.com/api/docs/models/gpt-5.4-mini> | Snapshot `gpt-5.4-mini-2026-03-17`, Structured Outputs, USD 0.75/M input, USD 4.50/M output and a documented 10% regional-processing uplift. | Translation quality, availability, account access, latency and billed usage are NOT RUN. |

## D3-A and D6 corpus decision

The manifest contains 20 public-search-visible standard watch candidates from
verified TED/TED-Ed channels. The YouTube pages showed fixed durations, English
metadata and a captions badge. Maximum observed duration is 646 seconds, so D6
does not require changing data or widening the 900-second product limit.

Every row remains `candidate`; `verifiedCount=0`. Before a gate run, every video
must, within 24 hours, pass server preflight for public/non-live/embeddable/
English/≤900s and approved English caption retrieval, then load in the Release A
IFrame environment. The validator rejects promotion to `verified` without those
structured evidence fields, including a run ID, run start timestamp,
timezone-aware check time, videos.list facts, named approved caption provider,
embed result and frozen environment fingerprint. The validator also requires
the run/check timestamps to be strict RFC3339, non-future and within 24 hours.
Any verified promotion must contain all 20 videos, an approved provider and
evidence, provisioned staging with actual run evidence, and matching corpus /
ledger gate states. Search-page signals do not satisfy this gate.

The corpus is deliberately separate from:

- preflight rejection fixtures 06, 07 and 12–16;
- service-failure fixture 08;
- any Release B captionless/STT corpus, which does not exist in this package.

Two independent Traditional-Chinese review roles are assigned:
`codex-hermione-pro` and `codex-mcgonagall-review-pro`. Each must score the same
deterministically selected 10 segments per video before seeing the other score.
The rubric is 1–5; 4 means accurate, complete and natural enough Taiwan
Traditional Chinese. A rating is acceptable at ≥4, and at least 90% of all
20 × 10 × 2 = 400 ratings must be acceptable. Execution is **NOT RUN**.

The required `release-a-staging` environment is **BLOCKED / NOT PROVISIONED**.
Replacement never widens the video limit: invalidate the stale item, replace it
with another item satisfying every Release A condition, increment corpus
revision and rerun all 20 so metrics are not merged across corpus versions.

## AC and metric audit

| Requirement | Status | Evidence / gap |
| :--- | :--- | :--- |
| D1-D6 each has state, owner, deadline, source and release impact | PASS (document/fixture) | ledger + validator |
| D2-A caption/LLM/model/version/timeout/pipeline/cost | PARTIAL / BLOCKED | LLM and controls frozen; caption-text provider absent, so no false completion claim |
| D3-A 20-video Release A manifest | PASS as candidate list; quality gate BLOCKED | 20 unique candidates; verified=0; staging/provider NOT RUN |
| D3-A two reviewers, rubric, ≥4 threshold, 90% gate | PASS (contract); execution NOT RUN | corpus `qualityPlan` |
| D6 ≤15 minutes | PASS for observed candidate values | max 646s; official preflight recheck belongs to D3-A |
| AC-01 real caption path and P95≤60s | NOT RUN / blocked by D2-A and staging | Synthetic #1717 contract evidence remains separate |
| AC-02A zero audio/STT/LLM on captionless preflight | Contract fixture exists; real provider NOT RUN | existing fixture 06; red lines rechecked here |
| AC-03 ±300ms sentence sync | NOT RUN | no iOS/player runtime |
| AC-04 source rejection | Contract fixtures exist; real source preflight NOT RUN | fixtures 07, 12–16 |
| AC-05 recovery/idempotency | Existing contract fixture readback only | runtime/concurrency NOT RUN |
| AC-06 cache | 7-day value frozen; purge/runtime NOT RUN | D5 OPEN |
| AC-07 anonymous quota | Value frozen; enforcement NOT RUN | D4 runtime evidence pending |
| Translation quality ≥90% ratings at 4/5 | NOT RUN | verified corpus and staging absent |
| Release A success rate ≥90%, P95 preflight≤2s, ready≤60s | NOT RUN | provider/runtime absent |
| North Star `study_30s_reached` and secondary five-segment behavior | NOT RUN | no iOS/TestFlight/runtime; this decision package neither changes nor claims them |

## MVP scope delta

- P0 behavior is unchanged: Release A remains caption-only and keeps sentence
  synchronization as the launch floor.
- This memo narrows implementation to one metadata provider, one pinned LLM
  snapshot and one caption-only pipeline; it adds no user-visible behavior.
- Post-MVP scope is unchanged. No runtime/API integration, iOS work, M2/M3,
  longer-video support or Release B implementation was added.

## Release B machine-readable hold

`decision-ledger.json.releaseBDecisionCells` contains separate `D2-B` and
`D3-B` cells. Each requires `status=open_no_go`, non-empty owner/evidence/
unblock conditions/release impact and a timezone-aware deadline. The canonical
verifier rejects an empty or malformed cell. These cells authorize no STT,
audio acquisition, `transcribing` state or `transcriptSource=stt` path.

## Verification boundary

The gate verifier and Release A contract readback are deterministic contract
checks. Runtime/API provider calls, official `videos.list` preflight, approved
caption retrieval, LLM translation and billing, staging execution, latency,
success rate, translation review, synchronization, iOS build/tests, deployment
and TestFlight remain **NOT RUN**. They stay blocked by the named D2-A/D3-A
owners and deadlines; local PASS output must not be promoted to launch evidence.

## Reviewer challenge and stop conditions

`codex-vigil-pro` should fail the handoff if any of these is treated as PASS:

1. A YouTube captions badge is called proof of authorized caption-text access.
2. A candidate is called verified without the promotion evidence fields.
3. A passing local validator is called provider, quality, latency or runtime evidence.
4. `transcribing`, audio, STT or `transcriptSource=stt` appears in a Release A allowed path.
5. The USD 0.15 cap is reported as including unknown infrastructure or an unknown caption provider.
6. A replacement is longer than 900 seconds or results are mixed across corpus revisions.

## Open decisions and derived work

- Required derived issue: **Approve and prove a caption-text provider for
  arbitrary supported public videos** (recommended 5 SP; owner PO + legal +
  Uhura; due 2026-09-05). Abandon Release A M1 provider implementation if no
  compliant source is approved by the deadline; do not substitute scraping.
- Required derived issue after that gate: **Promote the 20 Release A candidates
  to verified and run the frozen quality/latency protocol** (recommended 5 SP;
  owner Hermione + R2D2; due 2026-09-08). It cannot start provider execution
  before the first issue is resolved.
- D1, D2-B and D3-B remain Release B open decisions only; no Release B work is
  authorized by this memo.
