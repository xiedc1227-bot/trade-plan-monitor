# Capability Map: Live Production Chain

> Canonical agent-facing English version. The human-review Chinese version is `CAPABILITY-MAP-live-production-chain.zh-CN.md`; both documents must remain semantically equivalent.

## P0 Registration

This document creates the stable `LPC` work-package namespace for the 2026-09-05 live-production repair. It does not rename, reuse, or imply completion of any historical `T001`–`T059`, `BT001`–`BT050`, `IDX001`–`IDX012`, or `WEBF13` task. In particular, `T059` remains the accepted DeepSeek release gate. Live board-index certification is newly registered as `LPC007`; it has no inherited task number or readiness claim.

## Modules

| Module ID | Responsibility | Depends on |
|---|---|---|
| `projection-availability` | Typed normal-unavailability contract for dashboard and symbol projections, while preserving successful response shapes | `local-web`, `monitor-runtime` |
| `live-state-store` | Additive Schema migration, complete evaluation results, decision/health/index heads, pending-close recovery, and persistent reads | `strategy-state`, `decision-engine`, `index-data` |
| `live-market-runtime` | Certified stock provider profile, request control, reference refresh, recovery, one-batch deadlines, evaluation supervision, and commit-after-publication discipline | `market-data`, `monitor-runtime`, `live-state-store` |
| `live-index-runtime` | Separately certified live board-index provider and per-index failure isolation | `index-data`, `live-market-runtime` |
| `web-availability` | Generated contracts, Vue availability state machine, WebSocket eligibility, Chrome acceptance, and lazy chart loading | `projection-availability`, `live-state-store`, `live-market-runtime`, `local-web` |

## Build Order

```text
projection-availability
        │
        ├──→ live-state-store ──→ live-market-runtime ──→ live-index-runtime
        │                              │                        │
        └──────────────────────────────┴────────────────────────┴──→ web-availability
```

The contract is frozen before code. Store and provider work may proceed independently after that contract; runtime integration follows the store boundary, and the Web consumes only generated server contracts. Real stock and index certification are separate serial operations and never share timestamp evidence.

## Protected Baselines

- Preserve Schema v1 plan bytes, historical evaluation/event/alert identities, backtest data/results, and all established hashes.
- Preserve DeepSeek, Web AI, board-index, backtest, and the nine pre-existing `WEBF13` working-tree changes; replace only the temporary Health fallback after tests cover the typed server contract.
- Do not commit, push, place orders, call DeepSeek, or call any provider other than the explicitly authorized Tushare test boundary.

## Review Status

Accepted for implementation by the user's explicit 2026-09-05 request. Runtime readiness is not inferred from approval: stock and index provider evidence must satisfy their own recorded gates.
