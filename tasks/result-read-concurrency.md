# Result-read concurrency implementation tasks

Contract: [SPEC-result-read-concurrency](../docs/specifications/backtesting/SPEC-result-read-concurrency.md). User authorized P0 and measurement-driven P1 on 2026-10-21. Preserve all existing changes and evidence.

- [x] RRC-I01 Record paired scope, owners, integrity boundaries, measurement gates and ordered tasks.
- [x] RRC-I02 Reproduce oversized read requests with bounded-reader tests, implement chunking, and verify tamper/short-read/size/link behavior. Files: `loop_input_store.py` and focused unit/integration tests. Depends on RRC-I01.
- [x] RRC-I03 Reproduce excess backtest navigation reads; scope runtime-root navigation and revoke obsolete actionable presentation. Files: runtime root/stream and focused tests. Verify initial read, internal backtest navigation, monitor re-entry and protocol/expiry behavior. Depends on RRC-I01.
- [x] RRC-I04 Measure complete P0 projection and browser request counts; compare exact response identities and decide P1 scope. No API latency claim from an isolated microbenchmark. Depends on RRC-I02–RRC-I03.
- [x] RRC-I05 If the measured gate holds, batch all historical index candidates, preserve every validation/rank/missing-row failure, and measure equivalent canonical optimization separately. Add corruption/count/ranking tests. Depends on RRC-I04.
- [x] RRC-I06 Measure remaining equivalent monitor work; either implement proven bounded sharing with authority/drain tests or explicitly record measured deferral. Depends on RRC-I05 or a recorded gate decision.
- [x] RRC-I07 Run integrity/publication/retention/pin/concurrency and monitor authority/protocol/heartbeat regressions, full frontend checks and real-browser interactions. Record paired before/after verification and remaining risks. Depends on RRC-I02–RRC-I06.

Build order: bounded read → scoped navigation → P0 measurements → justified P1 slice → full acceptance. No long-lived cache, process split, changed evidence bytes or weakened tests.

Delivery record: [verification](../docs/verification/result-read-concurrency-2026-10-21.md). RRC-I06 measurement and decision complete: keep batching; revert the slower primitive fast path; defer monitor sharing until authority/data fences and physical drain are separately proven.
