# Trade Plan Monitor Documentation

Unsuffixed documents are canonical English inputs; matching `.zh-CN.md` files are Chinese review copies. This index is reconciled against the current program on2026-10-02.

## Current entry points and unfinished work

- Daily plans: Schema4 / `plan-extract-v7` monitoring and explicit whole-lot simulation are implemented. Fundamentals are excluded from monitoring; new broad-market index decisions are deferred. The daily documents below own current contract, completion and acceptance.
- Runtime recovery: the normal Web entry uses monitor contract `2`; approved D1–D8 / A01–A13 offline implementation is complete. D9/A14 is a separate unreviewed legacy alert-linked actual-sale requirement, outside daily simulation. C5 user evidence review and real-environment rollout are not marked complete.
- Schema1/2/3, existing index conditions and backtesting remain. Historical path counts, test totals and certification validity windows in old specifications/reports do not certify current complete scope or live availability.
- Use the [project README](../README.md) for startup and routine checks. Machine API contracts are [`openapi.json`](../openapi.json) and [`openapi.runtime-status.json`](../openapi.runtime-status.json).

## Architecture

- [Capability map: daily-plan](architecture/CAPABILITY-MAP-daily-plan.md) ([Chinese](architecture/CAPABILITY-MAP-daily-plan.zh-CN.md))
- [Capability Map: Live Production Chain](architecture/CAPABILITY-MAP-live-production-chain.md) ([Chinese](architecture/CAPABILITY-MAP-live-production-chain.zh-CN.md))
- [Capability Map: Local AI-Assisted Trade Plan Monitor](architecture/CAPABILITY-MAP.md) ([Chinese](architecture/CAPABILITY-MAP.zh-CN.md))

## Monitoring specifications

- [Spec: ai-plan-drafting (AI Plan Drafting)](specifications/monitoring/SPEC-ai-plan-drafting.md) ([Chinese](specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md))
- [Specification: daily-plan](specifications/monitoring/SPEC-daily-plan.md) ([Chinese](specifications/monitoring/SPEC-daily-plan.zh-CN.md))
- [Spec: decision-engine (Deterministic Decision Engine)](specifications/monitoring/SPEC-decision-engine.md) ([Chinese](specifications/monitoring/SPEC-decision-engine.zh-CN.md))
- [Spec: executable-plan-extension (R08 / F06)](specifications/monitoring/SPEC-executable-plan-extension.md) ([Chinese](specifications/monitoring/SPEC-executable-plan-extension.zh-CN.md))
- [Spec: index-data](specifications/monitoring/SPEC-index-data.md) ([Chinese](specifications/monitoring/SPEC-index-data.zh-CN.md))
- [Spec: index-identity](specifications/monitoring/SPEC-index-identity.md) ([Chinese](specifications/monitoring/SPEC-index-identity.zh-CN.md))
- [Interface design contract](specifications/monitoring/SPEC-interface-design.md) ([Chinese](specifications/monitoring/SPEC-interface-design.zh-CN.md))
- [Spec: live-production-chain](specifications/monitoring/SPEC-live-production-chain.md) ([Chinese](specifications/monitoring/SPEC-live-production-chain.zh-CN.md))
- [Spec: local-web (Local Web Application)](specifications/monitoring/SPEC-local-web.md) ([Chinese](specifications/monitoring/SPEC-local-web.zh-CN.md))
- [Spec: market-data (Tushare Market Data)](specifications/monitoring/SPEC-market-data.md) ([Chinese](specifications/monitoring/SPEC-market-data.zh-CN.md))
- [Spec: monitor-index-trends](specifications/monitoring/SPEC-monitor-index-trends.md) ([Chinese](specifications/monitoring/SPEC-monitor-index-trends.zh-CN.md))
- [Spec: monitor-index-view](specifications/monitoring/SPEC-monitor-index-view.md) ([Chinese](specifications/monitoring/SPEC-monitor-index-view.zh-CN.md))
- [Spec: monitor-runtime (Monitoring Runtime)](specifications/monitoring/SPEC-monitor-runtime.md) ([Chinese](specifications/monitoring/SPEC-monitor-runtime.zh-CN.md))
- [Spec: notification-outbox (Notification Outbox)](specifications/monitoring/SPEC-notification-outbox.md) ([Chinese](specifications/monitoring/SPEC-notification-outbox.zh-CN.md))
- [Spec: plan-domain (Trade Plan Domain Model)](specifications/monitoring/SPEC-plan-domain.md) ([Chinese](specifications/monitoring/SPEC-plan-domain.zh-CN.md))
- [Spec: plan-index-conditions](specifications/monitoring/SPEC-plan-index-conditions.md) ([Chinese](specifications/monitoring/SPEC-plan-index-conditions.zh-CN.md))
- [Spec: provider-contract](specifications/monitoring/SPEC-provider-contract.md) ([Chinese](specifications/monitoring/SPEC-provider-contract.zh-CN.md))
- [Spec: runtime-recovery](specifications/monitoring/SPEC-runtime-recovery.md) ([Chinese](specifications/monitoring/SPEC-runtime-recovery.zh-CN.md))
- [Spec: runtime-status](specifications/monitoring/SPEC-runtime-status.md) ([Chinese](specifications/monitoring/SPEC-runtime-status.zh-CN.md))
- [Spec: source-treatment-review (R11 mixed-source completion)](specifications/monitoring/SPEC-source-treatment-review.md) ([Chinese](specifications/monitoring/SPEC-source-treatment-review.zh-CN.md))
- [Spec: strategy-state (Strategy State and Persistence)](specifications/monitoring/SPEC-strategy-state.md) ([Chinese](specifications/monitoring/SPEC-strategy-state.zh-CN.md))

