# ADR 0009: Admit One Unfinished Backtest Task

Canonical English; the matching `.zh-CN.md` is the Chinese review copy.

- Status: Accepted under the user's explicit scope correction
- Date: 2026-10-07, Asia/Shanghai
- Related: ADR 0001, ADR 0008, ML17, IP09, ML-T33, MV18
- Supersedes earlier multi-job queue admission and expiry-releases-slot choices only

## Context

The execution worker was serial, but admission still allowed 100 queued jobs and selected recovery could authorize multiple IDs. Expired unfinished work could release admission before the task reached a terminal state. The user requires one unfinished task: new tasks and mutually exclusive operations must wait for its actual end.

## Decision

1. Use the existing jobs-owned SQLite write transaction to admit at most one unfinished operation across `DATA_SYNC`, `DATASET_VERIFY` and `BACKTEST_RUN`. `QUEUED`, `RUNNING` and `CANCEL_REQUESTED` all occupy this slot, including expired/unknown leases.
2. Reserve that same slot before a new run's snapshot read. An unresolved reservation retains admission until release/finalization or explicit jobs-owned orphan cleanup; lease expiry alone does not release it.
3. Return internal `BACKTEST_BUSY` through the existing public `409 CONFLICT` envelope for a different new operation. Create no second job/reservation. Same-key replay and active-operation deduplication still return the existing resource.
4. Cancellation requested is unfinished. Terminal completion/failure/cancellation releases the job slot. Explicit recovery selects at most one existing job; the coordinator must drain physical work before another claim or replacement. Preserve the 30-second lease, 10-second heartbeat, 3 claim generations and stale-token/publication fences.
5. Preserve historical records and paginated reads. Legacy pending records require explicit reconciliation; do not silently delete, resume or cancel them to admit new work. Live monitoring and read-only status/history/results remain usable.
6. The pending single-source preparation workflow must honor the same mutual exclusion at its future entry boundary. This correction implements existing task/reservation admission and selected recovery; it does not claim preparation or new API/UI controls are implemented.

## Alternatives Considered

- Keep 100 queued jobs with one executing worker: conflicts with the user's one-task requirement.
- Release admission on cancellation request or lease expiry: neither proves actual task termination.
- Add a scheduler, generic cross-operation lock or resource framework: unnecessary for the existing transactional admission boundary.

## Consequences

Different submissions receive a conflict until unfinished work is reconciled. Restart does not free its slot automatically. Immutable completed results, job identities, retention, storage domains, schemas and the existing API error enum remain compatible. This decision does not change legacy plan-replacement semantics in frozen historical replay modes.

## Verification

MV18 records concurrent different submissions, same-request idempotency, cancellation-in-progress, expired/unknown leases, pending/expired snapshot reservations, selected recovery, physical worker drain and terminal slot release. Contract generation stays unchanged. Full preparation/API/UI workflow acceptance remains pending.
