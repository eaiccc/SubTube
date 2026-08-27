# Translation job contract

This package is the contract-only delivery for issue #1718. It defines the
Release A caption-to-`zh-Hant-TW` translation adapter, strict Structured Output,
bounded retry, LearningDocument assembly, and cache identity. It does not
implement or invoke an API server, queue, provider SDK, caption provider, or iOS
client.

## Normative package

- `contract.json` — frozen provider/configuration oracle, retry policy, security
  boundary, cost values, Release A red lines, and explicit NOT RUN set.
- `schemas/translation-input.schema.json` — strict caption segment input.
- `schemas/translation-output.schema.json` — strict provider Structured Output.
- `schemas/contract.schema.json` — strict machine-readable adapter contract.
- `fixtures/*.json` — valid first attempt, malformed-then-valid, invalid twice,
  provider timeout, and changed-pipeline cache miss.
- `verify_contract.py` — dependency-free schema/semantic readback and mutation
  harness. Cross-document rules intentionally live here because JSON Schema alone
  cannot prove equality with a separate input array.

The only canonical pipeline identity is `release-a-caption-v1`. The string
`caption-v1+translation-v1` appears only as an explicitly legacy negative cache
entry proving that a changed identity cannot reuse an old ready result.

## Service and data flow

```text
caption worker output (en, caption, stable segments)
  -> current dedupe owner: videoId|en|zh-Hant-TW|release-a-caption-v1
  -> server-only Translation Adapter
  -> OpenAI Responses API, frozen model snapshot, Structured Output
  -> strict output schema + cross-input semantic validation
       invalid once -> one automatic retry
       invalid twice -> failed / translation_invalid_response / no success cache
       provider failure -> failed / translation_provider_failed / no auto retry
  -> assemble caption-only LearningDocument
  -> persist success before ready
```

The adapter receives only `sourceLanguage=en`,
`targetLanguage=zh-Hant-TW`, `transcriptSource=caption`, the canonical pipeline
version, and ordered caption segments. The provider output must return the same
segment count, IDs, order, and exact start/end times plus a nonblank translation.
Segments must be nonnegative, strictly increasing, and nonoverlapping. The
assembler copies `originalText`, uses the provider translation as
`translatedText`, and emits `words=[]`; word timing remains optional.

## Frozen provider oracle

`contracts/release-a-gates/fixtures/decision-ledger.json` is authoritative:

- provider/endpoint: OpenAI API / Responses API;
- model snapshot: `gpt-5.4-mini-2026-03-17`;
- reasoning effort: `none`;
- Structured Outputs enabled;
- per-attempt input/output budgets: 12,000 / 12,000 tokens;
- timeout: 20,000 ms;
- at most one automatic invalid-response retry; two attempts total;
- no model fallback.

Official OpenAI model documentation lists this snapshot, Responses API,
Structured Outputs, and `none` reasoning support:
`https://developers.openai.com/api/docs/models/gpt-5.4-mini`.
Availability and provider execution are not proven by these fixtures.

## Failure and retry matrix

| Condition | Automatic action | Calls | Terminal result | Success cache |
| :--- | :--- | :---: | :--- | :---: |
| First response valid | none | 1 | `ready` | yes |
| First response malformed/schema-invalid/semantic-invalid; second valid | retry once | 2 | `ready` | yes |
| Both responses invalid | stop after retry | 2 | `translation_invalid_response`, `retryable=true` | no |
| Provider timeout/service failure | no automatic provider retry | 1 | `translation_provider_failed`, `retryable=true` | no |
| Only legacy identity is cached | current-key miss | 1 | current identity processes normally | old cache not reused |

Every row requires `audioDownloads=0`, `sttCalls=0`, caption source, and no
`transcribing`. A later user retry is governed by the existing parse-job
idempotency contract; it is not a third hidden adapter attempt.

## Security, retention, and cost

The adapter and provider credential boundary are server-only. Credentials are
read from a server secret store and are never forwarded to iOS, fixtures,
LearningDocument, or logs. Raw provider payload logging is forbidden. Fixtures
contain no credential value. Translation does not acquire or retain audio.

The frozen two-attempt token ceiling yields USD 0.126 base worst case and USD
0.1386 with the ledger's maximum regional uplift, below the USD 0.15 direct
provider cap. These are formula/oracle values only: provider billing and runtime
meter enforcement are **NOT RUN**.

## Verification and integration/load plan

Run the dependency-free package and all directly affected regressions:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 contracts/translation-job/verify_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 contracts/release-a/verify_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 contracts/url-preflight/verify_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 contracts/caption-job/verify_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 contracts/release-a-gates/verify_gates.py
```

When runtime exists, integration must inject valid, malformed, schema-drift,
semantic-drift, timeout, and provider-error responses; assert atomic persistence
before `ready`; and race current/legacy dedupe owners to prove no cross-version
reuse. Load testing must cover concurrent identical jobs, 20-video Release A
corpus runs, 1- and 2-attempt cost ceilings, provider P95, queue delay, and the
60-second job hard limit. API/queue/provider/billing/latency/concurrency/load,
translation quality/staging, iOS integration/build, deployment, and TestFlight
are all **NOT RUN** in this checkout.
