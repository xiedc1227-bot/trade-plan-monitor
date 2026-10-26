# Trade Plan Monitor Documentation

Daily market linkage: [capability and operations](operations/market-linkage-p0.md), [specifications](specifications/monitoring/SPEC-market-linkage-p0.md), [verification](verification/2026-10-24-market-linkage-p0.md).

P1 human-reviewed buy exceptions: [operations and both quantity rules](operations/market-linkage-p1.md) · [specification and six decisions](specifications/monitoring/SPEC-market-linkage-p1.md) · [tasks](../tasks/market-linkage-p1.md) · [executed acceptance status](verification/2026-10-24-market-linkage-p1.md). Schema 7 requires separate per-occurrence approval and execution; existing Schema 6 exception routes remain blocked.

P2 review draft (not implemented): [remaining gaps and six proposed decisions](specifications/monitoring/SPEC-market-linkage-p2.md) · [18 tasks and six checkpoints](../tasks/market-linkage-p2.md). Proposed scope: source-defined volatility sizing and pre-buy economics.

## Start here

English documents are canonical implementation inputs; matching `.zh-CN.md` files are equivalent Chinese review copies. Use the [project README](../README.md) for installation and routine checks, the [capability map](architecture/CAPABILITY-MAP.md) for module boundaries, and [One Trade Plan Workflow](specifications/monitoring/SPEC-unified-plan.md) for current product behavior.

One `/plans` workspace uses Schema 5 fixed plans, Schema 6 daily linked plans, Schema 7 per-occurrence exceptions and `plan-extract-v10`: source → draft → edit/review → explicit activation → mixed daily/five-minute monitoring → reminders and explicit whole-trade simulation. Exception approval alone never trades. Fundamentals are generation-time review only. Alerts/acknowledgement never change inventory. Frozen Schema 1–4 readers and independent research retain their original bytes/hashes; they cannot authorize new live operations.

Machine API truth is in [`openapi.json`](../openapi.json) and [`openapi.runtime-status.json`](../openapi.runtime-status.json). The installed entry uses monitor contract `2`. Local acceptance does not certify live-provider availability, user-database migration, manual NVDA review or deployment; these remain separate verification work.

## Architecture

- [Capability Map: Trade Plan Monitor](architecture/CAPABILITY-MAP.md) ([中文](architecture/CAPABILITY-MAP.zh-CN.md))

## Monitoring specifications

- [decision-engine (Deterministic Decision Engine)](specifications/monitoring/SPEC-decision-engine.md) ([中文](specifications/monitoring/SPEC-decision-engine.zh-CN.md))
- [index-data](specifications/monitoring/SPEC-index-data.md) ([中文](specifications/monitoring/SPEC-index-data.zh-CN.md))
- [index-identity](specifications/monitoring/SPEC-index-identity.md) ([中文](specifications/monitoring/SPEC-index-identity.zh-CN.md))
- [Interface design contract](specifications/monitoring/SPEC-interface-design.md) ([中文](specifications/monitoring/SPEC-interface-design.zh-CN.md))
- [live-production-chain](specifications/monitoring/SPEC-live-production-chain.md) ([中文](specifications/monitoring/SPEC-live-production-chain.zh-CN.md))
- [local-web](specifications/monitoring/SPEC-local-web.md) ([中文](specifications/monitoring/SPEC-local-web.zh-CN.md))
- [market-data (Tushare Market Data)](specifications/monitoring/SPEC-market-data.md) ([中文](specifications/monitoring/SPEC-market-data.zh-CN.md))
- [monitor-index-trends](specifications/monitoring/SPEC-monitor-index-trends.md) ([中文](specifications/monitoring/SPEC-monitor-index-trends.zh-CN.md))
- [monitor-index-view](specifications/monitoring/SPEC-monitor-index-view.md) ([中文](specifications/monitoring/SPEC-monitor-index-view.zh-CN.md))
- [monitor-runtime (Monitoring Runtime)](specifications/monitoring/SPEC-monitor-runtime.md) ([中文](specifications/monitoring/SPEC-monitor-runtime.zh-CN.md))
- [notification-outbox (Notification Outbox)](specifications/monitoring/SPEC-notification-outbox.md) ([中文](specifications/monitoring/SPEC-notification-outbox.zh-CN.md))
- [Frozen Plan Domain and Replay Compatibility](specifications/monitoring/SPEC-plan-domain.md) ([中文](specifications/monitoring/SPEC-plan-domain.zh-CN.md))
- [plan-index-conditions](specifications/monitoring/SPEC-plan-index-conditions.md) ([中文](specifications/monitoring/SPEC-plan-index-conditions.zh-CN.md))
- [provider-contract](specifications/monitoring/SPEC-provider-contract.md) ([中文](specifications/monitoring/SPEC-provider-contract.zh-CN.md))
- [runtime-recovery](specifications/monitoring/SPEC-runtime-recovery.md) ([中文](specifications/monitoring/SPEC-runtime-recovery.zh-CN.md))
- [runtime-status](specifications/monitoring/SPEC-runtime-status.md) ([中文](specifications/monitoring/SPEC-runtime-status.zh-CN.md))
- [source-treatment-review](specifications/monitoring/SPEC-source-treatment-review.md) ([中文](specifications/monitoring/SPEC-source-treatment-review.zh-CN.md))
- [strategy-state (Strategy State and Persistence)](specifications/monitoring/SPEC-strategy-state.md) ([中文](specifications/monitoring/SPEC-strategy-state.zh-CN.md))
- [Specification: One Trade Plan Workflow](specifications/monitoring/SPEC-unified-plan.md) ([中文](specifications/monitoring/SPEC-unified-plan.zh-CN.md))
- [Index close display repair](specifications/monitoring/SPEC-index-close-display-repair.md) ([中文](specifications/monitoring/SPEC-index-close-display-repair.zh-CN.md))

