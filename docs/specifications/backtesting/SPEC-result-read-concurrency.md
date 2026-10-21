# Verified result-read performance contract

Status: User authorized implementation on 2026-10-21. Baseline: `cd5113b`. Design: [proposal](PROPOSAL-result-read-concurrency.md). [Chinese review copy](SPEC-result-read-concurrency.zh-CN.md). Tasks: [implementation](../../../tasks/result-read-concurrency.md).

## RRC-S01. Scope and boundaries

Deliver P0 bounded frozen-file reading and scoped monitor navigation. Remeasure before advancing P1 monitor batching and equivalent normalization work. Add bounded monitor in-flight sharing only if remaining measurements justify its concurrency/lifecycle complexity. Preserve the proposal pair and all existing edits. No schema/API migration, provider download, evidence deletion, altered financial calculation, timeout increase or worker-pool expansion.

## RRC-S02. Owners and contracts

| Owner | Responsibility |
|---|---|
| `LoopInputStore._read` | Read at most `_MAX_OBJECT_BYTES + 1` bytes in chunks no larger than 65,536 bytes, retaining root/link/size/domain/hash checks and downstream typed/canonical validation. |
| `runtime-status/App.vue` | Classify navigation: one shared backtest surface, existing full-path identity for other resolved routes; initial route resolution is not an additional refresh. |
| `createRuntimeMonitor.navigation` | Invalidate obsolete requests/protocol and current actionable presentation on meaningful surface changes; fresh snapshot restores verified presentation. |
| `ProjectionRepository.list_latest_market_index_snapshots` | Batch historical head/payload loading while validating every candidate and preserving `snapshot_rank` and missing-payload failure. |
| `market_index/canonical.py` | If measured beneficial, handle exact primitives efficiently without changing Decimal, enum/subclass, timezone, float rejection or canonical bytes. |
| Existing result-thread and monitor read services | Preserve physical ownership, bounded admission, cancellation isolation, authority checks and revision/availability consistency. |

## RRC-S03. Frozen-read acceptance

Keep `_MAX_OBJECT_BYTES`, all hash domains and `reportHash` unchanged. A complete read stops at EOF or the existing maximum plus one byte; short reads must not be mistaken for EOF. No cross-request validated-file cache. Retain file/root ownership, symlink/junction rejection, missing/oversized rejection, typed decoding, canonical equality, plan/account/dataset/input/report bindings and audit envelope/event-set checks. Re-reading after same-length/same-timestamp tampering must fail.

## RRC-S04. Navigation acceptance

Backtest list/result/new/data/task/filter/page/tab transitions add zero monitor refreshes merely because their URL changes. Initial startup still performs its authoritative snapshot read. Resolved monitor route changes, monitor re-entry, generation/sequence mismatch, expiry, visibility recovery, reconnect and protocol mismatch retain fresh-read behavior. Withdraw current presentation before meaningful navigation refresh; do not enable actions from an old snapshot. Command preflight is unchanged. No job submission/resume or market download is triggered by browsing.

## RRC-S05. P1 measurement gate

After P0, record store projection, HTTP and browser request counts separately. Advance historical batching if monitor projection still exceeds 1 second on the reference sample or still issues one query per historical head. Validate all candidates, including unselected corrupt historical evidence. Use a left join/equivalent missing-row check, bounded pages and the same verified ranking; never substitute maximum revision or trust unchecked SQL ordering. Keep per-read validation uncached. Preserve all row/payload identity checks. Any exact-primitive normalization change needs byte/hash equality, float/subclass/Decimal/time boundary tests and measured improvement beyond variation.

Only advance monitor sharing after the above if repeated equivalent physical work remains material and a bounded authority/data-fence design is proven. Otherwise record its deferral with measurements. Long-lived caches/process separation remain outside this delivery.

## RRC-S06. Integrity and concurrency gates

Verify damaged/missing/oversized/truncated/growing/replaced files, symlink/junction rejection, bad domain/hash, noncanonical payload, foreign identities and event-set corruption. Test retained/expired/pinned evidence, fresh mutable revisions and absence of a cache fallback. Fixtures use isolated storage. Check shared result reads, different-run queuing, observer cancellation, backpressure and shutdown physical drain; monitor generation/protocol/heartbeat tests must remain green.

## RRC-S07. Measurement gates

Use the same 39-day / 2,961-event completed run. Alternate warm original/candidate paths and compare complete responses and identities; label profiling and cold-read overhead separately. P0 sample target: verified projection median at most 2.5 seconds and at least 30% improvement. Record temporary allocation, CPU and SQL separately. Browser coverage includes initial normalization, list → result → provenance → summary, filter/pagination, back/forward and monitor re-entry; assert zero business writes and page exceptions. Do not claim p95 or global SLA from a few local samples.

## RRC-S08. Commands and delivery

From `web/`: `npm run test -- --run --maxWorkers=4`, `npm run type-check`, `npm run build`, focused `npm run test:e2e -- tests/e2e/backtest-workspace.spec.ts` plus a runtime-root navigation journey. From the project root: `.venv/Scripts/python.exe -m pytest` on bounded input, publication/tamper/retention/thread ownership, index projection and runtime status tests; `.venv/Scripts/python.exe -m ruff check` on changed Python files. Record paired verification, P1 decisions, exact measurements and remaining limits. Do not commit or push unless requested.
