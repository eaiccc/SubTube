# Release A API、State 與 Error Contract

- Issue：#1717
- 狀態：QA rework complete；ready for QA re-run
- Writer：`codex-vitruvius-pro`
- Reviewer handoff：`codex-vigil-pro`
- QA re-run handoff：`codex-hermione-pro`
- 範圍：MVP Release A caption-first path
- 機械契約：[`contracts/release-a/openapi.json`](../../contracts/release-a/openapi.json)
- Fixture 與 readback：[`contracts/release-a/fixtures`](../../contracts/release-a/fixtures)、[`verify_contract.py`](../../contracts/release-a/verify_contract.py)

本文把 PRD 的 Release A 行為凍結成 iOS、Backend 與 QA 可共同引用的規格。`MUST`／`MUST NOT` 是 #1717 的必要契約；標成 `OPEN` 的事項沒有以假設補齊。Release B 的 `transcribing`、STT/audio pipeline 與 `transcriptSource=stt` 不屬於本契約。

## 1. Normative scope 與 evidence

| 結論 | 規格依據 | 可打靶 evidence |
| :--- | :--- | :--- |
| Preflight 與 job creation 使用單一 `POST /v1/parse-jobs` | `PRD.md:93-100, 144-151, 215-231` | OpenAPI `createOrReuseParseJob`；fixtures 01、06–07、12–18 |
| Release A 只有 `queued → fetching_captions → translating → ready`，各 processing state 可到 `failed` | `PRD.md:153-173, 233-237` | OpenAPI `ProcessingStatus`；fixtures 01–04、08 |
| Release A 無字幕是 4xx `captions_unavailable`，無 job、audio、STT、LLM | `PRD.md:59-62, 175-181, 401-405` | fixture 06；verifier effect assertions |
| Client idempotency key 與 Server dedupe key 分離 | `PRD.md:202-208, 223-237` | fixtures 09–11、17–18；§5 invariants |
| Release A 只接受 `transcriptSource=caption`，`words=[]` 仍是成功 | `PRD.md:102-106, 179-190, 311-318` | OpenAPI `LearningDocument`；fixture 05 |
| Polling、background 與 resume 不得建立重複 job | `PRD.md:125-138, 169-173, 425-429` | §4 interaction matrix；§5 I-08–I-12 |

### 1.1 Contract precedence

1. `PRD.md` 是產品範圍 source of truth。
2. 本文凍結跨層語意、ownership、transition 與使用者出口。
3. `openapi.json` 凍結 wire shape、enum、nullability、HTTP response 與 error mapping。
4. Fixtures 凍結可重播範例；verifier 檢查 schema、Release B 排除、transition、retry、cache 與 sentence fallback。
5. 若四者衝突，implementation MUST 停止並交由 PO／Spec Gatekeeper 決定；不得由 iOS 或 Backend 單方容錯改寫產品語意。

## 2. Cross-layer state model

### 2.1 Ownership

| 資料／狀態 | 唯一 authoritative owner | Consumer | 規則 |
| :--- | :--- | :--- | :--- |
| URL draft、client validation、目前 route | iOS | UI | Client validation 只改善 UX，不取代 Server preflight。 |
| Pending submit record：request body、`Idempotency-Key`、是否已取得 definitive response | iOS persistent store | submit/resume coordinator | MUST 在第一次 network attempt 前原子保存；收到 definitive HTTP response 後才可標記 resolved。 |
| Job state、`updatedAt`、job error | Backend Job Store | iOS polling、worker | iOS 不自行推算 backend stage，不用 timeout 或 network error改成 `failed`。 |
| Dedupe key：`videoId + sourceLanguage + targetLanguage + pipelineVersion` | Backend | API、worker、result cache | Client 不產生、不傳送、不以 Video ID 代替 idempotency key。 |
| Caption／translation stage lease 與 checkpoint | Backend worker/queue | Backend API/observability | 同一 dedupe key 的 active work MUST 只有一個 owner；poll/replay 不啟動 provider。 |
| Ready `LearningDocument` 與 7-day success-cache target | Backend Result Cache | learning-data endpoint、iOS local recent cache | Result MUST 先持久化，再以同一 atomic completion 將 job 設為 `ready` 並填 path。7-day value 已做 contract readback；purge/runtime evidence 仍為 D5 OPEN／NOT RUN。 |
| 最近 5 支 learning documents | iOS local cache | Learning UI | 可離線讀文字；不代表 YouTube 影片可離線播放。 |
| Poll task、poll generation、transport error | iOS process memory | Processing UI | Polling 是 backend state 的 projection；transport error 不是 job state。 |
| Player time、manual-follow suppression、active sentence | iOS player/UI | subtitle list | 不寫回 Backend；`words=[]` 時照 sentence time seek。 |