## Backtesting specifications

- [Spec: backtest-api](specifications/backtesting/SPEC-backtest-api.md) ([Chinese](specifications/backtesting/SPEC-backtest-api.zh-CN.md))
- [Spec: backtest-data](specifications/backtesting/SPEC-backtest-data.md) ([Chinese](specifications/backtesting/SPEC-backtest-data.zh-CN.md))
- [Spec: backtest-engine](specifications/backtesting/SPEC-backtest-engine.md) ([Chinese](specifications/backtesting/SPEC-backtest-engine.zh-CN.md))
- [Spec: backtest-index-data](specifications/backtesting/SPEC-backtest-index-data.md) ([Chinese](specifications/backtesting/SPEC-backtest-index-data.zh-CN.md))
- [Spec: backtest-index-view](specifications/backtesting/SPEC-backtest-index-view.md) ([Chinese](specifications/backtesting/SPEC-backtest-index-view.zh-CN.md))
- [Spec: backtest-jobs](specifications/backtesting/SPEC-backtest-jobs.md) ([Chinese](specifications/backtesting/SPEC-backtest-jobs.zh-CN.md))
- [Spec: backtest-results](specifications/backtesting/SPEC-backtest-results.md) ([Chinese](specifications/backtesting/SPEC-backtest-results.zh-CN.md))
- [Spec: backtest-web](specifications/backtesting/SPEC-backtest-web.md) ([Chinese](specifications/backtesting/SPEC-backtest-web.zh-CN.md))
- [Spec: backtest (Historical Data and Deterministic Trade Backtesting)](specifications/backtesting/SPEC-backtest.md) ([Chinese](specifications/backtesting/SPEC-backtest.zh-CN.md))

## Architecture decisions

- [ADR 0001: Isolate Durable Backtest Jobs from Deterministic Results](decisions/0001-isolate-backtest-jobs-from-results.md) ([Chinese](decisions/0001-isolate-backtest-jobs-from-results.zh-CN.md))
- [ADR 0002: Use Asia/Shanghai for All Backtest Time](decisions/0002-use-asia-shanghai-for-backtest-time.md) ([Chinese](decisions/0002-use-asia-shanghai-for-backtest-time.zh-CN.md))
- [ADR 0003: Share Board-Index Data and Let Trade Plans Own Its Usage](decisions/0003-share-board-index-data-and-let-plans-own-usage.md) ([Chinese](decisions/0003-share-board-index-data-and-let-plans-own-usage.zh-CN.md))
- [ADR 0004: Use Authoritative Projection Availability and Atomic Live State](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.md) ([Chinese](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.zh-CN.md))
- [ADR 0005: Version Explicit Plan Rules Without Reinterpreting History](decisions/0005-version-explicit-plan-rules.md) ([Chinese](decisions/0005-version-explicit-plan-rules.zh-CN.md))
- [ADR 0006: Review Mixed Source with Bounded Server Treatments](decisions/0006-review-mixed-source-with-bounded-treatments.md) ([Chinese](decisions/0006-review-mixed-source-with-bounded-treatments.zh-CN.md))
- [ADR 0007: Separate Recovery Delivery Metadata from Alert Identity](decisions/0007-separate-recovery-delivery-metadata.md) ([Chinese](decisions/0007-separate-recovery-delivery-metadata.zh-CN.md))

