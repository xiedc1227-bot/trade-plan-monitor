# Spec: local-web (Local Web Application)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-local-web.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Provide the single local interface for monitoring up to 10 stocks, pasting natural-language plans, configuring AI, reviewing extracted rules, activating immutable versions, inspecting live evidence/charts, maintaining manual positions, reading textual reminders, and diagnosing system health.

FastAPI owns the REST/WebSocket contract and serves a Vue 3 SPA on `127.0.0.1`. The backend is authoritative for all trading conditions; the frontend only manages display state and explicit user commands.

## Tech Stack

Backend version families:

- Python 3.14.x (`>=3.14,<3.15`), FastAPI, Uvicorn, Pydantic 2
- OpenAPI-generated frontend types
- Same-origin static serving in production

Frontend version families:

- Vue 3 with Composition API and `<script setup lang="ts">`
- TypeScript, Vite, Vue Router, Pinia
- Apache ECharts
- Vitest, Vue Test Utils, Playwright, axe-core

Exact patch versions will be selected from official releases and frozen in lock files during scaffolding.

## Commands

```powershell
# Backend API contract
python -m pytest tests/integration/test_web_api.py -q
python -m trade_plan_monitor web --host 127.0.0.1 --port 8765

# Frontend
Set-Location web
npm run test -- --run
npm run type-check
npm run build
npm run test:e2e
```

## Project Structure

```text
src/trade_plan_monitor/web/
├── app.py
├── lifespan.py
├── errors.py
├── schemas.py
├── websocket.py
├── origin_guard.py
└── routers/
    ├── dashboard.py
    ├── symbols.py
    ├── plans.py
    ├── ai.py
    ├── positions.py
    ├── alerts.py
    └── health.py
web/src/
├── api/
├── assets/
├── components/{common,dashboard,symbol,plans,ai,alerts,health}/
├── composables/
├── layouts/
├── stores/
├── views/
├── App.vue
├── main.ts
└── router.ts
```

## REST Contract

