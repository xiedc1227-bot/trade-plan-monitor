# ADR 0008: Isolate the Backtest Service Lifecycle with Dedicated Threads

Canonical English; the matching `.zh-CN.md` is the Chinese review copy.

- Status: Thread execution and first-use-only implementation authorized by the user; final API review remains pending
- Date: 2026-10-07, Asia/Shanghai
- Related: ML14–ML17, IP09, ML-T30–ML-T39
- ADR 0001 execution placement, queue identity and atomic publication remain applicable

## Context

Backtest resource preparation currently occurs before Web lifespan readiness. Its factory/start failure stops an already-started monitor through shared cleanup. A dedicated execution thread already exists; another thread alone cannot correct this lifecycle policy. The user selected same-process thread isolation as sufficient and declined a mandatory later child-process stage.

## Decision

Keep one product, process and Web/API entry. Preserve bounded dedicated execution/repository threads and the existing single execution slot. Application startup registers inert routes/status only; first explicit backtest use triggers guarded single-flight resource preparation. Separate metadata READ_READY from execution READY; status/history reads never start jobs or paid work. Expose independent health/capabilities and contain first-use/task/coordinator errors. Keep accounts, clocks, stores and notification sinks separate; share immutable rule/application participants only.

Cooperative cancellation, claim-checked atomic completion and physical drain govern stop/recovery. Never replace an executor while old work can still mutate stores. Initialization/shutdown timeouts report degraded/restart-required state; they do not force-stop threads. Unknown paid outcomes never silently retry. Windows checks cover failure containment, paths, ownership, cancellation, existing finite-work safeguards and 10-stock monitor load.

## Alternatives

Automatic background warm-up still touches an unused business at startup and is rejected. Only splitting modules leaves startup cleanup coupled. Adding per-stock threads does not create backtest isolation. Owned child processes, independently deployed services and remote hosts provide stronger fault boundaries but are not selected now. Revisit them only if the accepted same-process limits become insufficient.

## Consequences

Backtest preparation failure no longer needs to prevent Web/monitor readiness. Application launch performs zero backtest I/O or queue recovery. Existing pending work resumes only after explicit selection; a new submission authorizes its own job. Unused shutdown/status/prefetch remain inert, and concurrent first users share initialization. Same-process native crashes, memory exhaustion, stuck threads and shared host/device failure remain accepted risks. Thread resource guards are soft; no process-specific hard CPU/memory cap or guaranteed forced cancellation is claimed.

## Verification

ML-A19–ML-A24 and ML-C11–ML-C13 cover independent startup, owned threads, drain-aware recovery, cancel/commit races, storage/provider boundaries, understandable degradation and Windows load evidence. ML-A08 preserves online behavior. [Partial executed verification](../verification/monitor-loop-backtest.md) records completed ML-T30–ML-T34/ML-C11/ML-C12 and startup-decoupling PASS; this ADR does not claim complete fault/load acceptance or final API approval.
