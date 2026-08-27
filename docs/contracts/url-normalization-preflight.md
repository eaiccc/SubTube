# #1725 URL normalization and preflight rejection gate

- Writer：`codex-uhura-pro`
- Reviewer handoff：`codex-spock-review-pro`
- Scope：MVP-01、MVP-02 preflight、AC-01、AC-02A、AC-04
- Dependency：#1717 closed Release A contract; consumed read-only
- Machine contract：[`contracts/url-preflight/policy.json`](../../contracts/url-preflight/policy.json)
- Schemas／fixtures／readback：[`contracts/url-preflight`](../../contracts/url-preflight)
- Excluded：#1727 parse-job worker/state/polling implementation、Release B STT/audio path、runtime/provider claims

This package fills the implementation-ready seam that #1717 intentionally left open: parsing the two PRD URL forms, producing deterministic preflight decisions, proving rejection side effects are zero, and handing the normalized identity to the frozen idempotency/dedupe contract. It does not change `contracts/release-a/**` or `docs/contracts/release-a-contract.md`.

## 1. Normative sources and boundary

| Contract statement | Source | #1725 evidence |
| :--- | :--- | :--- |
| Accept `youtube.com/watch?v=` and `youtu.be/`, extract a Video ID, and remove tracking data | `PRD.md:93-99, 144-151` | `policy.json#/normalization`; normalization fixtures |
| One POST performs server-authoritative preflight and creates a job only after all gates pass | `PRD.md:126-138, 144-173, 215-231` | `policy.json#/requestOrder`; preflight fixtures |
| Release A requires public, non-live, embeddable, English, ≤900-second video with parseable English captions | `PRD.md:76-83, 93-100, 175-181` | eight preflight cases including 900/900.001 boundaries |
| Rejected preflight returns frozen 4xx `APIError`, no job, audio, STT, or LLM | `PRD.md:135-138, 149-151, 395-423` | APIError compatibility readback and zero-effect mutation probe |
| Idempotency raw request identity differs from normalized work identity | `PRD.md:223-231`; `docs/contracts/release-a-contract.md:180-207` | three handoff fixtures |
| `cost_limit_exceeded` is a job error, not preflight 4xx | Frozen OpenAPI `x-error-contract`; `docs/contracts/release-a-contract.md:229-255` | provider-entry guard fixture; no #1727 transition added |

If the PRD, #1717 frozen OpenAPI, or this package disagree, implementation stops for PO／Spec Gatekeeper review. #1725 does not override the frozen wire shape.

## 2. Service and data-flow architecture

```text
POST /v1/parse-jobs (raw body + Idempotency-Key)
  │
  ├─ 1. Idempotency lookup
  │     ├─ same key + same raw-body fingerprint → exact stored response
  │     └─ same key + changed raw-body value → 409 idempotency_conflict
  │
  ├─ 2. Request schema/target + rate/quota/concurrency gates
  │     └─ rejection → APIError, no source probe/job/downstream work
  │
  ├─ 3. URL normalizer (pure; never fetches the submitted URL)
  │     └─ {videoId, canonicalUrl}; raw URL remains the idempotency value
  │
  ├─ 4. Source adapter preflight
  │     ├─ metadata → public / non-live / embeddable / duration / language
  │     └─ captions → available + parseable English track
  │
  ├─ rejection → frozen 4xx APIError; no job/audio/STT/LLM
  │
  └─ acceptance
        ├─ derive videoId|en|zh-Hant-TW|pipelineVersion
        ├─ atomically reuse ready/in-flight owner or create one queued job
        └─ hand off to #1727 (not implemented here)
```

The URL normalizer emits an identifier only. A future source adapter constructs its own provider request from that Video ID; it must not follow an arbitrary user-supplied host, redirect, credential, or port. Preflight source metadata/caption probes are synchronous facts for the same POST. The asynchronous caption/translation pipeline starts only after acceptance and atomic ownership.

### 2.1 URL normalization contract

