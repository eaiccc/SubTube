# Release A decision and corpus gate (#1705)

This package is the machine-recheckable evidence for the D1-D6 product ledger,
D2-A provider/cost decision and D3-A/D6 Release A corpus gate. It is a decision
artifact, not a provider integration.

## Canonical command

```bash
python3 contracts/release-a-gates/verify_gates.py
```

This is the only canonical entrypoint for this package. The dependency-free
verifier applies both JSON schemas to the fixtures (it does not merely parse
them), rejects missing/unknown keys, wrong types, blank required strings,
timezone-less deadlines and malformed dates/HTTPS URLs, and then runs the
cross-file semantic checks. It recomputes the D2-A LLM worst-case cost, enforces
the provider/model snapshot, Responses endpoint, reasoning effort, positive
timeout envelope, activation rule, pipeline version and price evidence, and
keeps the direct-provider ceiling at USD 0.15.

For D3-A it checks exactly 20 shaped candidates, the public/non-live/
embeddable/retrievable-caption promotion contract, the two-reviewer 1–5 rubric
and threshold, the `release-a-staging` fingerprint/run lanes/evidence contract,
fixture separation and D6's 900-second ceiling. A `verified` row additionally
requires structured `runId`/`runStartedAt`/`checkedAt` evidence using strict
RFC3339, with no future timestamp and no more than 24 hours between the run and
check. Promotion is cross-constrained: all 20 rows must promote together, the
ledger must carry an externally approved named provider and evidence, staging
must be provisioned with matching actual run evidence, and corpus/ledger gate
states must agree. The checked-in honest state remains 20 candidates, 0
verified, provider blocked/null, staging blocked and quality execution `NOT RUN`.

The verifier also sends 34 deterministic invalid mutations through that same
schema-plus-semantic path. Coverage includes all nine Vigil failure classes
(missing decision cells, timezone-less deadline, zero timeout, invalid price
URL/date, false eligibility, removed promotion rules/evidence, junk verified
evidence and unknown keys), fabricated one/all-20 promotion, fabricated provider
identity, stale/future/missing/reversed timestamps and space-separated datetime,
plus provider/model/cost, staging, quality, Release-B-cell, type, blank-value
and schema-only strictness regressions.

## Evidence boundary

- `decision-ledger.json` freezes the choices that can be decided from PRD and
  official documentation. The caption-text provider remains blocked because
  the official YouTube download API requires edit permission for the video.
- `release-a-corpus.json` contains 20 **candidates** observed on visible YouTube
  search pages. `verifiedCount=0`: embed status, API language metadata, approved
  caption retrieval, staging playback and provider execution are not verified.
- A candidate may become `verified` only with every `promotionGate` item. The
  verifier rejects a `verified` row without the required evidence object.
- Preflight-rejection and service-failure fixtures remain separate from the
  20-video success/quality denominator.
- Release B/STT has no corpus or implementation in this package.

The command verifies documentation and fixture consistency only. Runtime/API
provider calls, official `videos.list` preflight, authorized caption retrieval,
LLM execution and billing, staging, latency, success rate, translation review,
synchronization, iOS build/tests, deployment and TestFlight remain `NOT RUN`.
Use `python3 contracts/release-a/verify_contract.py` separately for the frozen
Release A wire-contract readback; that command also does not supply runtime or
provider evidence.

## Expected status before external unblock

The command passes the consistency of this package while product launch status
remains `Release A=BLOCKED/NO-GO`, `Release B=OPEN/NO-GO`. A passing validator
does not turn an OPEN/NOT RUN gate into provider evidence.
