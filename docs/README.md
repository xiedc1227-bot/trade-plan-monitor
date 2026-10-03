# Trade Plan Monitor Documentation

## Start here

English documents are canonical implementation inputs; matching `.zh-CN.md` files are equivalent Chinese review copies. Use the [project README](../README.md) for installation and routine checks, the [capability map](architecture/CAPABILITY-MAP.md) for module boundaries, and [One Trade Plan Workflow](specifications/monitoring/SPEC-unified-plan.md) for current product behavior.

One `/plans` workspace uses Schema 5 and `plan-extract-v9`: source → draft → edit/review → explicit activation → mixed daily/five-minute monitoring → reminders and explicit whole-trade simulation. Fundamentals are generation-time review only. Alerts/acknowledgement never change inventory. Frozen Schema 1–4 readers and independent research retain their original bytes/hashes; they cannot authorize new live operations.

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

## Backtesting specifications

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

## Operations and conventions

- [Tushare Live Certification](operations/live-certification.md) ([中文](operations/live-certification.zh-CN.md))

## Guides

- [File naming](guides/file-naming.md) ([中文](guides/file-naming.zh-CN.md))

## Necessary acceptance evidence

- [One Plan Workflow Verification](verification/2026-10-03-unified-plan.md) ([中文](verification/2026-10-03-unified-plan.zh-CN.md))
- [Backtest production-fake acceptance](verification/backtest-acceptance.md) ([中文](verification/backtest-acceptance.zh-CN.md))

## Maintenance policy

Retain current specifications, useful frozen compatibility contracts, accepted architectural decisions and reusable operating/development guides. Keep the latest executed current acceptance and the backtest acceptance contract consumed by regression tests; recorded results apply to their stated scope/date only. Do not relax thresholds or remove safety assertions to delete a document.

Remove superseded proposals, completed handoffs, intermediate test/debug reports, duplicate evidence indexes, expired model-assignment guides, migration inventories and obsolete logs/screenshots after incorporating any enduring constraints into a maintained document. Historical source remains in Git. Update both languages and inbound links together, then remove empty directories. New process records should not become permanent development entry points.

Historical document bytes needed by contract tests belong in `tests/history` with frozen source identities, not in current development indexes. Keep their assertions and authorization boundaries intact when cleaning documentation.