| Input class | Decision | Output / error |
| :--- | :--- | :--- |
| `https://youtube.com/watch?v={id}` or `https://www.youtube.com/watch?v={id}` | Accept | `{id}` plus `https://www.youtube.com/watch?v={id}` |
| `https://youtu.be/{id}` | Accept | Same normalized output |
| Tracking query or fragment on either accepted form | Remove from canonical URL | Original string remains in idempotency fingerprint |
| Blank, malformed, missing/duplicate `v`, empty/extra short-link path, invalid ID | Reject | `400 invalid_url` |
| A syntactically valid HTTPS URL on any non-allowlisted host, including deceptive suffix hosts | Reject | `422 unsupported_source` |

The #1725 Video ID syntax is exactly 11 characters matching `[A-Za-z0-9_-]`. Only the two HTTPS forms above are supported now. Mobile/music/embed/shorts hosts and non-HTTPS schemes are UP-01 open scope, not permissive aliases. Query order/whitespace is canonicalized only for the idempotency request fingerprint; the exact string values, including URL tracking parameters, remain significant per #1717.

### 2.2 Preflight facts and deterministic precedence

One metadata response may carry all source facts, but the selected error is deterministic:

| Order | Gate | Accept condition | Rejection |
| :---: | :--- | :--- | :--- |
| 1 | Visibility | `public` | `422 video_private` |
| 2 | Live | `isLive=false` | `422 video_live` |
| 3 | Embeddability | `embeddable=true` | `422 video_not_embeddable` |
| 4 | Duration | `0 < durationSeconds <= 900` | `422 video_too_long` |
| 5 | Source language | `en` | `422 non_english` |
| 6 | Caption availability | available, parseable, English | `422 captions_unavailable` |

For gates 1–5, caption availability is not probed after rejection. Every rejection returns only frozen `APIError`; `jobId` is absent and effects are `jobCreated=false`, `captionPipelineStarts=0`, `translationCalls=0`, `audioDownloads=0`, `sttCalls=0`. Metadata/caption lookup counters are tracked separately because they are preflight probes, not asynchronous processing.

### 2.3 Idempotency and dedupe handoff

| Identity | Inputs | Consequence |
| :--- | :--- | :--- |
| Request fingerprint | Canonical JSON structure while preserving exact `url` and `targetLanguage` string values | Same key/same body exact-replays ≥24h; changed URL string conflicts even if normalization would yield the same Video ID |
| Work dedupe key | `videoId + en + zh-Hant-TW + pipelineVersion` | Different keys and standard/short URL forms converge on one ready/in-flight owner |

The idempotency lookup precedes normalization. Therefore a same-key changed URL gets `409 idempotency_conflict` without a second normalization, source probe, or job/provider side effect. A new user intent uses a new UUID; unknown delivery exact-replays the same body/key, as frozen by #1717.

## 3. Failure and retry matrix

| Failure | Wire result | Retry | Job / provider effects |
| :--- | :--- | :--- | :--- |
| Blank/malformed/missing/ambiguous Video ID | `400 invalid_url`, nonretryable | User edits; later submit uses new key | No source probe, job, caption pipeline, audio, STT, LLM |
| Non-YouTube/deceptive host | `422 unsupported_source`, nonretryable | User chooses supported URL | Same zero effects |
| Private/live/not embeddable/>900s/non-English | Corresponding frozen `422`, nonretryable | User chooses another video | One metadata probe; no caption probe after failed metadata gate; no job/downstream |
| Caption absent or unparseable | `422 captions_unavailable`, nonretryable | Choose captioned video; Release A never falls back to STT | Metadata + caption availability probe only; no job/audio/STT/LLM |
| Quota denied | `429 quota_exceeded` with required positive-integer `Retry-After`, nonretryable until reset | Follow reset interval; installation-token/reset timestamp representation remains SG-01 open | Runs before source probe; no job/downstream |
| Same key, changed raw request | `409 idempotency_conflict`, nonretryable | New logical submit/new UUID | No second normalization/preflight/job/downstream |
| Unknown delivery, same key/body | Exact stored replay | Retry transport with same key/body | No duplicated source/job/provider work |
| Cost policy denies existing job | HTTP 200 `ProcessingJob(status=failed, cost_limit_exceeded)`, nonretryable | No retry button | Existing job may exist; gate must precede asynchronous caption/translation provider; threshold is D2 OPEN |