### 2.2 Backend state machine

```text
POST preflight rejected ───────────────> APIError (no job)

POST accepted/reused
        │
        ├─ ready dedupe hit ───────────> existing ready snapshot
        ├─ in-flight dedupe hit ───────> existing processing snapshot
        └─ new job ─> queued ─> fetching_captions ─> translating ─> ready
                         │                │                 │
                         └────────────────┴─────────────────┴──────> failed
```

Backend state properties：

| State | Entry | Visible API output | Backend allowed action | Exit | Persisted data |
| :--- | :--- | :--- | :--- | :--- | :--- |
| No job / request rejected | POST fails URL/source/language/duration/embed/caption/target/request availability gate | 4xx/5xx `APIError`; no `jobId` | Return mapped error; record non-sensitive rejection telemetry | Terminal request result; a later user submit is a new request | Idempotency result ≥24h; no job/cache/downstream work |
| `queued` | Preflight and request gates pass; no reusable result exists | error fields/path `null`; `retryable=false` | Acquire the one active dedupe lease and schedule caption fetch | `fetching_captions` or `failed` | Job snapshot, dedupe key, pipeline version, timestamps |
| `fetching_captions` | Caption stage owns the job lease | Same null rules; stage label only, no fake percent | Fetch/parse verified English captions | `translating` or `failed` | Job snapshot and stage checkpoint; no audio/STT data |
| `translating` | Valid sentence segments exist | Same null rules | Translate in order; validate schema; malformed output may auto-retry once | `ready` or `failed` | Stable segment IDs/time axis and translation attempt evidence |
| `ready` | LearningDocument is validated and persisted | error fields `null`; `retryable=false`; non-null `learningDataPath` | Serve document/cache; emit `job_ready` once and `cache_hit` on reuse | Terminal | Ready job + successful result cache |
| `failed` | A processing stage reaches a terminal job error | non-null code/key; path `null`; mapped `retryable` | Serve failure; emit `job_failed` once; never expose as success cache | Terminal; user retry creates/reuses another job | Failed snapshot and sanitized failure evidence; no success cache |

There is no Release A `transcribing` state and no same-job `failed → queued` or `ready → processing` transition. Internal same-stage retries do not create a public state regression. A cache hit is reuse of an existing ready snapshot, not a new state.

### 2.3 iOS state map

