# Spec: provider-contract

> Implementation contract derived from approved runtime-recovery proposal D1/D6; implementation authorized on 2026-09-21. English canonical; paired Chinese copy.
## Objective

Separate durable evidence of provider data interpretation from current credentials, permissions and availability. Implement A01–A02 without treating expired operational observations as live health.
## Contract

- Historical readers retain schema, size, canonical hash, normalized endpoint, nonfuture time and scope validation; only seven-day age is ignored. Existing freshness-sensitive readers retain their contract.
- Semantic sidecars contain version, surface, endpoint, profile, interval/endpoints, verified source labels, explicit adapter compatibility, provenance and semantic revision. No credential and no current READY status.
- Compatibility checks the installed SDK and the application adapter mapping. Version 1 supports the reviewed Tushare 1.4.29 adapter only. Unknown compatibility fails closed.
- Stock and index records are independent. Import only verified scopes; never promote unverified labels, missing 399107.SZ evidence or deferred BSE.
- Semantic revision includes interpretation fields, excludes verifiedAt/provenance timestamps. Metadata-only reimport is harmless. Writes are atomic, idempotent; original evidence remains unchanged. Hashes are integrity checks, not authentication.
- Production requests validate the installed interpretation identity before acquisition. Relevant configuration or incompatible semantic drift blocks the old source and requires safe stop, manual correction and a new process start. Stop drains old workers and their durable outcomes before releasing storage; no stale-generation commit. Metadata-only semantic refresh does not require restart.
## Structure and style

Own runtime/provider_contract.py and live_profiles.py. Frozen typed records; narrow validated boundary functions; no provider network IO in import.
## Commands and testing

`.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_contract.py tests/unit/test_live_certification_profiles.py -q`
Use temporary evidence files; test aged, corrupt, future, incompatible and partial scopes. Existing certification tests remain.
## Boundaries

Always preserve source evidence and strict validation. Ask before new SDK support or live certification. Never copy old health to current health or alter credentials.