Base path: `/api/v1`. JSON fields use camelCase; enum values use `UPPER_SNAKE`. List resources are paginated. Every error has one shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Plan cannot be activated",
    "details": [],
    "requestId": "..."
  }
}
```

### T035 Application and Error Boundary

- `create_app(...)` constructs only the FastAPI adapter. Import and construction do not load configuration, open SQLite, call providers, create tasks, or bind a network socket; no module-level application instance starts hidden work.
- One explicitly injected runtime factory is invoked only when the FastAPI lifespan starts. The lifespan owns exactly one runtime instance, awaits `start()`, accepts a valid `DEGRADED` read-only startup, makes the active instance available through dependency injection, and always awaits `stop()` before clearing it. Starting without a factory fails closed.
- Every request receives a newly generated 32-character lowercase-hex request ID. Caller-supplied IDs are ignored; the same validated value appears in the `X-Request-ID` header and the error body's `requestId`.
- `ApiError`, request-validation errors, HTTP errors, and unexpected exceptions map to the single envelope above. Public outer messages are selected from fixed error codes. Validation details are capped at 100 entries; each location is capped at 16 bounded parts, and only a sanitized code plus `Field required` or `Invalid value` is exposed. Rejected input, Pydantic context, exception cause, secret values, and raw provider/storage bodies are never serialized.
- Shared error schemas are strict, frozen, camelCase-compatible, and revalidate `model_copy(update=...)`. T035 adds no dashboard, symbol, health, plan, position, alert, WebSocket, Origin/security-header, static-file, or network-listener behavior; those remain T036 and later tasks.

### T036 Monitoring Read Boundary

- `create_app(read_service=...)` accepts one explicitly injected `MonitorReadService` without constructing it or starting I/O. The seven T036 routes are async transport adapters over that service; a missing service returns `SERVICE_UNAVAILABLE`. Every service result is revalidated through a closed, immutable response model before serialization, and malformed internal results use the generic error boundary without exposing their rejected values.
- T036 implements `GET /dashboard`, `GET /symbols`, `GET /symbols/{symbol}`, `GET /symbols/{symbol}/bars`, `GET /symbols/{symbol}/events`, `GET /health`, and `GET /health/symbols/{symbol}` under `/api/v1`. It does not implement T037+ commands, alert-center queries, plan/AI resources, WebSocket transport, Origin/security headers, static serving, or production composition.
- List pagination uses `offset` (default `0`, range `0..10000`) and `limit` (default `20`, range `1..100`) and returns exact `items`, `offset`, `limit`, and `total`. Symbol totals are capped at 10 and bar/event totals at 10,000. Bar and event reads require explicit inclusive `startAt` and `endAt` `Asia/Shanghai` timestamps; reversed ranges return `BAD_REQUEST`. Bar reads additionally accept `interval=ONE_MINUTE|FIVE_MINUTES`. Response pagination, range, interval, and symbol identities must match the request. A malformed symbol returns request validation failure; a valid unknown symbol returns `NOT_FOUND`.
- The dashboard returns its committed `sequence`, observation/connection/data-age strip, the six approved counts, and at most 10 isolated symbol summaries. Each summary contains one authoritative deterministic decision projection with `symbol`, `resultHash`, exact plan identity, evaluation/market timestamps, data age, price, zone, signal, position, episode/risk state, typed evidence, and next step. The adapter never evaluates a condition, changes priority, recalculates a decision hash, or reads a second quote stream. Cross-symbol identity, contradictory risk state, mismatched position lots/T+1 availability, and inconsistent ages fail closed.
- Bar responses preserve normalized integer-fen OHLC, shares, exact yuan amount, receipt time, and aggregate formula provenance. Event responses preserve symbol, sequence, stable event ID/type, timestamp, optional signal/result hash, and bounded server-authored plain text. All JSON field names are camelCase and all enum values are `UPPER_SNAKE`.
- Runtime health exposes only stable lifecycle/resource/capability states, retry/cooldown/poll times, ordered gaps, bounded executor counts, database/WAL/checkpoint/backup facts, and delivery counters. Symbol health exposes the exact data age/completeness/freshness/gap facts. `LIVE` requires fresh, complete data with a latest timestamp; disconnected, stale, gapped, blocked, or otherwise contradictory data cannot be labelled live or actionable. No response schema has a secret, authorization detail, raw provider body, or raw storage-error field.

Read resources:

```text
GET /dashboard
GET /symbols
GET /symbols/{symbol}
GET /symbols/{symbol}/bars
GET /symbols/{symbol}/events
GET /plan-versions
GET /plan-versions/{id}
GET /plan-extractions/{id}
GET /ai-providers
GET /alerts
GET /position-lots
GET /health
GET /health/symbols/{symbol}
```

Write resources:

```text
POST  /plan-drafts                 create or edit a structured draft
POST  /plan-imports                safe YAML/JSON import to draft
POST  /plan-extractions            submit natural-language AI extraction; returns 202 + id
POST  /plan-activations            activate one validated immutable version
POST  /plan-deactivations          disable a symbol's active plan
POST  /ai-providers                create non-secret provider configuration
PATCH /ai-providers/{id}           update non-secret configuration/revision
POST  /ai-provider-secrets         write or replace a secret; never readable
POST  /ai-provider-tests           create a bounded connection-test operation
POST  /position-lots               record a manual fill
POST  /position-lot-closures       record a manual reduction
POST  /alert-acknowledgements      acknowledge one alert
POST  /diagnostic-evaluations      non-mutating manual evaluation request
```

All state-changing requests require `Idempotency-Key`; mutable resources require `expectedRevision`. Duplicate in-flight intent returns 409; key reuse with a different request hash returns 422. Plan extraction and provider tests are bounded asynchronous operations and never run in request handlers after returning 202.

OpenAPI is committed as a snapshot and used to generate TypeScript types; frontend contracts are not hand-copied.

## WebSocket Contract

Endpoint: `/ws/v1/monitor?after=<sequence>`.

The browser loads an authoritative REST dashboard snapshot and its sequence before applying incremental events. Committed event types include:

- `symbol.snapshot.updated`
- `symbol.health.updated`
- `alert.created`
- `alert.acknowledged`
- `plan.extraction.updated`
- `plan.activated`
- `plan.deactivated`
- `position.updated`
- `ai.provider.updated`
- `system.health.updated`
- `snapshot.required`

Heartbeat is 20 seconds. The client reconnects with capped exponential backoff and jitter. Sequence gaps or expired replay windows force a new REST snapshot. Disconnected or stale data is visibly labelled and never presented as live.

## Information Architecture

### `/` — Monitoring Overview

- Market/provider/connection/data-age status strip.
- Counts for actionable, low-zone watch, blocked, risk, stale, and normal states.
- Dense sortable watchlist for up to 10 stocks: price, zone, condition progress, signal, position, risk distance, market-data time, and health.
- Search/filter plus a dedicated actionable-alert rail.

### `/stocks/:symbol` — Stock Detail

- Candlestick chart with low/pressure/risk zones, indicators, episode low, and alert markers.
- Source time/data age, plan version, position lots, T+1 state, and current decision.
- Condition checklist with numeric evidence and blockers.
- Episode/risk timeline, indicator tables, alerts, and provider diagnostics.
- Accessible tabular alternative to chart-only information.

### `/plans` and `/plans/:id` — Plan Workbench

- Version list and active/draft status.
- Natural-language source editor.
- AI provider selector and extraction progress.
- Side-by-side source evidence, structured fields, assumptions, warnings, omissions, and validation issues.
- Sectioned structured editor and human-readable executable preview.
- Version diff plus explicit activation/deactivation confirmation.
- YAML/JSON import and export.

### `/alerts` — Alert Center

- Paginated textual reminders and health alerts.
- Symbol/type/time/acknowledgement filters.
- Expandable evidence, blockers, event ID, and chart-time link.
- Acknowledgement language explicitly states that it is not a fill.

### `/system` — System and AI Settings

- Tushare capabilities, latency, cooldown, next poll, gaps, executor, database/WAL, backup, and delivery health.
- AI provider/base URL/model/limits/prompt-version configuration.
- Write-only API-key replacement, masked configured state, and bounded connection test.
- No secret values or raw authorization errors are displayed.

## Vue Component Map

Route views are composition surfaces only.

| Component | Responsibility | Inputs | Outputs |
|---|---|---|---|
| `AppShell` | Navigation, connection banner, route outlet | connection/health | navigation |
| `MarketStatusStrip` | Market/provider/polling health | system health | open system |
| `WatchlistToolbar` | Search/filter/sort/view mode | preferences | typed changes |
| `WatchlistTable` / `WatchlistRow` | Render normalized symbol summaries | symbol summaries | select symbol |
| `ConditionProgress` | Render pass/partial/block evidence | condition states | none |
| `AlertRail` / `AlertTable` | Recent and historical reminders | alert summaries/page | select/acknowledge |
| `PriceChart` | ECharts bars/zones/markers | immutable chart series | range change |
| `EpisodeTimeline` | Episode/risk transitions | timeline events | select time |
| `PositionLots` | Lots and T+1 status | position summary | add/close request |
| `PlanWorkbench` | Orchestrate extraction/review/edit/activation | draft/extraction | save/activate |
| `SourceTextEditor` | Plain-text plan input | source text | update text |
| `AIProviderSelector` | Choose/test configured provider | providers/status | select/test |
| `ExtractionEvidence` | Evidence, uncertainty, omissions | extraction result | resolve issue |
| `StructuredPlanEditor` | Sectioned typed draft editing | plan draft/issues | update draft |
| `ActivationDiffDialog` | Confirm immutable version switch | before/after/issues | confirm/cancel |
| `HealthMatrix` | Provider/symbol health | health rows | select symbol |

The `monitor` Pinia store owns normalized snapshot/event state with readonly views and explicit `applySnapshot`, `applyEvent`, and recovery actions. Route-local plan forms remain local. `useMonitorStream`, `useSymbolFilters`, and `useChartSeries` contain lifecycle and derived logic. ECharts instances and large immutable series use shallow refs. Components use typed props/emits and never mutate shared records directly.

## Visual and Accessibility Direction

Use an industrial signal-console aesthetic: graphite/ink surfaces, fine technical grid, mineral-white text, brass/amber watch state, muted sea-glass live state, vermilion reserved for real risk, and sparse cyan information accents. Use tabular numerals and clear decimal alignment. Avoid purple gradients, glass-card excess, oversized KPI tiles, and decorative stock imagery.

- Target WCAG 2.1 AA contrast.
- Do not rely on red/green alone; use labels, icons, and shapes.
- Full keyboard navigation, visible focus, skip-to-content, and labelled forms/dialogs/tables.
- `aria-live` polite for status and assertive only for time-sensitive actionable/risk reminders.
- Respect reduced motion.
- Work at 320, 768, 1024, and 1440px widths.
- Never use unsanitized `v-html`; plan and AI text is escaped plain text.

## Local Security Boundary

- The production command binds exactly to `127.0.0.1`; remote/LAN mode is out of scope.
- SPA/API/WebSocket share one origin; production CORS is disabled and unexpected HTTP/WebSocket origins are rejected.
- No login or authentication is implemented for MVP. Documentation forbids port forwarding or public exposure.
- CSP, frame denial, content-type, referrer, and permissions headers are set.
- Request body/text/import sizes are bounded; YAML uses safe loading.
- AI base URLs accept HTTPS, with an explicit loopback exception for a user-run local model; redirects and embedded credentials are rejected.
- Secrets are write-only and redacted from responses, frontend state, exports, logs, and errors.
- All plan, provider, position, acknowledgement, and activation changes create audit entries.

## Code Style

```vue
<script setup lang="ts">
interface Props {
  extraction: PlanExtraction
}

