# Run-record filter simplification

## RF-01 — Interface

- [x] Keep stock, inclusive backtest cutoff dates and retention status. Remove dataset hash and plan version ID, including their advanced/legacy lookup entrances. Old page links drop both conditions and their cursor before querying; internal APIs and stored identifiers remain. Replace the disabled sort selector with an explanation. Preserve visible old-link time conditions, keyboard use, URL restoration and narrow layouts.

## RF-02 — Date contract and compatibility

- [x] Add optional `eventEndFrom` / `eventEndTo` to `GET /api/v1/backtest-runs`. Validate real `YYYY-MM-DD` dates and range order, combine conditions with AND, filter before pagination and bind them to the signed cursor. Common dates always compare `eventEnd`, including old results. Preserve old `completedFrom` / `completedTo` links and their result-time meaning; do not relabel replay evidence cutoff as actual completion. Keep frozen identities, retention and `completedAt:desc,runId:desc` unchanged. Show result time explicitly in the table.

## RF-03 — Verification and status

- [x] Complete within RF-01–RF-02. Latest frontend: 71 files / 1094 tests passed; type checking, build and one updated Chrome journey passed. Initial date-contract verification passed 14 snapshot checks, both generated-contract checks and the final 60 backend query/API rechecks; 128 selected backend cases passed across initial runs and correction. The later filter removal changes no backend contract. Actual date-filter and removal evidence is recorded separately. Paired documentation is updated. See [RF-V01–RF-V05](../docs/verification/2026-10-18-run-record-filters.md) for evidence and retained browser-suite limits.