| Client state | Entry | Visible output | Allowed actions | Exit | Persisted data |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `idle` | Input screen enters with no active request | URL field + submit | Edit, paste, submit, open a recent result | Valid submit → `submitting_preflight`; invalid submit → `invalid`; recent result → `loading_learning_data` | Draft optional; recent cache |
| `invalid` | Local syntax validation rejects empty/non-YouTube/missing ID | Inline `parse.error.invalidURL`; no loading/modal | Edit, paste, submit again, leave | Valid submit → `submitting_preflight`; edit may return `idle` | No key/job created |
| `submitting_preflight` | Valid submit; pending request persisted before POST | “正在檢查影片”; cancel/leave remains available; no percent | Leave; wait. Do not allow a second submit for this request | 2xx → mirrored processing/ready; 4xx/5xx → `request_error`; no response → `submit_uncertain` | Exact body + same key + unresolved marker |
| `submit_uncertain` | POST has no definitive HTTP response due cancellation/network/process loss | Connectivity/recovery message; no backend failure claim | Retry connection using **same** body/key; leave | Replay result → corresponding state; edit/new intent abandons active presentation but retains safe recovery record | Pending submit record, no assumed `jobId` |
| `processing(status)` | 2xx has job with queued/fetching/translating | Exact stage name and expected next stage; no percent | Leave; foreground polling every 3s | Newer matching snapshot; `ready`; `failed`; background/offscreen suspension | `jobId`, video summary, last accepted snapshot |
| `resuming` | Foreground/route restore/restart with active job or unresolved submit | “正在恢復處理狀態”; back/leave available | GET active job; or replay unresolved POST with same key | Processing/ready/failed/request error; transport loss remains recoverable | Active job or pending submit record |
| `request_error` | Definitive `APIError` from POST/GET, not a failed job snapshot | Localized key, safe details, permitted action | Back/edit always; retry only per §6 matrix | Retry creates new submit key except lookup GET retry; nonretryable returns to input | Sanitized code/status/Retry-After if present |
| `failed` | Authoritative job snapshot has `status=failed` | Localized job error; no loading | Back/edit; retry only when `retryable=true` | Retry → new pending submit/new key; back → idle | Failed job snapshot and original normalized URL needed for retry |
| `loading_learning_data` | Matching `ready` snapshot accepted | Loading document; leave/back | Retry GET on transport error; leave | Valid document → `learning_ready`; 404/410/API error → `request_error` | Job ID/path and last ready snapshot |
| `learning_ready` | Valid caption LearningDocument decoded | Player + bilingual sentence list | Play/pause, native scrub, manual scroll, sentence seek, toggle translation, leave | Leave/reopen; player failure degrades to static subtitles | Recent local document, player UI state as implementation choice |

Client state MUST NOT stay as a blocking modal without back/leave. Leaving a screen cancels its local poll task, not the backend job. Returning to a processing route restores by `jobId`; restarting with an unresolved POST first replays the same key to recover the lost response.

### 2.4 Client wire-model alignment

The PRD Swift names are not wire-identical. iOS MUST define explicit `CodingKeys`: `ProcessingJob.id ↔ jobId`, `ProcessingJob.videoID ↔ videoId`, and `LearningDocument.videoID ↔ videoId`. `updatedAt` uses an RFC 3339/ISO-8601 decoder. The wire requires a non-null duration in a successful POST/job snapshot, while nullable title remains valid; the current optional Swift properties may decode this stricter server response. Release A may retain `transcribing`/`stt` in future-compatible source enums, but the Release A reducer and fixtures MUST reject either as a valid Release A route/result.

## 3. Transition invariants

