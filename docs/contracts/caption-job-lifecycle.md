# #1727 Caption parse job state and polling lifecycle

## Scope

This contract closes the Release A handoff after URL normalization and preflight
acceptance. A valid public, non-live, embeddable English video with captions is
accepted as one `queued` ProcessingJob. The contract freezes state, polling,
identity, retry, and sentence-level completion behavior without claiming runtime
implementation.

## State map

```text
queued -> fetching_captions -> translating -> ready
   |             |                  |
   +-----------> failed <-----------+
```

`ready` and `failed` are terminal. `transcribing` is not a Release A state. A
failed snapshot keeps `learningDataPath=null`, exposes `errorCode`,
`errorMessageKey`, and `retryable`, and is never treated as a successful cache
entry.

## Client polling contract

| Event | Required behavior |
| --- | --- |
| Processing view becomes active | Read-only GET immediately |
| Foreground, non-terminal | Read-only GET every 3 seconds |
| App enters background | Stop local periodic polling; do not mutate the job |
| App returns foreground | GET immediately, then resume 3-second cadence |
| Terminal snapshot | Stop polling |
| Transport failure | Do not synthesize a failed job snapshot |

The backend job continues while the app is backgrounded. This ticket does not
freeze a background execution or queue implementation.

## Identity and delivery

An unknown response is recovered with the same idempotency key and byte-equivalent
canonical request body. A deliberate retry uses a new key. In-flight requests with
different keys but the same dedupe tuple reuse one active owner; a failed prior job
does not become a success cache hit. Snapshots are ordered by timezone-aware RFC
3339 `updatedAt`; older arrivals are ignored and equal conflicting payloads are
logged/ignored.

## Completion and acceptance

The ready result is a caption-only `LearningDocument` in `en → zh-Hant-TW` with a
learning-data reference derived from the same video owner. Every segment includes
`words`; `words=[]` is valid and keeps sentence seek available while word
highlighting stays unavailable. The
fixture verifier covers:

- AC-01: accepted preflight handoff and complete caption-first state chain.
- AC-05: polling lifecycle, replay/dedupe, retry ownership, and snapshot ordering.
- Release A no-audio/no-STT boundary and no `transcribing` state.

Run `python3 contracts/caption-job/verify_contract.py` for structural, semantic,
and mutation evidence. The verifier currently reports 61/61 adversarial mutations
rejected, including exact polling app-state/action traces, actual cadence,
owner/dedupe/pipeline-version/stale-state binding, retryability, snapshot read-only/provider-work
guards, audio/STT zero-effect guards, strict event vocabulary, accepted preflight
handoff, nested unknown-field rejection, exact equal-conflict/newer-arrival
ordering, forbidden-state enforcement, and sentence-fallback document/path
video identity binding. Independent Release A and
URL-preflight regressions are run as separate commands so each ticket retains its
own evidence.

## Open decisions and not-run evidence

D2-A (providers, timeout, pipeline version, cost cap), D3-A (20-video corpus and
quality environment), D5-A (success-cache purge), SG-02 (processing timeout), and
SG-03 (terminal retention) remain OPEN. Runtime/API/queue/store, iOS, real
providers, concurrency/load, latency/quality/cost, purge, deployment, and
TestFlight are NOT RUN because this checkout contains contracts and fixtures only.