## Operations and guides

- [AI Model Selection Guide](guides/ai-model-selection.md) ([Chinese](guides/ai-model-selection.zh-CN.md))
- [File naming](guides/file-naming.md) ([Chinese](guides/file-naming.zh-CN.md))
- [Tushare Live Certification](operations/live-certification.md) ([Chinese](operations/live-certification.zh-CN.md))

## Task completion records

- [Consolidated daily record](../tasks/daily-plan-todo.md) ([Chinese](../tasks/daily-plan-todo.zh-CN.md)): DPT, DSC and C1–C4 complete, including publication.
- [Runtime recovery plan](../tasks/runtime-recovery-plan.md) ([Chinese](../tasks/runtime-recovery-plan.zh-CN.md)) and [tasks](../tasks/runtime-recovery-todo.md) ([Chinese](../tasks/runtime-recovery-todo.zh-CN.md)): completed RR work plus unapproved D9/A14 and pending C5 review.
- [Index and WEBF13 record](../tasks/todo.md) ([Chinese](../tasks/todo.zh-CN.md)) and [live-chain LPC record](../tasks/live-production-todo.md) ([Chinese](../tasks/live-production-todo.zh-CN.md)): completed historical tasks; acceptance counts apply to their recorded scope.

## Verification evidence

- [Daily simulation final acceptance](verification/2026-10-02-daily-simulation-cleanup.md) ([Chinese](verification/2026-10-02-daily-simulation-cleanup.zh-CN.md))
- [Daily simulation independent review](verification/2026-10-02-daily-simulation-independent-review.md) ([Chinese](verification/2026-10-02-daily-simulation-independent-review.zh-CN.md))
- [Runtime recovery final offline gate](verification/2026-09-30-runtime-recovery-final-gate.md) ([Chinese](verification/2026-09-30-runtime-recovery-final-gate.zh-CN.md))
- [Runtime status and page acceptance](verification/2026-09-30-s4-offline-status-gate.md) ([Chinese](verification/2026-09-30-s4-offline-status-gate.zh-CN.md))
- [Schema3 backtest reflow acceptance addendum](verification/R13-N05-addendum.md) ([Chinese](verification/R13-N05-addendum.zh-CN.md))
- [Schema3 independent reacceptance before addendum](verification/R13-reacceptance.md) ([Chinese](verification/R13-reacceptance.zh-CN.md))
- [Backtest offline acceptance (test dependency)](verification/backtest-acceptance.md) ([Chinese](verification/backtest-acceptance.zh-CN.md))
- [Historical WEBF13 acceptance](verification/webf13-acceptance.md) ([Chinese](verification/webf13-acceptance.zh-CN.md))
- [Historical LPC acceptance and limits](verification/live-production-chain-acceptance.md) ([Chinese](verification/live-production-chain-acceptance.zh-CN.md))
- [Historical Tushare contract acceptance](verification/tushare-live.md) ([Chinese](verification/tushare-live.zh-CN.md))
- [Historical T059 release acceptance](verification/release-acceptance.md) ([Chinese](verification/release-acceptance.zh-CN.md))

## Document retention rules

Retain current specifications, machine API contracts, architecture decisions, operating guides, valid source mappings, unfinished requirements and executed acceptance records. Stage records in `verification/` preserve commands, outcomes, failures and limitations; their dates define evidence scope, not pending instructions. Earlier handoffs in `remediation/` still contain regression rationale and acceptance matrices not covered by other reports and remain; original evidence attachments are unchanged.

Removed46 obsolete or duplicate pairs (92 files): expired one-shot R14–R32 proposals/preparations, R17–R32 handoffs covered by execution reports, completed remediation plans, the old index proposal/execution plans, and old daily pause/resume/execution/cleanup handoff. Stable daily DPT/DSC/C identifiers are consolidated in the single record. Historical reports that cite removed process text now link to the exact file at published commit `030075c4946bf34833a0155fde6b4deda3c79055`, preserving original context; this does not renew old one-shot authorization. New or material documentation updates must synchronize both languages and this index.