## Backtesting specifications

- [Backtest result interaction proposal (proposed)](specifications/backtesting/PROPOSAL-backtest-result-ux.md) ([中文](specifications/backtesting/PROPOSAL-backtest-result-ux.zh-CN.md))
- [Backtest result review — P0 + minimal P1](specifications/backtesting/SPEC-backtest-review.md) · [BT-R01–BT-R03](../tasks/backtest-review.md)
  - [Review operations and old-run indexing](operations/backtest-review.md) · [Verification](verification/2026-10-20-backtest-review.md)
- [Backtest creation interaction](specifications/backtesting/SPEC-backtest-creation-ux.md) · [Implementation tasks](../tasks/backtest-creation-ux.md)
  - [Creation interaction verification](verification/2026-10-20-backtest-creation-ux.md)
- [Monitoring-loop backtest design (implemented)](specifications/backtesting/PROPOSAL-monitor-loop-backtest.md) ([中文](specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md))
- Active monitoring-loop implementation: [plan](../tasks/plan.md) ([中文](../tasks/plan.zh-CN.md)) and [tasks](../tasks/todo.md) ([中文](../tasks/todo.zh-CN.md)); implementation and acceptance are complete, with results in MV18–MV46.
- [Unified Plan Historical Replay](specifications/backtesting/SPEC-unified-replay.md) ([中文](specifications/backtesting/SPEC-unified-replay.zh-CN.md))
- [backtest-api](specifications/backtesting/SPEC-backtest-api.md) ([中文](specifications/backtesting/SPEC-backtest-api.zh-CN.md))
- [backtest-data](specifications/backtesting/SPEC-backtest-data.md) ([中文](specifications/backtesting/SPEC-backtest-data.zh-CN.md))
- [backtest-engine](specifications/backtesting/SPEC-backtest-engine.md) ([中文](specifications/backtesting/SPEC-backtest-engine.zh-CN.md))
- [backtest-index-data](specifications/backtesting/SPEC-backtest-index-data.md) ([中文](specifications/backtesting/SPEC-backtest-index-data.zh-CN.md))
- [backtest-index-view](specifications/backtesting/SPEC-backtest-index-view.md) ([中文](specifications/backtesting/SPEC-backtest-index-view.zh-CN.md))
- [backtest-jobs](specifications/backtesting/SPEC-backtest-jobs.md) ([中文](specifications/backtesting/SPEC-backtest-jobs.zh-CN.md))
- [backtest-results](specifications/backtesting/SPEC-backtest-results.md) ([中文](specifications/backtesting/SPEC-backtest-results.zh-CN.md))
- [backtest-web](specifications/backtesting/SPEC-backtest-web.md) ([中文](specifications/backtesting/SPEC-backtest-web.zh-CN.md))
- [backtest (Historical Data and Deterministic Trade Backtesting)](specifications/backtesting/SPEC-backtest.md) ([中文](specifications/backtesting/SPEC-backtest.zh-CN.md))

