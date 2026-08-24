# Trade Plan Monitor

[中文说明](README.zh-CN.md)

A standalone, local-only Web application for turning reviewed A-share trade plans into deterministic monitoring rules and producing textual and visual reminders. It is designed for one user, at most 10 enabled stocks, Tushare market data, configurable AI-assisted plan drafting, and a single SQLite WAL database.

> Development status: tasks `T001`–`T041` and checkpoints `C00`–`C16` are complete. The repository now includes the reviewed AI drafting boundary, normalized market history and indicators, durable strategy state, the pure deterministic decision engine, deterministic typed Chinese alert rendering, a transactional alert outbox, bounded per-channel in-app/console/optional-Webhook dispatch, an injected-clock A-share minute/official-close scheduler, bounded priority-aware Tushare/AI request isolation, per-symbol canonical-minute orchestration with fail-closed health isolation, serial startup/current-day targeted gap recovery, lossless intraday/official evaluation identities, exact provisional-daily context assembly, atomic evaluation/state/outbox application, post-commit publication, exact official-close reconciliation, durable cross-day `CLOSE_PENDING`, startup close recovery, an owned lifecycle with sanitized health and bounded retryable shutdown, a side-effect-free FastAPI application/lifespan/error boundary, strict dashboard/symbol/bar/event/runtime-health read contracts, injected plan/AI operation APIs with revision/idempotency/audit context, bounded 202 receipts, and write-only secret responses, explicit manual-position, canonical alert-center, acknowledgement, and non-mutating diagnostic APIs, one append-only global monitor-event ledger and sequenced WebSocket replay with committed-event verification, 20-second heartbeats, gap/expiry snapshot recovery, and restart-safe seven-day retention, an exact loopback-Origin boundary, uniform security headers, a 4 MiB raw-request cap, explicit safe Vue-build SPA serving, plus a canonical committed OpenAPI snapshot, generated TypeScript payload/path contracts, and a CSP-compatible Vite document entry. The accessible Vue application shell is next at `T042`, and the multi-stock dashboard starts at `T047`. Default installed-console composition remains explicitly deferred to `T052`–`T054`.

## Product Goals

- Paste a natural-language trading plan and use a user-configured OpenAI-compatible service to create a structured draft.
- Show extracted fields, source evidence, assumptions, warnings, omissions, and version differences for human review.
- Activate only an immutable plan version that passes deterministic validation and explicit user confirmation.
- Monitor at most 10 A-share stocks with Tushare minute, daily, calendar, and daily-limit data.
- Evaluate only complete, fresh market data through a pure deterministic decision engine.
- Persist strategy state, manual position lots, T+1 constraints, audits, alerts, and replay state in SQLite WAL.
- Produce deduplicated, traceable textual and visual reminders without placing orders.
- Provide a local FastAPI REST/WebSocket service and a Vue 3 dashboard bound only to `127.0.0.1`.

## Current Implementation Status

Last verified on 2026-08-24 with CPython 3.14.7.

| Area | Tasks | Status |
|---|---:|---|
| Python and Vue toolchain scaffold | `T001`–`T003` | Complete |
| Plan model, condition DSL, validation, codecs, hashing, and sample plan | `T004`–`T007` | Complete |
| Market-data contracts, A-share sessions, normalization, and Tushare adapter | `T008`–`T010` | Complete |
| SQLite WAL schema, repositories, strategy state, and verified online backup | `T011`–`T014` | Complete |
| AI configuration, write-only secrets, bounded provider adapter, prompts, and extraction | `T015`–`T017` | Complete |
| Idempotent market history, `ta-v1` indicators, and provisional/official close reconciliation | `T018`–`T020` | Complete |
| Typed conditions, low-zone episodes, pressure/risk evaluation, priority, hashes, and replay | `T021`–`T024` | Complete |
| Alert identity, deterministic rendering, transactional outbox, and bounded channel dispatch | `T025`–`T027` | Complete |
| Injected market clock, session-aware deadlines, and bounded Tushare/AI request control | `T028`–`T029` | Complete |
| Per-symbol orchestration, recovery, atomic evaluation, and committed publication | `T030`–`T032` | Complete |
| Official-close reconciliation, durable pending state, and startup retry | `T033` | Complete |
| Owned lifecycle, sanitized health, graceful shutdown, and maintenance CLI boundary | `T034` | Complete |
| Side-effect-free FastAPI app, owned lifespan, shared schemas, and error mapping | `T035` | Complete |
| Dashboard, symbol, bar, event, and runtime-health read APIs | `T036` | Complete |
| Plan versions, draft/import/extraction/activation, and write-only AI-provider operation APIs | `T037` | Complete |
| Manual-position, canonical alert-center, acknowledgement, and diagnostic APIs | `T038` | Complete |
| Global durable monitor-event ledger and sequenced WebSocket replay | `T039` | Complete |
| Local-origin security and explicit Vue-build SPA serving | `T040` | Complete |
| Frozen OpenAPI, generated TypeScript contracts, and Vite document entry | `T041` | Complete |
| Production UI, packaging, and external acceptance | `T042`–`T059` | Pending |

