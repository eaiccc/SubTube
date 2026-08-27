# URL normalization and preflight contract

Issue #1725 adds a contract-only URL normalization and Release A preflight gate. It does not implement an API server or the #1727 parse-job lifecycle, and it does not modify the frozen #1717 package in `../release-a`.

Contents:

- `policy.json` — accepted URL forms, deterministic request/preflight order, rejection effects, provider-entry guards, and idempotency/dedupe handoff.
- `schemas/*.schema.json` — policy and fixture collection schemas.
- `fixtures/normalization.json` — standard/short URL normalization and syntax/source rejection.
- `fixtures/preflight.json` — accepted 900-second boundary plus private/live/embed/language/duration/caption rejection.
- `fixtures/handoff.json` — exact replay, raw-body conflict, and normalized Video ID dedupe.
- `fixtures/provider-entry-guards.json` — quota rejection with required `Retry-After` and the frozen job-level cost guard boundary.
- `verify_contract.py` — dependency-free field-level schema/semantic readback, frozen OpenAPI compatibility checks, and negative mutation probes.
- `../../docs/contracts/url-normalization-preflight.md` — normative data flow, failure matrix, security/cost analysis, test plan, evidence, and open decisions.

Run:

```bash
python3 contracts/url-preflight/verify_contract.py
python3 contracts/release-a/verify_contract.py
```

These commands validate contract artifacts only. API runtime, real YouTube/caption/LLM providers, concurrency/latency, build, deployment, and the D2 cost threshold remain `NOT RUN`.
