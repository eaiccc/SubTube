# SubTube Release A contract package

Issue #1717 freezes the caption-only Release A wire and semantic contract.
The canonical pipeline/cache identity is `release-a-caption-v1`; a changed
identity must not reuse an older ready or in-flight dedupe owner.

Contents:

- `openapi.json` — OpenAPI 3.1 paths, schemas, null rules, Release A enums, and exact error mapping.
- `fixtures/*.json` — 18 fixtures covering normal flow, complete AC-04, failed/retry, ready/in-flight reuse, idempotency replay/conflict, and sentence fallback.
- `verify_contract.py` — dependency-free schema/semantic readback with per-success effect oracles and mutation regressions.
- `../../docs/contracts/release-a-contract.md` — cross-layer state/transition/interaction specification and implementation handoff.

Run:

```bash
python3 contracts/release-a/verify_contract.py
```

This verifier is contract evidence only. It reads back the PRD's 7-day success-cache value but does not prove D5 purge enforcement. It does not start an API server, invoke a caption/LLM/STT provider, build iOS, or measure latency.