| ID | Invariant | Target |
| :--- | :--- | :--- |
| I-01 | Every definitive POST `APIError` means no job was created. A preflight rejection MUST be 4xx, MUST NOT include `jobId`, and MUST assert `captionPipelineStarts=0`、`translationCalls=0`、`audioDownloads=0`、`sttCalls=0`. Source metadata/caption availability lookup remains part of preflight. If job creation committed but delivery was lost, the client receives no definitive HTTP response and recovers with the same key. | Fixtures 06–07、12–16、18 + downstream mutation probe |
| I-02 | Release A status enum is exactly `queued`, `fetching_captions`, `translating`, `ready`, `failed`. Unknown status MUST fail decoding visibly/observably; it MUST NOT be mapped to ready. | Shared decoding tests |
| I-03 | Processing states have `errorCode=null`, `errorMessageKey=null`, `retryable=false`, `learningDataPath=null`. | Schema branch tests |
| I-04 | `ready` has null error fields, `retryable=false`, and a non-null learning path. The referenced document MUST already exist and validate. | Transaction/integration test |
| I-05 | `failed` has a mapped non-null code/key, path null, and exact retryability. Failed jobs MUST NOT be written/read as success cache. | Worker/store tests + fixture 08 |
| I-06 | `ready` and `failed` are terminal for a job ID. Retry never mutates a failed job back to processing. | State transition tests |
| I-07 | One normal transition chain MUST preserve `jobId` and `videoId`; each `updatedAt` MUST be RFC 3339 with timezone and strictly increase. iOS accepts a poll result only if job ID and local poll generation match, and never replaces a newer snapshot with an older/equal one. | Fixtures 01–04 + mismatched-ID/non-monotonic/timezone-less mutation probes |
| I-08 | The pending POST body/key MUST be persisted before sending. No HTTP response/network cancellation leaves it unresolved; recovery uses the same key. | iOS persistence/restart tests |
| I-09 | A definitive response resolves an idempotent request. A user-initiated resubmit/retry then uses a new UUID. | iOS request coordinator tests + fixtures 09/11 |
| I-10 | Same key + same canonical request returns the same HTTP status, headers and body for ≥24h, even if the underlying job later advances. Same key + different canonical body returns `409 idempotency_conflict` with zero downstream effects. | Fixtures 11、18 |
| I-11 | Different keys with one ready/in-flight dedupe key return its existing job; in-flight requests converge on one owner/job ID and exactly one caption pipeline start. | Fixtures 10、17 |
| I-12 | A retryable failed dedupe result is not success reuse. Fresh retry MUST assert exactly one outcome: create one new job, or reuse an already-existing newer in-flight/ready owner; returning the prior failed job or asserting neither is invalid. | Fixture 09 + retry-without-owner mutation probe |
| I-13 | Background, leave, poll cancellation, poll timeout, offline state, and GET transport failure only affect iOS polling; they do not mutate backend job state or generate a new POST. | iOS lifecycle tests |
| I-14 | A response from an abandoned submit/job/poll generation is stale: it may update durable recovery storage, but MUST NOT navigate or overwrite the currently visible intent. | iOS reducer race tests |
| I-15 | Translation keeps stable server IDs, sentence order, and original time axis. Invalid/missing fields, invalid time ranges, or count mismatch get at most one automatic translation retry, then `translation_invalid_response`. | Backend schema/worker tests |
| I-16 | `words=[]` is valid. Its effect oracle MUST assert `sentenceSeekEnabled=true` and `wordHighlightEnabled=false`; Client keeps sentence highlight/seek from segment times and disables only word highlight. | Fixture 05 + seek-disabled/word-highlight-enabled mutation probes |
| I-17 | Every Release A fixture/path MUST explicitly assert `audioDownloads=0` and `sttCalls=0`; Release A also rejects `transcribing`/`transcriptSource=stt`. | All 18 fixtures + success-audio mutation probe |
| I-18 | Polling a nonterminal job occurs every 3 seconds only while its processing view is active and app is foreground. Foreground resumes with an immediate GET before the next interval. | iOS clock/lifecycle tests |
| I-19 | Normal success stage effects are fixed: queued=`caption=false/translation=false`; fetching=`true/false`; translating and ready=`true/true`. Every successful fixture MUST have a case-specific effect oracle; missing or contradictory flags fail readback. | Fixtures 01–04、09–11、17 + false-caption-stage mutation probe |

## 4. Interaction and async matrix

