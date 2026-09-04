# Implementation Plan: Shared Board-Index Data with Plan-Owned Usage

> Canonical English plan. The Chinese review copy is `plan.zh-CN.md`; both documents must remain semantically equivalent.

## Overview

Implement the six approved modules in dependency order while preserving the clean two-commit local baseline, Schema v1 plan/result bytes, DeepSeek/Web AI work, and all offline-only/security boundaries. Each code slice starts with a failing focused test and ends with focused verification. No commit, push, dependency installation, deployment, or real provider request is part of this plan.

## Architecture Decisions

- One closed `board-index-map-v1` resolver; no fallback or industry mapping.
- One immutable snapshot per index/cutoff/request set; condition outcomes remain plan/path-specific.
- Schema v2 is explicit and additive; Schema v1 canonical JSON, hashes, rows, and historical results are unchanged.
- Live and replay share index models, formulas, snapshot construction, condition evaluator, cutoff rules, evidence, and hashes.
- OpenAPI is the backend contract source; generated TypeScript is regenerated, never hand-designed as a second schema.
- Vue uses Composition API, `<script setup lang="ts">`, readonly props, typed events, and no policy calculations.

## Component Map

| Component/composable | Responsibility | Contract |
|---|---|---|
| `MarketIndexDataStrip.vue` | Shared monitoring facts/health | readonly snapshots in |
| `IndexConditionProgress.vue` | One plan's counts/not-used state | readonly progress in |
| `ReferenceMarketPanel.vue` | One stock's binding/snapshot identity | readonly reference market in |
| `MarketIndexChart.vue` | Validated server series plus table alternative | readonly points in |
| `BacktestIndexConditionSummary.vue` | Per-path backtest counts | readonly summaries in |
| `BacktestMarketIndexPanel.vue` | Compose backtest identity/chart/health/date navigation | props down, date event up |
| `useMarketIndexSeries.ts` | Bounded cancellable series requests | readonly state + explicit load/cancel |

## Phases and Checkpoints

1. Foundation: `IDX001`–`IDX003` — identity, facts, shared snapshot cache.
2. Plan evaluation: `IDX004`–`IDX005` — Schema v2, conditions, paths, evidence.
3. Monitoring: `IDX006`–`IDX008` — runtime, API/OpenAPI, Vue.
4. Backtesting: `IDX009`–`IDX011` — replay data/identity, API/export, Vue.
5. Completion: `IDX012` — parity, README/API/test report, full offline gates.
6. WEBF13 route and journey closure — prove the real-route/new-backtest boundary, preserve the frozen 42-path contract, and record only actually run offline evidence.

Checkpoints occur after each phase. A checkpoint requires focused tests green, Ruff/type checks for changed surfaces, `git diff --check`, and confirmation that no secret or unrelated file entered the diff.

The WEBF13 checkpoint additionally verifies the exact 10-route map and the new-backtest chain `submit → /backtests/:runId?jobId=<jobId> → poll → remove jobId → materialized result`. It must run the OpenAPI consistency check, focused backend and frontend tests, Ruff, `vue-tsc`, production build, and deterministic browser suite before marking the paired evidence `PASS`; it must not add an API field, regenerate a changed contract, read a token, or call a provider.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Existing v1 hashes change | Historical audit break | omit new null fields, keep golden tests, version new dataset/run/report domains |
| Runtime fetch duplicates | Quota/data divergence | union requirements first and share one in-flight immutable snapshot per key |
| Index failure becomes global blocker | Violates ADR | evaluate only explicit leaves; no-condition regression tests |
| Browser duplicates policy | Divergent decisions | generated server types, presentation-only components, tests that provide authoritative outcomes |
| Backtest lookahead | Invalid research | cutoff-filtered replay, observed-time tests, shared formula/evidence goldens |
| Provider capability unknown | Production unavailability | safe `UNVERIFIED` adapter and offline fakes; report real capability as unverified |
| Existing DeepSeek/Web changes overlap | Work loss | preserve HEAD baseline and inspect every overlapping diff before editing |

## Verification Gates

```powershell
python -m ruff check src tests
python -m pytest -m "not live"
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

The backend suite excludes only tests marked `live`; it includes the repository's heavy acceptance tests unless an existing test has a documented separate resource gate. No skipped/deleted test or lowered threshold is allowed.

## Open Questions

No design question blocks offline implementation. Exact real Tushare index endpoints, five-code entitlements, timestamp/field semantics, quotas, and longest history remain intentionally unverified until separately authorized.
