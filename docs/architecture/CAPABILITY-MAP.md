# Capability Map: Local AI-Assisted Trade Plan Monitor

> Canonical agent-facing English version. The human-review Chinese version is `CAPABILITY-MAP.zh-CN.md`; both documents must remain semantically equivalent.

## Product Boundary

- A standalone local Web application for one user, listening only on `127.0.0.1`.
- Enable and monitor at most 10 A-share stocks at the same time.
- Accept pasted natural-language trade plans and use a user-configured AI service to create structured drafts.
- An AI draft must pass deterministic validation and explicit user activation before entering monitoring.
- The live path provides textual and visual reminders only and never submits, cancels, or infers broker fills. The isolated offline `BACKTEST` mode may create versioned simulated fills for research.
- The approved backtest redesign adds a local Vue workbench and additive REST resources through a persistent bounded job layer; the Web surface remains unimplemented until its module specifications, plan, and tasks pass their own review gates.
- Use one SQLite WAL database for live state plus isolated market/result SQLite databases for backtesting; do not build a cluster, primary/replica topology, or high-availability system.

## Capability Modules

| Module ID | Responsibility | Depends on |
|---|---|---|
| `plan-domain` | Versioned plan model, price zones, monitoring conditions, activation policy, validation, and immutable active versions | None |
| `ai-plan-drafting` | AI service configuration, prompt versions, natural-language extraction, evidence, uncertainty, and connectivity tests | `plan-domain` |
| `market-data` | Tushare APIs, trading calendar, daily price limits, 1-minute/5-minute/daily bars, freshness, request control, and indicators | None |
| `strategy-state` | Manual position lots, T+1, low-zone episodes, risk state, plan activation state, market history, and audit records | `plan-domain` |
| `decision-engine` | Pure deterministic evaluation from an active plan, complete market data, indicators, blockers, and strategy state | `plan-domain`, `market-data`, `strategy-state` |
| `notification-outbox` | Signal deduplication, textual alert rendering, acknowledgement, retries, in-app alerts, console, and generic webhook | `decision-engine` |
| `monitor-runtime` | Trading-session scheduling for at most 10 stocks, bounded concurrency, recovery, health, replay, and graceful shutdown | `market-data`, `strategy-state`, `decision-engine`, `notification-outbox` |
| `backtest-data` | Historical capability mapping, authorized incremental synchronization, coverage inspection, immutable revisions, dataset verification, and frozen `dataset_hash` identities | `market-data` |
| `backtest-engine` | Pure offline event-time replay, no-lookahead enforcement, versioned simulated execution, deterministic metrics, and `run_id` identity | `backtest-data`, `plan-domain`, `market-data`, `strategy-state`, `decision-engine` |
| `backtest-results` | Materialized run summaries, fills, bounded details, pagination, exports, pinning, retention, and integrity-checked reconstruction | `backtest-engine` |
| `backtest-jobs` | Persistent bounded sync/verify/run job lifecycle, dedicated single-thread execution slot, atomic idempotency claims and job/result Unit of Work, progress, cooperative cancellation, restart recovery, and single-host resource admission | `backtest-data`, `backtest-engine`, `backtest-results` |
| `backtest` | Stable initiative-wide invariant and target CLI-compatibility index for research-only offline backtesting; detailed contracts live in the six child specifications | `backtest-data`, `backtest-engine`, `backtest-results`, `backtest-jobs` |
| `local-web` | Shared loopback-only FastAPI/Vue platform for live views, same-origin security, OpenAPI generation, application shell, and design tokens | All live modules |
| `backtest-api` | Additive typed REST resources for datasets, jobs, runs, results, plan snapshots, idempotency, pagination, and generated frontend contracts | `backtest-data`, `backtest-jobs`, `backtest-results`, `plan-domain`, `local-web` |
| `backtest-web` | Vue backtest workbench for historical-data coverage, run submission, progress/cancellation, paginated history, and result inspection | `backtest-api`, `local-web` |
| `index-identity` | Closed board-index identities, validated stock-board classification, and versioned `board-index-map-v1` mapping | None |
| `index-data` | Validated live/historical board-index bars, reusable facts, health, immutable shared cutoff snapshots, and hashes | `index-identity` |
| `plan-index-conditions` | Explicit Plan Schema v2 binding, six allowlisted index leaves, plan-path validation, and pure evidence evaluation | `index-identity`, `index-data`, `plan-domain`, `decision-engine` |
| `monitor-index-view` | Separate shared index facts and plan-specific condition progress/evidence in monitoring APIs, invalidation, and Vue views | `plan-index-conditions`, `monitor-runtime`, `local-web` |
| `backtest-index-data` | Versioned index artifacts, dynamic plan warm-up, coverage, dataset/run identity, and no-lookahead replay snapshots | `plan-index-conditions`, `backtest-data`, `backtest-engine` |
| `backtest-index-view` | Backtest binding, series, path-level summaries, exact decision evidence, export, and Vue presentation | `backtest-index-data`, `backtest-results`, `backtest-api`, `backtest-web` |

