# Trade Plan Monitor

Trade Plan Monitor is a local-first, AI-assisted monitor for deterministic A-share trade
plans. It turns reviewed plans and normalized market data into explainable reminders; it does
not place orders.

[简体中文](README.zh-CN.md)

## Product Status

Tasks `T001` through `T053` are implemented. The packaged command can serve the built Vue SPA,
REST API, and WebSocket routes on exact loopback. Until the application service composition is
wired, that installed entry intentionally starts in read-only `DEGRADED` mode: the UI is
available, but business API dependencies return `SERVICE_UNAVAILABLE` instead of inventing live
state.

The deterministic test suite does not use live Tushare, AI, Webhook, or other external services.
Live provider checks remain separately authorized operations.

## Safety Boundaries

- The system is monitoring and reminder software, not a broker, order router, or investment
  adviser. Every actionable reminder carries the literal `仅提醒，不会自动下单。`
- Plans are typed, reviewed, versioned, and immutable after activation. AI output remains an
  untrusted draft until deterministic validation and user review succeed.
- Prices are stored as integer fen, quantities as integer shares, and A-share timestamps as
  timezone-aware `Asia/Shanghai` values.
- Missing, stale, unauthorized, or semantically unverified market data fails closed.
- Secrets are environment references or write-only secret-store material, never YAML values,
  database columns, API responses, logs, or exports.
- The Web listener accepts only the literal `127.0.0.1`; authentication is not implemented.

## Quick Start

The following PowerShell workflow starts the packaged local UI from a clean source checkout.
Dependency installation needs package-registry access once; the verification and startup steps
make no live Tushare, AI, or Webhook call.

### 1. Requirements

- CPython 3.14.x (`>=3.14,<3.15`); development is verified with Python 3.14.7.
- Node.js `^20.19.0`, `^22.13.0`, or `>=24.0.0` and npm 11.8.0.
- Windows PowerShell, with the current directory set to `trade-plan-monitor/`.

### 2. Install from a clean checkout

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Push-Location web
npm install --include=optional --no-package-lock
npm run build
Pop-Location
```

`npm run build` keeps the ordinary `web/dist/index.html` output and copies the same complete
build into the ignored Python package staging directory. The installed Web command does not fall
back to the current working directory or the frontend source tree when those assets are absent.

### 3. Configure local references

```powershell
Copy-Item config\app.example.yaml config\app.yaml
```

The YAML file contains only non-secret provider settings and environment-variable names. The
versioned example selects the verified `https://api.quicksync.cn` Tushare-compatible endpoint;
the local `config/app.yaml` copy is ignored by Git. For UI-only offline startup, leave the two
variables unset. Before an explicitly authorized live provider run, set placeholders in the
current process or your OS secret manager:

```powershell
$env:TUSHARE_TOKEN = "replace-with-your-tushare-token"
$env:AI_API_KEY = "replace-with-your-openai-compatible-api-key"
```

[.env.example](.env.example) is a versioned name/template reference; the application does **not**
automatically load `.env` files. Never put a token or API key in `config/app.yaml`, and never
commit `config/app.yaml`, `.env`, databases, backups, keys, or build output.

The current read-only packaged fallback accepts the configuration path but does not resolve these
provider references. The future injected application composition must load the strict YAML before
it can use them; `DEGRADED` startup never proves provider configuration is valid or active.

### 4. Start the packaged local Web UI

```powershell
trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` on the same computer. Stop the foreground process with `Ctrl+C`.
At the current composition checkpoint, expect the read-only `DEGRADED` state described above.

### 5. Offline verification

```powershell
python -m trade_plan_monitor --help
python -m pytest tests/unit/test_package.py tests/integration/test_packaging.py -q
Push-Location web
npm test -- --run
npm run type-check
npm run build
Pop-Location
```

These checks validate the installed entry, package assets, frontend tests, types, and production
build without contacting a live provider.

## Commands

Run backend commands from `trade-plan-monitor/` and frontend commands from `web/` unless the
command changes directories itself.