After `T041`, all 1245 backend tests pass. The exact OpenAPI/type/SPA gate contains 13 tests, the combined REST/WebSocket/OpenAPI transport gate contains 156 tests, and the unchanged decision/replay gate remains 273 tests. Whole-tree Ruff, scoped formatting, `compileall`, `pip check`, bilingual parity, generated-contract drift checks, and `git diff --check` pass. The frontend remains at 2 passing tests with type-check and a document-based production build passing. These tests are deterministic and require no live Tushare, AI, Webhook, browser, database, or network listener. The pinned FastAPI/Starlette TestClient currently emits one upstream deprecation warning recommending `httpx2`; it does not affect production behavior. Checkpoint `C16` is complete, and `T042` is next.

## Safety Boundaries

- Reminder only: the system does not submit, cancel, infer, simulate, or reconcile broker orders.
- AI output is untrusted draft data. AI cannot activate plans, execute code, write SQL, call market-data tools, or participate in the live decision path.
- Actual fills and position lots are entered manually; acknowledging an alert never changes a position.
- Non-loopback AI endpoints require HTTPS. Redirects, embedded URL credentials, unbounded retries, compressed provider responses, and oversized responses are rejected.
- Tushare and AI credentials are referenced through protected runtime inputs; raw values must not enter plans, SQLite, logs, audits, exports, fixtures, or ordinary DTOs.
- The generic Webhook is disabled by default, accepts only an exact HTTPS host allowlist, rejects redirects and embedded credentials, and never retains response bodies.
- The target Web service accepts only the exact `127.0.0.1` listener literal and exact configured HTTP Origin. Do not use port forwarding, a reverse proxy, a host alias, or public/LAN exposure; authentication is not implemented.
- HTTP responses carry CSP, frame, content-type, referrer, and permissions protections; production CORS is disabled, and raw request bodies are capped at 4 MiB before stricter field/import limits apply.
- Static SPA serving requires an explicitly supplied build directory with a local `index.html`; it cannot shadow `/api/v1` or `/ws/v1`. Automatic installed-asset discovery remains deferred to `T052`.

Every actionable reminder will include the equivalent of:

```text
Reminder only; no order will be placed automatically.
```

## Architecture

```text
Natural-language plan
        │
        ▼
ai-plan-drafting ──→ reviewed draft ──→ plan-domain ──→ immutable active plan
                                                        │
Tushare ──→ market-data ──→ normalized complete bars    │
                    │                                   │
                    └────────→ strategy-state ←─────────┘
                                      │
                                      ▼
                               decision-engine
                                      │
                                      ▼
                            notification-outbox
                                      │
                                      ▼
                               monitor-runtime
                                      │
                                      ▼
                local-web (FastAPI REST/WebSocket + Vue 3)
```

One Python process will own the FastAPI lifecycle, monitoring runtime, deterministic decision engine, and SQLite WAL database. The Vue 3 single-page application will be built as static assets and served from the same loopback origin. Synchronous Tushare calls and asynchronous AI calls use separate bounded execution paths so AI cannot delay market monitoring.

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14.x (`>=3.14,<3.15`), FastAPI, Uvicorn, Pydantic 2 |
| Persistence | SQLAlchemy 2, Alembic, SQLite WAL |
| Market data | Tushare Pro SDK, pandas |
| AI integration | OpenAI-compatible Chat Completions contract over `httpx` |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router, ECharts |
| Quality | pytest, Ruff, Vitest, Vue Test Utils, Playwright, axe-core |

Dependency versions are pinned in [pyproject.toml](pyproject.toml) and [web/package.json](web/package.json).