| Interaction / event | Starting condition | iOS action | Backend effect | User-visible result / exit | Required test |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Submit valid URL | `idle`/`invalid`, no active intent | Persist body + new UUID, then POST once | Idempotency lookup, server preflight, dedupe reuse or create | Processing/ready/error; leave always available | Request persistence order; fixture 01 |
| Submit while submit is pending | `submitting_preflight` | Disable duplicate submit for that intent | No second request | Existing loading state; leave available | Double-tap test |
| Client-local invalid URL | `idle` | Do not call API | None | Inline error; edit/back | URL reducer test |
| Preflight reject | POST receives 4xx | Resolve pending request; do not create ProcessingJob | No job or downstream caption/translation/audio/STT pipeline | Localized error; back/edit; retry only if mapped | Fixtures 06–07、12–16、18 |
| Leave during POST with no response | `submitting_preflight` | Cancel view task but retain unresolved request | Request may or may not have completed | No blocking modal; later same-key recovery | Lost-response race test |
| Leave during processing | Mirrored nonterminal job | Stop route poll; persist job ID | Worker continues | User returns elsewhere; reopen resumes | Lifecycle test |
| Background | POST/poll/learning GET active | Stop periodic poll; persist recovery state | Job continues; no cancel endpoint | No duplicate job | Background clock test |
| Foreground | Active job exists | Enter `resuming`; immediate GET, then 3s cadence if nonterminal | Read only | Latest stage/ready/failed | Foreground resume test |
| App restart with job ID | Durable active job | GET job; never POST | Read only | Restored processing/result/failure | Cold launch test |
| App restart with unresolved POST | Durable body/key, no job ID | Replay exact POST with same key | Exact replay/reuse; one job max | Recover job/error | Kill-after-send test + fixture 11 |
| Network loss during polling | Processing | Show connectivity recovery state; suspend/backoff transport; preserve job snapshot | None | No fake failed state; back available | Offline/recovery reducer test |
| Network recovers | Active job still relevant | Immediate GET; restart 3s cadence | Read only | Catch up, possibly directly ready/failed | Recovery clock test |
| Poll response arrives after leave/new submit | Generation mismatch | Ignore for navigation/current view | None | Current intent unchanged | Stale result race test |
| Job provider failure | Poll returns `status=failed` | Stop polling; render mapped error | Terminal failed snapshot; no success cache | Retry only if true; back/edit always | Fixture 08 |
| User retries failed job | `failed`, retryable true | Same URL/body semantics, new UUID | Reuse newer ready/inflight or create one new job | New processing/ready/error | Fixture 09 + concurrency test |
| Ready cache hit | New key, same dedupe key has ready result | Accept HTTP 200 ready then GET path | No caption/translation/STT call; emit `cache_hit` | Learning data load | Fixture 10 |
| In-flight reuse | New key, same dedupe key active | Mirror returned existing job ID; one poll loop | Converge on one active owner and one caption pipeline start | Existing stage | Fixture 17 |
| Learning-data transport failure | Job remains ready | Retry GET path; do not POST | Read only | Recoverable data-loading error; back | Endpoint retry test |
| `words=[]` | Learning data valid | Render sentence list and seek by `startTime`; no word highlight | None | Full sentence-level learning path | Fixture 05 |
| Sentence seek | `learning_ready` | Seek to segment `startTime`; restore auto-follow | None | Active sentence follows player time | Player fixture/UI test |
| Manual scroll | `learning_ready` | Suspend auto-follow | None | List does not snap back | UI reducer test |
| Play/replay or return to learning page | Manual-follow suspended | Restore auto-follow | None | Current sentence follows playback | UI reducer test |
| Player time unavailable | Learning document loaded | Disable active-time updates; keep static bilingual list | None | No crash/dead end; back available | Player disconnect test |

### 4.1 Modal and dead-end checklist

| Surface | Exit required | Retry semantics | Forbidden dead-end |
| :--- | :--- | :--- | :--- |
| Submit/preflight loading | Back/leave | Lost response uses same key; no second submit button | Uncancelable modal or duplicate POST |
| Processing loading | Back/leave | No user retry while authoritative job is nonterminal | Fake percentage, infinite screen with no route exit |
| Connectivity interruption | Back/leave + reconnect | GET or same-key unresolved replay, never fresh POST | Converting offline to job failed |
| Preflight/request error | Back/edit always | Respect mapped retryability and `Retry-After` | Retry button on permanently unsupported input |
| Failed job | Back/edit always | Only `retryable=true`; fresh key | Failed card that has neither exit nor actionable explanation |
| Learning-data loading/error | Back/leave | Retry GET only | Re-running parse because result GET failed |
| Player unavailable | Back/leave | Player reload is implementation-local | Hiding already-valid subtitles or crashing |

There is no backend cancel endpoint in Release A. “Leave” is a presentation/poll cancellation only; adding task cancellation requires a separate product/API decision.

## 5. Async, idempotency, dedupe, cache

### 5.1 Request identity

- Client `Idempotency-Key` identifies one logical POST attempt and is a UUID.
- Client MUST persist `{body, key, unresolved}` before network send.
- If delivery outcome is unknown, retry transport with the same body and key.
- After any definitive HTTP response, a later explicit submit/retry uses a new key.
- The request fingerprint canonicalizes JSON member ordering/whitespace but preserves the exact `url` and `targetLanguage` string values. Reusing one key with changed values is a conflict even when two URLs normalize to the same Video ID.
- Server stores the exact logical response for at least 24 hours. Replay returns the stored HTTP status, headers, and body, not a newly sampled job snapshot.
- Same key with a different canonical request is `409 idempotency_conflict`; no job/provider work starts.