interface Emits {
  resolveIssue: [issueId: string]
}

defineProps<Props>()
const emit = defineEmits<Emits>()
</script>

<template>
  <button type="button" @click="emit('resolveIssue', extraction.id)">
    标记为已处理
  </button>
</template>
```

Use `<script setup lang="ts">`, PascalCase SFCs, script/template/scoped-style order, feature folders, pure computed derivations, and watchers only for side effects with cleanup.

## Testing Strategy

- Backend contract tests for every endpoint, schema, error shape, pagination, idempotency, optimistic conflict, origin guard, secret redaction, and OpenAPI snapshot.
- WebSocket tests for snapshot consistency, ordering, replay, sequence gap, reconnect, and restart.
- Vue unit tests for stores, plan workbench, AI extraction review, activation gates, watchlist, details, alerts, settings, loading/error/empty states, and keyboard interactions.
- Chart mapping tests plus accessible table fallback.
- Playwright end-to-end flows: configure a fake AI provider, paste a plan, extract, resolve a warning, activate, replay market data, receive one alert, acknowledge it, and verify no position change.
- Accessibility automation with axe plus keyboard/manual checks.
- Browser verification at desktop, tablet, and mobile widths.

## Boundaries

- Always: the backend is authoritative for executable rules and validation.
- Always: display data freshness and connection state honestly.
- Always: require confirmation for activation and position changes.
- Ask first: add authentication, remote access, OS browser notifications, or a new external message channel.
- Never: expose secrets, duplicate rule logic in Vue, or treat acknowledgement as a fill.
- Never: render AI/user text as raw HTML.
- Never: allow an extraction request to directly activate a plan.

## Success Criteria

- One local URL supports the complete text-plan-to-reviewed-active-plan workflow.
- Dashboard and detail views show all 10 symbols independently and update without full-page refresh.
- A disconnected browser recovers from a consistent snapshot and never labels stale data as live.
- AI configuration is usable while secret values remain unreadable after submission.
- The plan cannot activate while material omissions or validation errors remain.
- One deterministic buy event appears as one textual reminder with evidence and disclaimer.
- UI meets keyboard, contrast, responsive, reduced-motion, and non-color-only requirements.
- No normal startup path listens beyond loopback.

## Open Questions

None blocking. OS-level browser notifications and named chat platforms remain future opt-in channels.