## Requirements

- CPython 3.14.x; development is currently verified on Python 3.14.7.
- Node.js `^20.19.0`, `^22.13.0`, or `>=24.0.0` for frontend work.
- npm 11.8.0, as declared by the frontend package.
- A Tushare account with the required interfaces for future live monitoring.
- An optional OpenAI-compatible endpoint and API key for AI-assisted drafting.

Actual Tushare entitlements, rate limits, and realtime-minute timestamp semantics must be confirmed through capability probes and separately authorized live contract tests. They are never assumed from configuration alone.

## Quick Start for Development

Run the following commands from `trade-plan-monitor/` in PowerShell.

### Backend

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/generate_frontend_types.py --check
python -m trade_plan_monitor --help
```

### Frontend toolchain

```powershell
Set-Location web
npm install
npm test -- --run
npm run type-check
npm run build
Set-Location ..
```

The frontend now has a stable CSP-compatible `web/index.html` document entry and generated OpenAPI contracts, while `main.ts` remains the verified toolchain boundary. The production Vue application shell starts at `T042`, and the multi-stock monitoring dashboard at `T047`; do not treat the current minimal document build as the finished application.

### Local configuration

```powershell
Copy-Item config\app.example.yaml config\app.yaml
$env:TUSHARE_TOKEN = "replace-with-your-token"
$env:AI_API_KEY = "replace-with-your-api-key"
```

[config/app.example.yaml](config/app.example.yaml) stores environment-variable references, never secret values. `AI_API_KEY` is optional until AI drafting is configured. Never put secret values in `config/app.yaml`, and do not commit `.env` files, databases, backups, keys, or `web/dist` build output. The generated `openapi.json` and `web/src/api/generated.ts` contracts are intentionally versioned.

## Commands

| Command | Purpose | Availability |
|---|---|---|
| `python -m pytest -q` | Run the complete 1232-test backend gate | Available |
| `python -m pytest tests/unit/test_package.py -q` | Run the stable package smoke test | Available |
| `python -m pytest tests/integration/test_ai_provider_contract.py -q` | Verify the AI provider and extraction contract | Available |
| `python -m pytest tests/unit/test_decision_engine.py tests/replay/test_decision_replay.py -q` | Run the deterministic decision and replay gate | Available |
| `python -m pytest tests/integration/test_tushare_contract.py -q` | Verify deterministic Tushare fixtures | Available |
| `python -m ruff check --no-cache src tests` | Run backend lint checks | Available |
| `python -m compileall -q src/trade_plan_monitor` | Compile-check backend modules | Available |
| `npm test -- --run` | Run frontend unit tests | Available in `web/` |
| `npm run type-check` | Run Vue and TypeScript checks | Available in `web/` |
| `npm run build` | Build frontend static assets | Available in `web/` |
| `python -m trade_plan_monitor validate` | Dispatch configuration/plan validation through an injected runtime service | Service boundary; production composition at `T052`–`T054` |
| `python -m trade_plan_monitor monitor --once` | Dispatch one headless monitoring cycle through an injected runtime service | Service boundary; production composition at `T052`–`T054` |
| `python -m trade_plan_monitor web --host 127.0.0.1 --port 8765` | Reserved loopback-only Web command with strict host/port validation | Inert scaffold until T052 |
| `python -m trade_plan_monitor replay` | Dispatch deterministic replay through an injected runtime service | Service boundary; production composition at `T052`–`T054` |
| `python -m trade_plan_monitor backup` | Dispatch a verified backup through an injected runtime service | Service boundary; production composition at `T052`–`T054` |

Live-provider tests or calls require an explicit authorization step and must never use production credentials in fixtures or command output.

## Project Structure

```text
trade-plan-monitor/
├── config/
│   ├── app.example.yaml
│   └── plans/003043.SZ.sample.yaml
├── src/trade_plan_monitor/
│   ├── ai/             # AI configuration, secrets, provider protocol, HTTP adapter
│   ├── decision/       # Pure conditions, episodes, pressure/risk, priority, hashes
│   ├── domain/         # Plan models, validation, codecs, and stable hashing
│   ├── market_data/    # Normalization, history, aggregation, indicators, reconciliation
│   ├── notifications/  # Deterministic alerts, transactional outbox, channels, and dispatch
│   ├── state/          # SQLite models, migrations, repositories, UoW, backup
│   ├── web/            # FastAPI routes plus local-origin, request-size, and SPA security
│   ├── cli.py          # Side-effect-free commands and injected service dispatch
│   └── config.py       # Strict non-secret application configuration
├── tests/
│   ├── fixtures/
│   ├── integration/
│   ├── replay/
│   └── unit/
├── web/                # Vue/TypeScript toolchain scaffold
├── CAPABILITY-MAP.md
├── SPEC-*.md
├── pyproject.toml
├── README.md
└── README.zh-CN.md
```

The project is standalone and must not import from or modify `TradingAgents/` or other workspace projects.

## Domain Conventions

- Symbols use canonical Tushare form such as `003043.SZ`.
- Prices are persisted as integer fen and quantities as integer shares; conversion happens only at input/output boundaries.
- A-share timestamps are timezone-aware and normalized to `Asia/Shanghai`.
- Buy quantities obey 100-share board lots; sellable lots obey T+1 by trading date.
- Price-zone boundaries have one explicit owner so values such as 64.50 and 68.80 cannot trigger conflicting actions.
- Incomplete, stale, permission-blocked, or source-semantics-unverified data fails closed and cannot create an actionable signal.
- The 15:00 intraday result remains provisional until reconciled with the official daily close.
- Active plan versions are immutable; changes create a new reviewed version.

The checked-in [Huaya Intelligent sample plan](config/plans/003043.SZ.sample.yaml) is the golden example for `003043.SZ`.

## Documentation

Unsuffixed documents are canonical English inputs for agents and implementation workflows. Matching `.zh-CN.md` files are Chinese review copies and must be updated in the same change.

| Document | English | Chinese |
|---|---|---|
| Capability map | [CAPABILITY-MAP.md](CAPABILITY-MAP.md) | [CAPABILITY-MAP.zh-CN.md](CAPABILITY-MAP.zh-CN.md) |
| Plan domain | [SPEC-plan-domain.md](SPEC-plan-domain.md) | [SPEC-plan-domain.zh-CN.md](SPEC-plan-domain.zh-CN.md) |
| AI plan drafting | [SPEC-ai-plan-drafting.md](SPEC-ai-plan-drafting.md) | [SPEC-ai-plan-drafting.zh-CN.md](SPEC-ai-plan-drafting.zh-CN.md) |
| Market data | [SPEC-market-data.md](SPEC-market-data.md) | [SPEC-market-data.zh-CN.md](SPEC-market-data.zh-CN.md) |
| Strategy state | [SPEC-strategy-state.md](SPEC-strategy-state.md) | [SPEC-strategy-state.zh-CN.md](SPEC-strategy-state.zh-CN.md) |
| Decision engine | [SPEC-decision-engine.md](SPEC-decision-engine.md) | [SPEC-decision-engine.zh-CN.md](SPEC-decision-engine.zh-CN.md) |
| Notification outbox | [SPEC-notification-outbox.md](SPEC-notification-outbox.md) | [SPEC-notification-outbox.zh-CN.md](SPEC-notification-outbox.zh-CN.md) |
| Monitoring runtime | [SPEC-monitor-runtime.md](SPEC-monitor-runtime.md) | [SPEC-monitor-runtime.zh-CN.md](SPEC-monitor-runtime.zh-CN.md) |
| Local Web | [SPEC-local-web.md](SPEC-local-web.md) | [SPEC-local-web.zh-CN.md](SPEC-local-web.zh-CN.md) |

Workspace-level implementation plans and execution task lists are maintained outside this standalone Git repository. When documents disagree, the approved module specification takes precedence. Restore bilingual parity before continuing implementation.

## Development Workflow

1. Work on one approved workspace task at a time.
2. Reconcile the task with its module specification and existing code.
3. Add a failing test before changing behavior.
4. Implement the smallest bounded change that makes the test pass.
5. Run focused tests, the complete suite, Ruff, formatting, compilation, dependency, security, and documentation-parity checks.
6. Update both English and Chinese documents when behavior, public contracts, commands, or architecture change.

## Financial Disclaimer

This project is a personal monitoring and reminder tool, not investment advice, a brokerage service, or an order-execution system. Market data, AI output, indicators, and reminders can be delayed, incomplete, or incorrect. The user remains solely responsible for reviewing every plan and making every trading decision.