## Build Order

```text
plan-domain ──→ ai-plan-drafting
     │
     └──→ strategy-state ───────────────┐
                                        ▼
market-data ───────────────────→ decision-engine
                                        │
                   ▼
        notification-outbox
                   │
                   ▼
            monitor-runtime ─────────────────────────→ local-web

market-data ──→ backtest-data ──→ backtest-engine ──→ backtest-results
                      │                  │                    │
                      └──────────────────┴────────────────────┘
                                         │
                                         └──→ backtest-jobs ──┬──→ backtest (CLI compatibility/index)
                                                              └──→ backtest-api ──→ backtest-web
                                                                       ▲                 ▲
                                                                       └──── local-web ──┘

index-identity ──→ index-data ──→ plan-index-conditions
                                         ├──→ monitor-index-view
                                         └──→ backtest-index-data ──→ backtest-index-view
```

After `plan-domain` is approved, `ai-plan-drafting`, `market-data`, and `strategy-state` can be specified and implemented independently. The live decision path never calls AI. `backtest` reuses the pure decision contracts but remains storage-, scheduler-, notification-, and network-isolated during execution.

The approved backtest-module build order is `backtest-data` → `backtest-engine` → `backtest-results` → `backtest-jobs` → `backtest-api` → `backtest-web`. The stable `backtest` id is retained as the documentation umbrella and target CLI compatibility contract rather than being renamed or reused. The current direct CLI MVP remains a baseline until an approved task migrates its adapters to `backtest-jobs`; it is not a second orchestration path. Existing verified code is mapped into the first three modules; this decomposition does not authorize a rewrite of working deterministic logic. `backtest-jobs` owns the atomic job/result Unit of Work and calls result transaction participants; `backtest-results` never imports the job coordinator.

The board-index build order approved on `2026-09-02` is `index-identity` → `index-data` → `plan-index-conditions` → (`monitor-index-view`, `backtest-index-data`) → `backtest-index-view`. Shared snapshots contain data facts only; every condition outcome and trade effect remains owned by an exact path in one Schema v2 plan. Schema v1 plans and historical results remain immutable, and Phase 1 contains no industry index.

## AI Trust Boundary

1. The user pastes or edits a natural-language trade plan.
2. AI returns JSON conforming to the published draft schema, together with source evidence, uncertainty, and unmapped text.
3. The backend treats AI output as untrusted input and validates types, numeric ranges, dates, overlapping zones, position limits, and allowlisted conditions.
4. The Web UI shows source text, extracted fields, omissions, warnings, and version differences together.
5. The user edits as needed and explicitly activates one immutable plan version.
6. During market hours, only `decision-engine` reads the active plan and produces decisions.

AI output cannot directly activate a plan, write SQL, execute code, call a broker, or bypass validation. If AI is unavailable, structured forms and YAML/JSON import remain available.