### 5.2 Work identity

- Server derives `dedupeKey = videoId + "|en|zh-Hant-TW|" + pipelineVersion` after normalization/preflight facts are available.
- A ready dedupe hit returns HTTP 200 with the existing ready `jobId` and path.
- An in-flight dedupe hit returns HTTP 202 with the existing `jobId` and current nonterminal snapshot.
- Dedupe ownership MUST be atomic under concurrent POSTs; exactly one active job may schedule each stage.
- A failed job is not a ready cache entry. A valid retry can create one new job, while concurrent retry races converge on the new in-flight owner.
- `pipelineVersion` change creates a different dedupe/cache identity.

### 5.3 Polling and stale result rule

- GET is read-only and never advances/restarts a job by itself.
- iOS keys every async response by `intentGeneration + jobId` (or pending request key before job ID exists).
- A result may affect visible navigation only when its generation and identity still match.
- For matching job snapshots, lower `updatedAt` cannot replace a higher accepted value. Equal timestamp with conflicting payload is a server invariant violation and MUST be logged, not silently selected.
- `ready` triggers learning-data GET once per active generation. Multiple UI callbacks MUST coalesce to one load task.

## 6. Error-path matrix

The exact machine mapping is `openapi.json#/x-error-contract`. Request/preflight errors are `APIError`; background job errors are HTTP 200 `ProcessingJob(status=failed)`.

| `errorCode` | HTTP / phase | Message key | Retryable | Required user action / backend effect |
| :--- | :--- | :--- | :---: | :--- |
| `invalid_url` | 400 preflight | `parse.error.invalidURL` | no | Edit URL; no job or downstream work |
| `idempotency_conflict` | 409 request | `parse.error.idempotencyConflict` | no | Start a new logical submit with a new UUID; server logs misuse |
| `unsupported_source` | 422 preflight | `parse.error.unsupportedSource` | no | Edit URL/back; no job |
| `video_private` | 422 preflight | `parse.error.privateVideo` | no | Choose a public video; no job |
| `video_live` | 422 preflight | `parse.error.liveVideo` | no | Choose a non-live video; no job |
| `video_not_embeddable` | 422 preflight | `parse.error.notEmbeddable` | no | Choose another video; no job |
| `video_too_long` | 422 preflight | `parse.error.videoTooLong` | no | Choose ≤15-minute video; no job |
| `non_english` | 422 preflight | `parse.error.nonEnglish` | no | Choose English content; no job |
| `captions_unavailable` | 422 preflight | `parse.error.captionsUnavailable` | no | Choose captioned video; zero audio/STT/LLM |
| `unsupported_target_language` | 422 preflight | `parse.error.unsupportedTargetLanguage` | no | Client contract bug; Release A only supports `zh-Hant-TW` |
| `rate_limited` | 429 request | `parse.error.rateLimited` | yes | Show `Retry-After`; new key only after wait; no job/downstream work |
| `quota_exceeded` | 429 request | `parse.error.quotaExceeded` | no | Show reset interval from `Retry-After`; no retry before reset |
| `concurrent_job_limit` | 429 request | `parse.error.concurrentJobLimit` | yes | Return to existing job or wait per `Retry-After`; no new job |
| `caption_fetch_failed` | 200 failed job | `parse.error.captionFetchFailed` | yes | Fresh-key retry; never run STT in A |
| `translation_provider_failed` | 200 failed job | `parse.error.translationProviderFailed` | yes | Fresh-key retry after provider failure |
| `translation_invalid_response` | 200 failed job | `parse.error.translationInvalidResponse` | yes | Emitted only after at most one automatic schema retry |
| `processing_timeout` | 200 failed job | `parse.error.processingTimeout` | yes | Stop infinite loading; allow fresh-key retry |
| `cost_limit_exceeded` | 200 failed job | `parse.error.costLimitExceeded` | no | Explain limit; no retry button |
| `processing_internal_error` | 200 failed job | `parse.error.processingInternal` | yes | Fresh-key retry; sanitized logging |
| `internal_error` | 500 request | `parse.error.internal` | yes | Definitive request error; later retry uses new key |
| `service_unavailable` | 503 request | `parse.error.serviceUnavailable` | yes | Later retry uses new key; no assumed job unless response was absent |
| `job_not_found` | 404 lookup | `parse.error.jobNotFound` | no | End stale recovery record; offer back/new submit, not repeated GET |
| `learning_data_not_found` | 404 lookup | `parse.error.learningDataNotFound` | yes | Retry learning-data GET; alert backend invariant if job is ready |
| `learning_data_expired` | 410 lookup | `parse.error.learningDataExpired` | no | Remove stale local path; offer a new submit |

