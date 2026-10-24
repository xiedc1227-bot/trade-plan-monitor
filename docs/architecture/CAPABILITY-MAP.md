# Capability Map: Trade Plan Monitor

## Product boundary

A local single-user application binds to `127.0.0.1` and monitors at most 10 A-share symbols. One `/plans` workspace owns Schema 5 fixed, Schema 6 linked and Schema 7 per-occurrence exception extraction, human review, explicit activation, mixed daily/five-minute monitoring and explicit whole-trade simulation. Linkage confirms on official daily evidence and executes in the next exchange session. Exception approval is separate from execution. Fundamentals are generation-time review only. Alerts and acknowledgement never change inventory. See [One Trade Plan Workflow](../specifications/monitoring/SPEC-unified-plan.md).

## Maintained modules

| Module ID | Responsibility | Depends on |
|---|---|---|
| `plan-domain`, `ai-plan-drafting` | Current typed plan, source evidence, omissions and exact human review; `plan-extract-v10` performs extraction only | `local-web`, `strategy-state` |
| `market-data`, `index-identity`, `index-data` | Certified normalization, calendar, official daily/complete minute evidence and shared informational index facts | `provider-contract` |
| `decision-engine` | Pure, exact, source-defined condition evaluation; current and frozen replay contracts stay separate | `plan-domain`, `market-data` |
| `market-regime`, `relative-strength` | Four-state daily classification and aligned 5/20-session stock/index comparison | `index-data`, `market-data` |
| `confirmation-selection`, `quantity-policy` | Source-bound S0/S1/S2, official grids and ordinary legal floor; Schema 7 WEAK_MINIMUM exact-minimum / BROKEN_STRONG explicitly entered quantity, frozen once per occurrence | `market-regime`, `relative-strength`, `strategy-state` |
| `market-linkage-workflow` | Schema 6/7 review, distinct occurrence preview/approve/reject/revoke, atomic consumption, shared runtime/frozen replay, correction fencing and provenance; [P0 operations](../operations/market-linkage-p0.md), [P1 operations](../operations/market-linkage-p1.md) | All four linkage modules |
| `strategy-state`, `live-state-store` | Immutable plan/review identities, scoped facts, completion proofs and atomic isolated simulation accounting | `decision-engine` |
| `monitor-runtime`, `live-market-runtime`, `live-index-runtime` | One owned scheduler, bounded acquisition, durable recovery, activation fences and honest progress | `market-data`, `strategy-state` |
| `notification-outbox` | Transactional reminder identity, send-time eligibility and independent acknowledgement | `strategy-state`, `monitor-runtime` |
| `projection-availability`, `web-availability`, `local-web` | Authoritative reads, monitor contract `2`, same-origin commands and accessible Vue presentation | `strategy-state`, `monitor-runtime` |
| `plan-index-conditions`, `monitor-index-view` | Historical plan-specific index interpretation and current shared index display; Schema 6 decisions belong to `market-regime` | `index-data` |
| `backtest-data`, `backtest-engine`, `backtest-results` | Frozen datasets, no-lookahead deterministic research and integrity-checked result publication | Frozen `plan-domain`, `market-data` |
| `backtest-jobs`, `backtest-api`, `backtest-web` | One durable worker slot, typed resources and independent research workbench | `backtest-data`, `backtest-engine`, `backtest-results`, `local-web` |

## Development boundaries

[market-linkage-p1](../specifications/monitoring/SPEC-market-linkage-p1.md) extends the three existing linkage modules with source-permitted human authorization for `WEAK_MINIMUM` and `BROKEN_STRONG`. Schema 6 retains `BLOCK_P1`; only explicit Schema 7 can request occurrence approval. Frozen research requires explicit authorization events and independent operations, never current local approval lookup. [Ordered tasks](../../tasks/market-linkage-p1.md) and the [verification report](../verification/2026-10-24-market-linkage-p1.md) record executed checkpoints and whole-project acceptance status.

Domain logic stays in `src/trade_plan_monitor`; HTTP adapters and Vue render backend authority. Market I/O occurs outside short SQLite transactions. Current simulation inventory, historical actual-position records and backtest market/result stores remain isolated. Frozen Schema 1–4 bytes/hashes are read or replayed, never silently converted into an active Schema 5/6/7 plan. Existing Schema 5/6 bytes/hashes remain unchanged.

Implement in dependency order: contract and review → normalized evidence → pure evaluation → atomic persistence → owned runtime and outbox → projections/API → Vue. Follow the relevant maintained specifications and deterministic tests. Real provider calls, user-database migration and deployment remain separately authorized operations; local acceptance does not prove live readiness.