| Command | Purpose | Current availability |
|---|---|---|
| `trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765` | Serve packaged SPA, API, and WebSocket routes | Available; business services remain read-only/unavailable until composition |
| `python -m trade_plan_monitor --help` | Show the stable installed command surface | Available |
| `python -m pytest -q` | Run the complete backend suite | Available; offline |
| `python -m ruff check --no-cache src tests` | Run backend lint | Available; offline |
| `python -m compileall -q src/trade_plan_monitor` | Compile-check backend modules | Available; offline |
| `python scripts/generate_frontend_types.py --check` | Detect OpenAPI/generated TypeScript drift | Available; offline |
| `npm test -- --run` | Run frontend unit tests | Available in `web/`; offline |
| `npm run type-check` | Check Vue and TypeScript | Available in `web/`; offline |
| `npm run build` | Build and stage production SPA assets | Available in `web/`; offline after dependencies are installed |
| `python -m trade_plan_monitor validate` | Dispatch configuration/plan validation | Injection boundary; not wired by the packaged fallback |
| `python -m trade_plan_monitor monitor --once` | Dispatch one headless monitor cycle | Injection boundary; not wired by the packaged fallback |
| `python -m trade_plan_monitor replay` | Dispatch deterministic replay | Injection boundary; not wired by the packaged fallback |
| `python -m trade_plan_monitor backup` | Dispatch verified online backup | Injection boundary; not wired by the packaged fallback |

An injection-boundary command raises `runtime service factory is not configured` when invoked
through the current standalone console entry. This is an explicit incomplete-composition signal,
not a successful no-op.

## Architecture

```text
reviewed text ─→ AI drafting ─→ typed plan validation ─→ immutable active plan
                                      │                         │
Tushare ─→ normalized complete bars ──┴──→ deterministic decision engine
                                                    │
                                                    ▼
                                         transactional outbox
                                                    │
                                                    ▼
                                            monitor runtime
                                                    │
                                                    ▼
                           FastAPI REST/WebSocket + packaged Vue SPA
                                                    │
                                                    ▼
                                      127.0.0.1:8765 only
```

The target runtime is one Python process owning FastAPI lifecycle, the monitor runtime,
deterministic decision engine, SQLite WAL state, and local Vue SPA. Synchronous Tushare work and
asynchronous AI work use separate bounded execution paths so AI latency cannot stall market-data
monitoring. Repositories never perform network I/O.

## Tushare Capabilities

The adapter exposes one independent capability probe and five normalized operations:

| Normalized operation | Tushare interface | Use |
|---|---|---|
| `realtime_minutes` | `rt_min` | Requested-symbol real-time minute rows |
| `current_day_minutes` | `rt_min_daily` | Current trading-day one-minute rows |
| `trading_calendar` | `trade_cal` | Trading-day/session decisions |
| `daily_limits` | `stk_limit` | Official daily up/down limits |
| `daily_bars` | `daily` | Official unadjusted daily bars |

The non-secret example configuration selects `https://api.quicksync.cn`. The
`create_tushare_client` factory resolves `TUSHARE_TOKEN` only at runtime and sets the endpoint on
one official `tushare==1.4.29` `DataApi` instance instead of mutating the SDK's process-global
endpoint. Plain HTTP, embedded credentials, query strings, and fragments are rejected.

An explicitly authorized check on 2026-08-25 verified `stk_mins` through both HTTPS and the
official SDK: one `600000.SH` trading day returned 241 one-minute rows for 2026-08-24, covering
09:30:00 through 15:00:00 with the expected eight fields and no duplicate, null-required,
invalid-OHLC, negative-flow, or wrong-symbol row. This makes the endpoint suitable as a future
historical-minute backtest source; it does not replace the separately required live `rt_min` and
`rt_min_daily` capabilities, and the current packaged read-only fallback still does not compose a
backtest runtime.

Set `TUSHARE_TOKEN` only for a separately authorized live capability probe. Capability, account
permission, rate limit, and minute-label semantics are discovered independently; configuration
never implies availability. A denied or unverified required capability blocks actionable output.
The default contract suite uses deterministic fake DataFrames:

```powershell
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
```

## AI Secrets

`AI_API_KEY` is optional unless AI-assisted drafting is enabled. The committed YAML stores only
its environment-variable name. Runtime provider configuration stores a non-secret reference,
model, bounded timeout/retry/token limits, and an HTTPS base URL (plain HTTP is accepted only for
an explicit loopback host).

API-key material is write-only through the secret boundary and cannot be returned through the
public contract. Redirects, embedded URL credentials, query-bearing base URLs, raw model
execution, and secret-bearing validation errors are rejected. AI output is never activated
directly.

## Backup and Restore

### Create and verify

The backup service uses SQLite's online backup API while WAL writes may continue. It writes a
temporary candidate, runs `PRAGMA integrity_check`, atomically publishes only a verified
`monitor-backup-*.sqlite3` file, and then applies retention. Never copy an in-use `.sqlite3`,
`-wal`, or `-shm` file as a backup.

