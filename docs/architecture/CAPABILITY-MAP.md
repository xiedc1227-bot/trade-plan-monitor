# Capability Map: Trade Plan Monitor

## Product boundary

A local single-user application binds to `127.0.0.1` and monitors at most 10 A-share symbols. One `/plans` workspace owns Schema 5 extraction, human review, explicit activation, mixed daily/five-minute monitoring and explicit whole-trade simulation. Fundamentals are generation-time review only. Alerts and acknowledgement never change inventory. See [One Trade Plan Workflow](../specifications/monitoring/SPEC-unified-plan.md).

## Maintained modules

| Module ID | Responsibility | Depends on |
|---|---|---|
| `plan-domain`, `ai-plan-drafting` | Current typed plan, source evidence, omissions and exact human review; `plan-extract-v8` performs extraction only | `local-web`, `strategy-state` |
| `market-data`, `index-identity`, `index-data` | Certified normalization, calendar, official daily/complete minute evidence and shared informational index facts | `provider-contract` |
| `decision-engine` | Pure, exact, source-defined condition evaluation; current and frozen replay contracts stay separate | `plan-domain`, `market-data` |
| `strategy-state`, `live-state-store` | Immutable plan/review identities, scoped facts, completion proofs and atomic isolated simulation accounting | `decision-engine` |
| `monitor-runtime`, `live-market-runtime`, `live-index-runtime` | One owned scheduler, bounded acquisition, durable recovery, activation fences and honest progress | `market-data`, `strategy-state` |
| `notification-outbox` | Transactional reminder identity, send-time eligibility and independent acknowledgement | `strategy-state`, `monitor-runtime` |
| `projection-availability`, `web-availability`, `local-web` | Authoritative reads, monitor contract `2`, same-origin commands and accessible Vue presentation | `strategy-state`, `monitor-runtime` |
| `plan-index-conditions`, `monitor-index-view` | Frozen plan-specific index interpretation and current shared index display; no new current index judgment | `index-data` |
| `backtest-data`, `backtest-engine`, `backtest-results` | Frozen datasets, no-lookahead deterministic research and integrity-checked result publication | Frozen `plan-domain`, `market-data` |
| `backtest-jobs`, `backtest-api`, `backtest-web` | One durable worker slot, typed resources and independent research workbench | `backtest-data`, `backtest-engine`, `backtest-results`, `local-web` |

## Development boundaries

Domain logic stays in `src/trade_plan_monitor`; HTTP adapters and Vue render backend authority. Market I/O occurs outside short SQLite transactions. Current simulation inventory, historical actual-position records and backtest market/result stores remain isolated. Frozen Schema 1–4 bytes/hashes are read or replayed, never silently converted into an active Schema 5 plan.

Implement in dependency order: contract and review → normalized evidence → pure evaluation → atomic persistence → owned runtime and outbox → projections/API → Vue. Follow the relevant maintained specifications and deterministic tests. Real provider calls, user-database migration and deployment remain separately authorized operations; local acceptance does not prove live readiness.