Preflight failures are deterministic and are not automatically retried inside the POST. Transport failure without a definitive response is not an APIError; the client follows #1717 same-key recovery. Source adapter timeout/error mapping remains outside these deterministic fixtures because the provider and timeout budget are D2-A open.

## 4. Security, retention, and cost analysis

- SSRF/source boundary: exact host/path/scheme allowlist, no host suffix matching, no userinfo or explicit port, no arbitrary submitted-URL fetch. The source adapter receives only the validated Video ID.
- Redirect/bypass boundary: no IP rotation and no redirect-following rule is granted by this package. Private, login-gated, live, DRM, and non-embeddable content remain unsupported.
- Secrets: no provider secret exists in these artifacts. A runtime must keep source/caption/LLM secrets server-side and redact them from errors/logs.
- Data minimization: telemetry may record normalized Video ID, decision/error code, adapter/pipeline version, latency, and counters. Do not log raw URLs with tracking tokens, full Idempotency-Key values, caption content, or secrets.
- Release A retention: every fixture asserts zero audio/STT. The raw-audio 24h TTL is therefore not exercised by #1725; D5 remains runtime `NOT RUN`.
- Cost: normalization is pure; rejected syntax/source and quota cases spend no source/provider call. Source preflight may spend one metadata and one caption availability probe. Concrete providers, prices, timeout, pipeline version, and the cost cap are D2-A open, so no per-request currency claim is made.
- Cost guard compatibility: frozen #1717 classifies `cost_limit_exceeded` as a failed job. #1725 verifies zero asynchronous provider entry after denial but does not define or implement a #1727 transition.

## 5. Load and integration test plan

| Layer | Planned test | Pass criterion | Current evidence |
| :--- | :--- | :--- | :--- |
| Contract/readback | Run both #1725 and frozen #1717 verifiers | Both exit 0; all required fixtures and negative mutations pass | Run locally; see §6 |
| URL parser property/fuzz | Generate valid 11-char IDs, tracking permutations, Unicode/deceptive hosts, duplicate query keys, path/port/userinfo mutations | No crash; only exact forms accepted; canonical output stable | `NOT RUN` — no production parser/runtime |
| Fake adapter integration | Table-drive every preflight fact and multi-failure precedence with call counters | Exact error; no caption probe after metadata rejection; no job/downstream | Contract fixtures PASS; service integration `NOT RUN` |
| Idempotency concurrency | 100 concurrent requests: same key/body, same key/changed body, and different keys/same Video ID | One exact response per key, conflict for changed body, one active dedupe owner | `NOT RUN` — no store/queue runtime |
| Failure injection | Metadata timeout/malformed response, caption parse failure, quota race, cost-policy denial | Bounded timeout/error; zero forbidden provider calls; no orphan job on preflight 4xx | `NOT RUN` — D2/runtime absent |
| Real source corpus | D3-A 20 public/non-live/embeddable English captioned videos plus rejection corpus | Preflight P95 ≤2s and accepted/rejected facts independently audited | `NOT RUN` — D3-A corpus/environment absent |
| Security integration | Redirect/DNS rebinding/arbitrary-host attempts and sanitized-log inspection | No arbitrary fetch; no raw tracking token/key/secret in logs | `NOT RUN` — no adapter/logging runtime |

## 6. AC and evidence matrix