The current standalone `backup` command is not yet composed, so do not assume it created a file.
When a runtime integration supplies the database and backup-directory paths, verify every result
before restore. This read-only command is the supported verification boundary; replace the
placeholder with one candidate path:

```powershell
$env:TPM_BACKUP_PATH = "backups\<verified-backup>.sqlite3"
python -c "import os; from trade_plan_monitor.state.backup import verify_sqlite_backup; result = verify_sqlite_backup(os.environ['TPM_BACKUP_PATH']); print(result.integrity_check, result.schema_object_count)"
```

Proceed only when the first value is exactly `ok`.

### Restore

1. Stop the foreground Web/monitor process; never restore into an open database.
2. Resolve the intended database and backup to exact local paths. Do not use a glob.
3. Run `verify_sqlite_backup` as above.
4. Move the existing database **and any same-name `-wal`/`-shm` sidecars** to one dated recovery
   location rather than deleting or leaving them beside the restore target.
5. Copy the single verified backup to the now-empty configured database path, start the
   application, and
   confirm health before removing the recovery copy.

The application configuration schema does not yet expose database or backup paths; those are
runtime-composition inputs. Unknown YAML fields are rejected, so do not invent `database` or
`backup` sections in `config/app.yaml`.

## Retention

- Verified online backups retain the newest **30 successful backups**. Cleanup considers only
  owned `monitor-backup-*.sqlite3` files inside the configured backup directory, verifies each
  candidate again, and ignores unrelated, invalid, or symlinked files.
- Alert replay and durable monitor-event replay use a default **7-day** replay window. A cursor
  older than retained history fails explicitly instead of silently skipping events.
- No general-purpose automatic deletion policy exists for plans, audits, positions, market bars,
  or the primary SQLite database. Manage those only through a future approved operation, not a
  filesystem wildcard.

## Webhook Defaults

The generic Webhook channel defaults to:

| Setting | Default |
|---|---|
| `enabled` | `false` |
| `endpoint` | `null` |
| `allowlisted_hosts` | empty |
| `timeout_seconds` | `5` |
| `allow_redirects` | `false` and cannot be enabled |

`config/app.example.yaml` intentionally has no `webhook` section; the strict application schema
would reject one. Enabling Webhook delivery requires explicit runtime composition with one HTTPS
endpoint whose exact host is allowlisted. Wildcards, embedded credentials, query strings,
fragments, redirects, and response-body persistence are rejected. Keep it disabled unless an
approved receiver and secret-handling procedure exist.

## Troubleshooting

| Symptom | Meaning and action |
|---|---|
| `WEB_ASSETS_UNAVAILABLE` | The installed distribution lacks a complete Vite build. Run `npm install --include=optional --no-package-lock` and `npm run build` before building/reinstalling the Python package; do not add a cwd fallback. |
| `Cannot find native binding` from Rolldown | npm omitted Vite's platform-specific optional package. Run `npm install --include=optional --no-package-lock`, then retry `npm run build`. |
| UI shows `DEGRADED` or APIs return `SERVICE_UNAVAILABLE` | Expected from the current packaged read-only fallback. It does not mean live monitoring is running. |
| `runtime service factory is not configured` | `validate`, `monitor`, `replay`, or `backup` was invoked before application service composition is wired. |
| Host validation rejects the listener | Use the exact literal `127.0.0.1`; `localhost`, `::1`, `0.0.0.0`, hostnames, and LAN addresses are intentionally rejected. |
| Port 8765 is busy | Stop the other local process or choose another unused port from 1–65535, keeping host `127.0.0.1`. |
| YAML reports an unknown field | Start again from `config/app.example.yaml`; the schema deliberately rejects unsupported sections and literal secrets. |
| Tushare capability is `DENIED`/`UNVERIFIED` | Check the process environment and account permission, then run only an authorized live probe. Never bypass the blocker. |
| AI returns configuration/authentication errors | Keep the key in `AI_API_KEY`, verify the non-secret provider URL/model, and do not place credentials in a URL or YAML. |
| Frontend generated types drift | Run `python scripts/generate_frontend_types.py --check`; regenerate only as part of an approved API-contract change. |

## No Port Forwarding

Use the application only from the same desktop that owns the process. Do **not** bind to
`0.0.0.0`, a LAN address, `localhost`, or `::1`; do not use SSH/IDE port forwarding, reverse
proxies, tunnels, container port publishing, host aliases, or router exposure. The exact Origin
guard and loopback listener are security boundaries, not deployment inconveniences.