## Architecture decisions

- [ADR 0001: Isolate Durable Backtest Jobs from Deterministic Results](decisions/0001-isolate-backtest-jobs-from-results.md) ([中文](decisions/0001-isolate-backtest-jobs-from-results.zh-CN.md))
- [ADR 0002: Use Asia/Shanghai for All Backtest Time](decisions/0002-use-asia-shanghai-for-backtest-time.md) ([中文](decisions/0002-use-asia-shanghai-for-backtest-time.zh-CN.md))
- [ADR 0003: Share Board-Index Data and Let Trade Plans Own Its Usage](decisions/0003-share-board-index-data-and-let-plans-own-usage.md) ([中文](decisions/0003-share-board-index-data-and-let-plans-own-usage.zh-CN.md))
- [ADR 0004: Use Authoritative Projection Availability and Atomic Live State](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.md) ([中文](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.zh-CN.md))
- [ADR 0005: Version Explicit Plan Rules Without Reinterpreting History](decisions/0005-version-explicit-plan-rules.md) ([中文](decisions/0005-version-explicit-plan-rules.zh-CN.md))
- [ADR 0006: Review Mixed Source with Bounded Server Treatments](decisions/0006-review-mixed-source-with-bounded-treatments.md) ([中文](decisions/0006-review-mixed-source-with-bounded-treatments.zh-CN.md))
- [ADR 0007: Separate Recovery Delivery Metadata from Alert Identity](decisions/0007-separate-recovery-delivery-metadata.md) ([中文](decisions/0007-separate-recovery-delivery-metadata.zh-CN.md))
- [ADR 0008: Isolate the Backtest Service Lifecycle with Dedicated Threads](decisions/0008-isolate-backtest-service-lifecycle.md) ([中文](decisions/0008-isolate-backtest-service-lifecycle.zh-CN.md))
- [ADR 0009: Admit One Unfinished Backtest Task](decisions/0009-single-unfinished-backtest-task.md) ([中文](decisions/0009-single-unfinished-backtest-task.zh-CN.md))

## Operations and conventions

- [Tushare Live Certification](operations/live-certification.md) ([中文](operations/live-certification.zh-CN.md))
- [Current Plan Replay Guide](operations/unified-replay.md) ([中文](operations/unified-replay.zh-CN.md))
- [Monitoring-loop Backtest Operations](operations/monitor-loop-backtest.md) ([中文](operations/monitor-loop-backtest.zh-CN.md))

## Guides

- [File naming](guides/file-naming.md) ([中文](guides/file-naming.zh-CN.md))

## Necessary acceptance evidence

- [Unified Replay Verification](verification/2026-10-03-unified-replay.md) ([中文](verification/2026-10-03-unified-replay.zh-CN.md))
- [One Plan Workflow Verification](verification/2026-10-03-unified-plan.md) ([中文](verification/2026-10-03-unified-plan.zh-CN.md))
- [Backtest production-fake acceptance](verification/backtest-acceptance.md) ([中文](verification/backtest-acceptance.zh-CN.md))
- [Monitoring-loop Backtest Verification](verification/monitor-loop-backtest.md) ([中文](verification/monitor-loop-backtest.zh-CN.md))
- [Index Close Display and Related Monitor Repair Verification](verification/2026-10-09-index-close-display-repair.md) ([中文](verification/2026-10-09-index-close-display-repair.zh-CN.md))

## Maintenance policy

Retain current specifications, useful frozen compatibility contracts, accepted architectural decisions and reusable operating/development guides. Keep the latest executed current acceptance and the backtest acceptance contract consumed by regression tests; recorded results apply to their stated scope/date only. Do not relax thresholds or remove safety assertions to delete a document.

Remove superseded proposals, completed handoffs, intermediate test/debug reports, duplicate evidence indexes, expired model-assignment guides, migration inventories and obsolete logs/screenshots after incorporating any enduring constraints into a maintained document. Historical source remains in Git. Update both languages and inbound links together, then remove empty directories. New process records should not become permanent development entry points.

Historical document bytes needed by contract tests belong in `tests/history` with frozen source identities, not in current development indexes. Keep their assertions and authorization boundaries intact when cleaning documentation.