Transport errors have no `errorCode`: timeout/offline/TLS/cancelled-before-response remain client recovery states. They MUST NOT be decoded as `internal_error`, `service_unavailable`, or job `failed`.

## 7. AC matrix

| AC | Frozen assertion | Fixture/readback | Runtime status |
| :--- | :--- | :--- | :--- |
| AC-01 | One POST yields summary/job, then polling follows caption-only states to ready; stage flags match queued/fetching/translating/ready; every Release A path has zero audio/STT | Fixtures 01–05 + nine-success-oracle readback PASS | End-to-end/provider/latency `NOT RUN` |
| AC-02A | Captionless Release A request returns 422 `captions_unavailable`, false, no job/audio/STT/LLM | Fixture 06 semantic assertions PASS | Real YouTube/provider `NOT RUN` |
| AC-03 | With `words=[]`, sentence seek remains enabled and word highlight is disabled | Fixture 05 + both fallback mutation probes PASS | Player seek/sync runtime `NOT RUN` |
| AC-04 | `invalid_url`、private、live、not embeddable、non-English、too-long each return mapped 4xx APIError with no job/downstream | Fixtures 07、12–16 + zero-effect mutation readback PASS | Real source preflight `NOT RUN` |
| AC-05 | Poll/foreground/restart recover existing job; unknown delivery exact-replays; different keys converge on one in-flight owner; changed body conflicts; retry creates/reuses a newer owner | Fixtures 08–11、17–18 + identity/retry mutation readback PASS | iOS lifecycle/backend concurrency `NOT RUN` |
| AC-06 (supporting #1717) | Ready dedupe hit returns existing ready job and zero provider calls; success-cache target is 7 days | Fixture 10 + 7-day contract value readback PASS | Cache integration/event/purge enforcement **D5 OPEN / NOT RUN** |

## 8. Open decisions and spec gaps

| ID | State | Owner / blocker | What is frozen now | Missing evidence / impact |
| :--- | :--- | :--- | :--- | :--- |
| D2-A | **BLOCKED / OPEN** | PO + Uhura + R2D2; blocks Release A M1 provider execution | Adapter-neutral caption/translation states and errors; `cost_limit_exceeded` shape | Caption provider, LLM provider, model/version, timeout and per-job cost cap are not selected (`PRD.md:532-539`) |
| D3-A | **BLOCKED / OPEN** | PO + QA; blocks Release A quality/latency claim | Deterministic synthetic fixtures and contract readback | 20 standardized Release A videos, 2 language reviewers and test environment do not exist (`PRD.md:532-539`) |
| D5-A | **BLOCKED / OPEN** | Uhura + R2D2; blocks cache-retention evidence, not this contract readback | `successDays=7` is frozen and machine-read back | No backend store, daily purge job, deletion log, clock-controlled test, or runtime exists; 7-day enforcement MUST remain `NOT RUN` (`PRD.md:536`) |
| SG-01 | OPEN | PO + Backend + iOS | `APIError` has only code/key/retryable; 429 has `Retry-After` | Installation token transport/header and reset timestamp representation are not defined; do not invent a header |
| SG-02 | OPEN | Backend + Product | `processing_timeout` is retryable and terminal | Timeout threshold and stage-specific budget are unspecified; no fake client timer may fail the job |
| SG-03 | OPEN | Backend + iOS | Job lookup returns `job_not_found`; learning cache expires at 7 days per PRD | ProcessingJob retention duration is unspecified, so restart-after-job-expiry behavior cannot be runtime-verified |
| SG-04 | OPEN | iOS + Product/UX | Exit/retry semantics and message keys are frozen | Localized Traditional Chinese copy, accessibility labels, and visual component are not authored |
| SG-05 | OPEN | Backend/Analytics | Backend records `cache_hit`; response stays ProcessingJob with no invented field | Client has no contract field to distinguish ready cache hit from ordinary ready; client-side cache-hit UI/analytics is not specified |
| SG-06 | OPEN | Backend | IDs are stable strings and path is relative | Concrete ID format and API base URL/environment configuration are implementation choices, not frozen here |

D1 and STT portions of D2/D3 block Release B only. They do not permit any Release A audio/STT behavior and are intentionally outside #1717.

## 9. Implementation and test handoff

### Backend

- Generate request/response models from or validate against `openapi.json`.
- Implement atomic idempotency-result storage, dedupe ownership, stage transitions, and ready-result persistence ordering.
- Write table-driven tests for all `x-error-contract` rows and concurrency tests for I-10–I-12.
- Instrument provider call counters so fixture effects (especially zero STT/audio calls) are observable without content logging.

### iOS

- Keep network DTO status enum Release A-compatible while treating the PRD client enum as a future superset; never route `transcribing` in Release A.
- Implement a reducer/state owner that separates authoritative job failure from local transport/recovery state.
- Persist pending submit before send; use generation/job identity to reject stale callbacks.
- Test background, foreground, leave, cold restart, kill-after-send, empty words, and sentence seek.

### QA / contract tests

- Canonical command: `python3 contracts/release-a/verify_contract.py`.
- Preserve regression probes for successful-path audio download, false caption-stage flag, disabled sentence seek, enabled word highlight, mismatched transition job ID, non-monotonic/timezone-less `updatedAt`, AC-04 downstream effects, retry without a new/newer owner, nullability, `transcribing`, `stt`, missing words/error, duplicate IDs, invalid time ranges, same-key/different-body, and stale responses.
- Provider/runtime evidence remains blocked until D2-A/D3-A and runtime/build tooling exist.

### Reviewer (`codex-vigil-pro`) challenge checklist

1. Confirm the OpenAPI status/transcript enums contain no Release B-required path.
2. Challenge every preflight error for “no job/no downstream pipeline” and every UI error/loading surface for an exit.
3. Challenge same-key lost-response recovery versus fresh-key user retry; they are intentionally different.
4. Challenge ready persistence atomicity, failed cache exclusion, concurrent dedupe ownership, and stale-result suppression.
5. Confirm 7-day cache value is only contract-readback PASS while purge/runtime proof remains D5 OPEN／NOT RUN.
6. Confirm all added wire/error decisions are compatible with the PRD; route any disagreement as an open decision, not permissive implementation behavior.

### QA re-run (`codex-hermione-pro`) focus

1. Mutate fixture 01 to `audioDownloads=1`; canonical verifier MUST fail.
2. Mutate fixture 02 to `captionPipelineStarted=false`; canonical verifier MUST fail.
3. Mutate fixture 05 to `sentenceSeekEnabled=false`; canonical verifier MUST fail.
4. Mutate fixture 05 to `wordHighlightEnabled=true`; canonical verifier MUST fail.
5. Confirm the unmodified package passes while D5 purge/runtime remains OPEN／NOT RUN.

## 10. Evidence status

- Contract JSON parse: run by `verify_contract.py`.
- 18 fixture schema/semantic readback、9 successful-fixture effect oracles and mutation regression probes: run by `verify_contract.py`.
- 7-day cache value: **contract readback PASS; purge/runtime enforcement D5 OPEN / NOT RUN.**
- Runtime/API server: **NOT RUN — this checkout has no runtime or canonical command.**
- iOS build/unit/UI tests: **NOT RUN — no Xcode project/scheme or canonical command exists.**
- Caption/LLM/STT provider: **NOT RUN — D2 unresolved and no provider runtime exists.**
- Latency/success/translation quality/synchronization: **NOT RUN — D3 Release A corpus/review environment absent.**
- Success-cache purge/TTL enforcement: **NOT RUN — D5 backend/purge/runtime evidence absent.**
- TestFlight/deployment: **NOT RUN — deployment tooling does not exist.**
