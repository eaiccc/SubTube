# Caption job lifecycle contract

This package is the contract-only delivery for GitHub issue #1727. It freezes the
Release A caption-first job lifecycle after the #1725 preflight gate. It does not
implement an API server, queue worker, iOS polling client, or provider adapter.

## Normative files

- `lifecycle.json` — state machine, polling, identity, completion, effects, open decisions.
- `schemas/lifecycle.schema.json` — structural schema for the lifecycle document.
- `schemas/fixtures.schema.json` — structural schema for fixture collections.
- `fixtures/01-normal-flow.json` — preflight handoff through `ready` and LearningDocument.
- `fixtures/02-failure-paths.json` — failure from each processing stage and one automatic retry.
- `fixtures/03-polling-lifecycle.json` — three-second polling, background stop, foreground resume.
- `fixtures/04-identity-and-retry.json` — exact replay, in-flight owner, explicit retry, cache reuse.
- `fixtures/05-snapshot-ordering.json` — stale/equal/newer snapshot handling.
- `fixtures/06-sentence-fallback.json` — sentence seek with `words=[]`.
- `verify_contract.py` — dependency-free semantic verifier and mutation harness.

## Frozen MVP rules

The only Release A statuses are `queued`, `fetching_captions`, `translating`,
`ready`, and `failed`. `transcribing` is forbidden. The normal path is
`queued → fetching_captions → translating → ready`; any processing status may
transition to `failed` with `errorCode`, `errorMessageKey`, and `retryable`.

The client performs a read-only GET immediately when the processing view becomes
active, then every three seconds while foregrounded. Backgrounding stops local
periodic polling; returning foreground performs an immediate GET and resumes the
three-second cadence. The backend job continues independently. A terminal snapshot
stops polling.

The idempotency key and canonical request body are replayed after an unknown
delivery. Explicit retry uses a new key. Equivalent requests converge on one
`videoId + sourceLanguage + targetLanguage + pipelineVersion` owner, with at most
one active owner. The canonical Release A identity is `release-a-caption-v1`;
a different identity cannot reuse its ready or in-flight owner. `updatedAt` is
timezone-aware RFC 3339 and strictly increasing
for a normal chain; stale snapshots are ignored and equal conflicting payloads do
not overwrite the accepted snapshot.

Ready data is a caption-only `LearningDocument` reference. Segment `words` is
required as an array, but an empty array is valid: the document remains accepted,
sentence seek remains enabled, and word highlighting remains disabled.

## Verification

```bash
python3 contracts/caption-job/verify_contract.py
python3 contracts/release-a/verify_contract.py
python3 contracts/url-preflight/verify_contract.py
PYTHONPYCACHEPREFIX=/tmp/subtube-1727-pycache python3 -m py_compile \
  contracts/caption-job/verify_contract.py \
  contracts/release-a/verify_contract.py \
  contracts/url-preflight/verify_contract.py
```

The #1727 verifier covers 6 fixture collections / 13 semantic cases and rejects
61 adversarial mutations, including invalid transitions, `transcribing`, wrong
actual poll cadence, forged foreground/background polling state, background
GETs, owner and dedupe identity changes, invalid request keys, key reuse on
explicit retry, stale visible-state overwrite, snapshot provider side effects,
pipeline-version drift between a LearningDocument and its dedupe/cache key,
equal-snapshot conflict removal, missing newer arrivals, normal event renames,
and duplicate forbidden statuses,
retryability drift, audio/STT provider side effects, unknown event/fixture and
request/response wrapper fields, terminal continuation, rejected preflight
handoff, incomplete OPEN/NOT RUN sets, sentence-fallback cross-video document/path
identity, and word-highlight regressions.

Runtime/API/queue/store, real caption or translation providers, iOS build/UI,
concurrency/load, latency, quality, cost enforcement, cache purge, deployment,
and TestFlight evidence are **NOT RUN** in this documentation-only checkout.
Open decisions remain D2-A, D3-A, D5-A, SG-02, and SG-03 as listed in
`lifecycle.json`.