| AC | Assertion | Fixture/readback evidence | Runtime status |
| :--- | :--- | :--- | :--- |
| MVP-01 | Standard and short URL → same 11-char Video ID/canonical URL; tracking removed; blank/non-source/missing/duplicate ID rejected | `fixtures/normalization.json`; verifier normalization mutation PASS | Production parser/client validation `NOT RUN` |
| AC-01 | Public, non-live, embeddable, English, parseable-caption video at 900s returns HTTP 202 queued job summary | `public_captioned_english_900_seconds_is_accepted`; frozen ProcessingJob validation PASS | API/provider/ready/player/latency portions `NOT RUN` |
| AC-02A | Caption absent or unparseable returns `422 captions_unavailable`, false, no job/audio/STT/LLM | Two caption cases + side-effect mutation rejection PASS | Real caption provider `NOT RUN` |
| AC-04 | Invalid source/private/live/not embeddable/non-English/>900s return exact frozen 4xx APIError and zero downstream work | Normalization + six preflight rejection families PASS | Real source preflight/localized UI `NOT RUN` |
| Idempotency/dedupe support | Exact replay, equivalent changed-body conflict, and different-key equivalent-URL convergence are distinct | Three handoff fixtures PASS | Store/concurrency/cache integration `NOT RUN` |
| Quota/cost support | Quota rejects before source probe with frozen required `Retry-After`; cost denial stays job-level and starts no async provider | Two provider-entry guard fixtures plus missing-header/provider-start mutations PASS | D2/D4/runtime enforcement `NOT RUN` |

Canonical commands:

```bash
python3 contracts/url-preflight/verify_contract.py
python3 contracts/release-a/verify_contract.py
python3 -m py_compile contracts/url-preflight/verify_contract.py
```

The #1725 verifier reads and checks frozen `contracts/release-a/openapi.json` but does not write any #1717 artifact. In a checkout without Git metadata, compare SHA-256 before/after for explicit immutability evidence.

## 7. Open decisions

| ID | State / owner | Missing decision | Impact |
| :--- | :--- | :--- | :--- |
| D2-A | **OPEN** — PO + Uhura + R2D2 | Caption/LLM provider, timeout, release pipeline version, per-job cap | Blocks real probes, cost, timeout, provider failure, and currency evidence; does not block deterministic contract fixtures |
| D3-A | **OPEN** — PO + QA | 20-video Release A corpus and environment | Blocks real P95, source compatibility, and success-rate claim |
| D4 / SG-01 | **OPEN** — PO + R2D2 + iOS | Installation-token transport and quota reset representation | Frozen 429 code/Retry-After exists; runtime request identity remains undefined |
| UP-01 | **OPEN** — PO | Whether mobile/music/embed/shorts URL forms or non-HTTPS schemes are added | Current parser must reject them; adding support is a separate explicit product decision |
| UP-02 | **OPEN** — Backend + PO | Authoritative metadata/caption adapter and English/parseability signals | Runtime may not invent provider semantics from fixture facts |

## 8. NOT RUN ledger

- Backend/API runtime and integration: **NOT RUN — no runtime or canonical server command exists.**
- #1727 queue/job state/polling lifecycle: **NOT RUN / OUT OF SCOPE — not implemented or modified.**
- iOS build/unit/UI: **NOT RUN — no Xcode project/scheme exists.**
- Real YouTube metadata/caption provider: **NOT RUN — UP-02/D2-A and runtime absent.**
- LLM/STT/audio: **NOT RUN — no provider runtime; STT/audio excluded from Release A.**
- Provider timeout/malformed response/retry: **NOT RUN — provider/runtime absent.**
- Latency, concurrency, success rate, translation quality, synchronization: **NOT RUN — D3-A/runtime absent.**
- Cost in currency and cost-cap threshold: **NOT RUN — D2-A unresolved.**
- Rate/quota enforcement and reset behavior: **NOT RUN — D4/SG-01 runtime transport unresolved.**
- Raw-audio TTL, cache purge, deployment, TestFlight: **NOT RUN — no corresponding runtime/tooling.**

Writer completion means this package is ready for independent `codex-spock-review-pro` review. It is not review, QA, or closeout evidence.