## Textual Alert Contract

A “textual alert” is a complete, readable, traceable message generated when a buy, reduction, or risk event occurs. It is more than a chart color change or sound. The first release stores messages in the Web alert center and displays an in-app notification; console output is diagnostic, and external webhook delivery is disabled by default.

Every actionable alert must include:

- signal type and severity;
- stock name and symbol;
- evaluation time, market-data time, and data delay;
- current price and suggested quantity;
- satisfied conditions and remaining blockers;
- relevant price zone, risk line, plan version, and event ID;
- next-step guidance;
- `Reminder only; no order will be placed automatically.`

The Chinese renderer uses the equivalent disclaimer `仅提醒，不会自动下单`.

## Confirmed Assumptions

1. “Text required” means both natural-language plan input and complete readable textual alerts.
2. The first AI integration defaults to DeepSeek through its OpenAI-format HTTP contract. The user configures the request profile, service name, base URL, model, timeout, retries, token limit, and API key directly in the Git-ignored `config/app.yaml`, including switching to another reviewed OpenAI-compatible service. Web loads that configuration once at startup; no separate credential source exists.
3. AI credentials may be stored in local application configuration but are never written into plans, logs, or ordinary API responses. The Web UI is read-only for AI configuration and displays only whether the configured key was loaded, never its value.
4. Tushare is the only first-release market-data source. Token, symbol batching, pacing, capability probes, and limits for 1–10 symbols are configurable.
5. The service listens only on the local loopback interface, so the first release has no login system. Origin/CORS restrictions, CSP, input validation, and secret protection still apply.
6. The user records actual fills manually. Neither an alert nor its acknowledgement represents a fill.
7. Backtest fills are simulated research records only. Historical `stk_mins` capability is independent of live `rt_min`/`rt_min_daily`, and cannot complete `T058`.
8. Historical backtest calendars explicitly support only SSE/SZSE; `.BJ` is blocked until a verified BSE calendar exists. Frozen artifacts are hash-verified on read, signal/fill times preserve `receivedAt`/`openAt` identities, and materialized long-lived summary/fill rows can rebuild missing summary JSON/fill CSV without restoring expired detail.
9. Every active backtest timestamp—market, replay, job lifecycle, audit, result publication, persistence, API, and Web display—uses the aware `Asia/Shanghai` business timezone. Canonical RFC 3339 wire/storage text carries explicit `+08:00`; `Z`, offsetless values, and other offsets are rejected. Date-only values use the China-market calendar. Existing UTC-normalized local-MVP result/export bytes remain isolated immutable compatibility artifacts and are not an active/public result until a versioned adoption migration.

## Documentation Language and Parity

- Unsuffixed documents are canonical English inputs for agents and implementation workflows.
- Matching `.zh-CN.md` documents are Chinese review copies for the user.
- Every user-facing project document created or materially changed must update both language versions in the same change.
- Both versions must preserve the same section structure, stable IDs, numeric thresholds, API paths, JSON fields, commands, boundaries, and acceptance criteria.
- Module IDs, filenames, API paths, JSON fields, code identifiers, commands, and third-party interface names remain unchanged in both versions.
- If the two versions conflict or a counterpart is missing, specification approval and downstream implementation are blocked until parity is restored.

## Review Status

The original capability map was approved by the user on 2026-08-18. The isolated hybrid-sync/offline-backtest scope, `SPEC-backtest.md`, and bounded retention policy were approved on 2026-08-25. On 2026-08-26, the user approved the six-module backtest decomposition, English-canonical/Chinese-review documentation rule, and corrected detailed specification set. On `2026-09-02`, the user approved ADR 0003 and the bilingual board-index proposal, then explicitly authorized the six board-index module specifications, implementation, and offline verification. Commit, push, dependency installation, deployment, and real DeepSeek/Tushare/provider network access remain unauthorized. Existing Schema v1 plans, historical results, and the two local commits ahead of `origin/main` remain protected baselines.