Because there is no login or remote-user authorization, forwarding `127.0.0.1:8765` would expose
sensitive plans, positions, health data, and mutation endpoints outside the supported threat
model. Remote access requires a separately designed and reviewed authentication/deployment model.

## Project Structure

```text
trade-plan-monitor/
├── config/                   # Non-secret app references and sample plan
├── src/trade_plan_monitor/
│   ├── ai/                   # AI configuration, secrets, adapter, extraction
│   ├── decision/             # Deterministic conditions, risk, priority, hashes
│   ├── domain/               # Typed plans, validation, codecs, stable hashes
│   ├── market_data/          # Tushare normalization, sessions, bars, indicators
│   ├── notifications/        # Alert models, outbox, channels, dispatch
│   ├── runtime/              # Monitoring, recovery, lifecycle, health
│   ├── state/                # SQLite WAL, migrations, repositories, backup
│   └── web/                  # FastAPI routes, security, packaged SPA assets
├── tests/                    # Unit, integration, replay, fixtures
├── web/                      # Vue 3 / TypeScript source and tooling
├── SPEC-*.md                 # Canonical English module contracts
├── pyproject.toml
├── README.md
└── README.zh-CN.md
```

The project is standalone and must not import from or modify the workspace's `TradingAgents/`
upstream checkout.

## Domain Conventions

- Symbols use standard Tushare form, for example `003043.SZ`.
- Buy quantities follow 100-share board lots; sellable lots follow A-share T+1 by trading date.
- Price-zone boundaries have one owner, so an exact boundary cannot trigger conflicting actions.
- A 15:00 intraday result remains provisional until reconciled with the official daily bar.
- Active plan versions are immutable; changes create a new reviewed version.

The [Huaya Intelligent sample plan](config/plans/003043.SZ.sample.yaml) is the repository's golden
example.

## Documentation

Unsuffixed documents are canonical English inputs for agents and implementation workflows. The
matching `.zh-CN.md` files are Chinese review copies and must remain semantically equivalent in
the same change.

| Contract | English | Chinese |
|---|---|---|
| Capability map | [CAPABILITY-MAP.md](CAPABILITY-MAP.md) | [CAPABILITY-MAP.zh-CN.md](CAPABILITY-MAP.zh-CN.md) |
| Plan domain | [SPEC-plan-domain.md](SPEC-plan-domain.md) | [SPEC-plan-domain.zh-CN.md](SPEC-plan-domain.zh-CN.md) |
| AI drafting | [SPEC-ai-plan-drafting.md](SPEC-ai-plan-drafting.md) | [SPEC-ai-plan-drafting.zh-CN.md](SPEC-ai-plan-drafting.zh-CN.md) |
| Market data | [SPEC-market-data.md](SPEC-market-data.md) | [SPEC-market-data.zh-CN.md](SPEC-market-data.zh-CN.md) |
| Strategy state | [SPEC-strategy-state.md](SPEC-strategy-state.md) | [SPEC-strategy-state.zh-CN.md](SPEC-strategy-state.zh-CN.md) |
| Decision engine | [SPEC-decision-engine.md](SPEC-decision-engine.md) | [SPEC-decision-engine.zh-CN.md](SPEC-decision-engine.zh-CN.md) |
| Notification outbox | [SPEC-notification-outbox.md](SPEC-notification-outbox.md) | [SPEC-notification-outbox.zh-CN.md](SPEC-notification-outbox.zh-CN.md) |
| Monitor runtime | [SPEC-monitor-runtime.md](SPEC-monitor-runtime.md) | [SPEC-monitor-runtime.zh-CN.md](SPEC-monitor-runtime.zh-CN.md) |
| Local Web | [SPEC-local-web.md](SPEC-local-web.md) | [SPEC-local-web.zh-CN.md](SPEC-local-web.zh-CN.md) |

## Development Workflow

1. Implement one approved workspace task at a time.
2. Read the task, module contracts, and current code before editing.
3. Add a failing test or contract check before behavior/documentation changes.
4. Run affected tests, full regression, Ruff, formatting, compile, dependency, security, and
   bilingual parity gates.
5. Update English and Chinese documents together whenever behavior, commands, architecture, or a
   public contract changes.

## Financial Disclaimer

This project is a personal monitoring and reminder tool. It is not investment advice, a broker,
or an order-execution system. Market data, AI output, indicators, and reminders may be delayed,
incomplete, or incorrect. Users must review every plan and remain solely responsible for every
trading decision.
