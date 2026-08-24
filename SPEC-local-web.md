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
python -m pytest tests/integration/test_openapi_snapshot.py -q
python scripts/generate_frontend_types.py --check
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

### T037 Plan and AI Operation Boundary

- `create_app(plan_service=..., ai_service=...)` accepts explicit `PlanOperationService` and `AIOperationService` adapters without constructing either service or starting database, provider, task, or network work. Missing services fail closed with `SERVICE_UNAVAILABLE`. The application services own atomic idempotency claims/replay, optimistic-revision checks, persistence, and audit insertion; the HTTP layer passes a validated `Idempotency-Key` plus the server-generated `requestId` as one `MutationContext`.
- T037 implements `GET /plan-versions`, `GET /plan-versions/{id}`, `GET /plan-extractions/{id}`, `GET /ai-providers`, `POST /plan-drafts`, `POST /plan-imports`, `POST /plan-extractions`, `POST /plan-activations`, `POST /plan-deactivations`, `POST /ai-providers`, `PATCH /ai-providers/{id}`, `POST /ai-provider-secrets`, and `POST /ai-provider-tests`. It does not implement T038 position/alert/diagnostic resources, WebSocket publication, Origin/security headers, static serving, production service composition, or any T024 decision behavior.
- Plan versions expose one canonical bounded `planJson` document, exact plan/version/symbol/hash identity, preserved bounded `sourceText`, review issues, deterministic validation issues, `canActivate`, status, revision, and creation time. Service output is revalidated and must match the requested draft/import identity and provenance. `planJson` remains the canonical `plan-domain` JSON document; surrounding API fields remain camelCase. Empty pages remain valid when `offset` is beyond `total`.
- Draft saves accept `planJson`, `sourceText`, `reviewIssues`, and `expectedRevision`. Imports accept `format=JSON|YAML`, a safe bounded `document`, and `expectedRevision`. Activation is a distinct command over an immutable `planVersionId`; deactivation is a distinct symbol command. An unresolved assumption, warning, missing-evidence item, material omission, or activation-blocking validation issue makes `canActivate=false`, and the application service must reject activation with a conflict.
- Plan extraction and AI-provider testing accept only a bounded submission command and return `202` with a typed `QUEUED` receipt. The route awaits only the service's durable submission boundary; it neither calls a provider nor creates/runs extraction work and it never activates a plan. Extraction status is closed over `QUEUED`, `RUNNING`, `SUCCEEDED`, `INVALID_OUTPUT`, `PROVIDER_ERROR`, and `CANCELLED`; successful results retain exactly one activation-blocking `AI_EVIDENCE_REVIEW_REQUIRED` and expose only canonical draft JSON, bounded evidence/issues, deterministic validation results, sanitized usage, hashes, and timestamps. Raw model/provider bodies and authorization material have no response field.
- AI-provider create/update uses the complete non-secret configuration. `PATCH` is a revision-guarded full replacement whose body `providerId` must match the path. The API revalidates it through the concrete `AIProviderConfig` class-local sanitized validator, including HTTPS/loopback URL policy and resource limits. Secret replacement accepts the existing class-local `SecretWrite` value but responses contain only `SecretStatus`-equivalent configured/source/fixed-mask/generation metadata. Service-returned configuration must match the submitted normalized configuration; extra secret or raw-provider fields fail closed.
- Every T037 state-changing endpoint requires an `Idempotency-Key` of 1–128 allowlisted characters and an `expectedRevision`. Duplicate in-flight intent maps to 409, the same key with a different request hash maps to 422, and completed identical intent replays its canonical response. Application services must perform those checks and their audit write atomically; the routers never reconstruct repository, validation, or decision-engine behavior.

### T038 Position, Alert, and Diagnostic Boundary

- `create_app(position_service=..., alert_service=...)` accepts explicit `PositionOperationService` and `AlertOperationService` adapters without constructing repositories, opening SQLite, evaluating a plan, or starting work. Missing services fail closed with `SERVICE_UNAVAILABLE`. The application services own atomic idempotency, optimistic revision checks, plan-owned maximum-position policy, T+1/calendar policy, persistence, and audit insertion.
- T038 implements `GET /position-lots`, `POST /position-lots`, `POST /position-lot-closures`, `GET /alerts`, `POST /alert-acknowledgements`, and `POST /diagnostic-evaluations`. It does not implement T039 WebSocket publication/replay, T040 Origin/security/static serving, production service composition, or any T024 decision priority/hash/replay change.
- Position pages require one exact symbol and explicit `asOfTradeDate`, echo the requested pagination/filter identity, and expose only bounded manual-lot facts plus the T+1 sellable projection. Manual creation requires an explicit 100-share board-lot quantity, bucket, acquisition trade date, integer-fen cost, optional related alert, and `expectedRevision=0`; a new lot starts at revision `0`. Reduction is a separate explicit command over one lot, quantity, trade date, and expected revision. A lot's durable revision is `(quantity - remainingQuantity) / 100`, so every reduced board lot advances it once without a new storage column. The reduction response binds the exact applied quantity and trade date to before/after remaining quantities and the resulting lot, and it cannot report a successful reduction on or before acquisition. The application service rejects maximum-position, remaining-quantity, trading-calendar T+1, and stale-revision conflicts before committing its position audit.
- Alert pages use bounded `offset`/`limit` and optional symbol, actionable signal type, acknowledgement, and paired inclusive Shanghai-time filters. The page echoes those filters, rejects duplicate event IDs or sequences, and revalidates each complete canonical `AlertEvent`, including dedup identity, severity, relevant zone, next step, evidence/node/fact/numeric budgets, deterministic renderer output, and acknowledgement timestamps. A position prefill is a non-submitting value whose symbol/quantity/bucket/target/event identity must exactly match the alert; it never invokes the position service.
- Alert acknowledgement is a distinct idempotent audited command. Alert revision is the durable acknowledgement state: `0` while unacknowledged and `1` once acknowledged. The first acknowledgement requires revision `0` and returns `1`; an acknowledgement against already acknowledged revision `1` is a no-op that remains `1`, while any stale revision conflicts. The response must identify the requested event and contain an acknowledgement time. The route cannot create, close, or otherwise change a position; acknowledgement remains separate from delivery success and from a fill.
- A diagnostic command names exactly one canonical `INTRADAY` five-minute session boundary or one `OFFICIAL_CLOSE` trade date. The service returns one canonical self-validating `EvaluationResult`; the adapter revalidates its `resultHash`, embedded evaluation identity, and complete result before projecting the authoritative decision. That embedded identity must contain the same `planHash`, symbol, kind, typed target, and `formulaVersion` as both the result and request, together with the exact source revision. The strict response requires `stateMutationApplied=false`, `alertEnqueued=false`, and `positionChanged=false`; an optional diagnostic audit is the only permitted write. The router does not call or reimplement the decision engine.
- Every T038 POST requires the bounded `Idempotency-Key` and `expectedRevision`. Duplicate in-flight intent maps to 409, key reuse with a different request hash maps to 422, and an identical completed command replays its canonical response. Service response pagination, filters, identities, target, revisions, severity, evidence partitions, and position shapes are revalidated before serialization; extra provider/storage/secret fields fail closed behind the generic error boundary.

### T040 Local-Origin and Static-Build Boundary

- `create_app(bind_host="127.0.0.1", bind_port=8765, static_directory=...)` validates the listener identity without binding a socket. The only accepted host literal is `127.0.0.1`, ports are limited to `1..65535`, and the reserved `web` CLI rejects wildcard, LAN, alias, and out-of-range values with an explicit public-exposure warning. The command remains inert until T052 owns production composition.
- When an HTTP or WebSocket `Origin` header is present, it must be the single exact configured `http://127.0.0.1:<port>` origin; duplicate, malformed, foreign, HTTPS, alias, or wrong-port values fail closed. HTTP rejection uses the fixed `FORBIDDEN` envelope and status 403, while WebSocket rejection occurs before acceptance with close code 1008. A missing `Origin` remains valid for non-browser loopback clients; production CORS is absent and any downstream `Access-Control-*` response header is removed.
- Every HTTP response receives the fixed CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and closed camera/geolocation/microphone/payment/USB `Permissions-Policy`. The shared error constructor also adds them to unexpected 500 responses that are created outside user middleware. Rejected origins, bodies, and exception details are never reflected.
- Raw HTTP request bodies are capped at exactly 4 MiB (`4194304` bytes) from both `Content-Length` and actual streamed chunks; the first excess byte returns the fixed 413 `PAYLOAD_TOO_LARGE` envelope. This transport budget accommodates the existing 200,000-character AI source limit even under worst-case JSON escaping. Existing plan JSON/YAML import and field-level text limits remain stricter and authoritative; safe YAML loading is unchanged.
- Static serving accepts only one explicitly injected, existing directory whose resolved local `index.html` is a regular file. Existing files are served without following escaping symlinks. Missing extensionless GET/HEAD paths and missing navigation paths that explicitly accept `text/html` fall back to `index.html`, including symbol routes such as `/stocks/003043.SZ`; missing asset-like paths use the fixed 404 envelope even when the distribution contains `404.html`. `/api/v1` and `/ws/v1` are excluded at static-route matching time, so static content cannot shadow or change the method semantics of API or WebSocket paths. T040 performs no default build discovery and creates no SPA entry; T041 supplies `web/index.html`, and T052 owns installed production asset discovery/composition.

### T041 Frozen OpenAPI and Frontend-Type Boundary

OpenAPI snapshot SHA-256: `e0b5435bedf6a98657bb95616bebf8e05589c387049a07eb752d4b8ea48c5102`

- The side-effect-free `create_app()` is the sole OpenAPI source. Its document contains exactly the 24 approved REST paths and documents every stable public error status with `ErrorResponse`; FastAPI's default `HTTPValidationError`/`ValidationError` schemas are excluded because runtime validation already uses the bounded secret-free envelope.
- `scripts/generate_frontend_types.py` serializes `openapi.json` as sorted, indented UTF-8 with LF line endings and one final newline. It derives TypeScript component schemas, path methods, grouped parameters, request bodies, response statuses, media types, references, unions, intersections, arrays, objects, enums, and literals from that same document; API fields are never copied by hand.
- `python scripts/generate_frontend_types.py --check` is read-only and fails when either committed generated file differs byte-for-byte. Generation fails closed on unsupported or dangling schema references, parameter locations, schema types, or invalid TypeScript identifiers rather than silently weakening a contract.
- `web/index.html` is the stable Vite application document with one `#app` root and one external module entry. It contains no inline script or style that would violate the T040 CSP. Vite now performs a document-based application build that emits `dist/index.html`; T042 still owns the first application shell, router, and component mount, while T052 still owns installed asset discovery and production composition.

### T042 Accessible Vue Application Shell Boundary

- `main.ts` mounts the root `App.vue` only when `#app` exists, installs the one application router for that production root, and preserves the typed unmounted-component factory used by tooling tests. Importing the module creates no API client, store, socket, timer, or domain state.
- The router declares exactly `/`, `/stocks/:symbol`, `/plans`, `/plans/:id`, `/alerts`, and `/system`. Until their approved later tasks create real views, small local placeholder components expose only labelled route headings; they contain no domain rules, API calls, or mutable shared quote state.
- `AppShell` owns only landmarks, desktop and mobile navigation, the route outlet, a typed optional `connectionBanner` slot, and one local mobile-menu boolean. The banner wrapper is rendered only when supplied and uses polite status semantics; connection/health ownership remains outside the shell.
- The skip link moves focus to the persistent `#main-content` landmark. Navigation uses native links and a native menu button with visible focus, `aria-controls`, and `aria-expanded`; Escape restores focus to the menu button, while mobile-link navigation closes the hidden menu and moves focus to main content.
- The desktop navigation replaces the mobile disclosure at `48rem`. Shell motion is bounded to presentation-only CSS and the `prefers-reduced-motion: reduce` branch reduces animation/transition duration to `0.01ms`. T043 design tokens, API client, Pinia/store and recovery behavior, T044 stream lifecycle, later business views, T052 installed composition, T041 generated contracts, and T024 decision semantics remain unchanged.

### T043 Frontend State Foundation Boundary

- `App.vue` loads one global token sheet. Its graphite/ink surfaces, mineral text, amber watch, sea-glass live, vermilion risk, cyan information, visible focus, spacing, and numeric-font tokens are semantic inputs rather than business decisions; `AppShell` consumes those tokens without adding a domain view or color-only status.
- The same-origin API client currently owns only `GET /api/v1/dashboard`. It uses the generated `DashboardResponse` and `ErrorResponse` contracts, reads at most 4 MiB of raw response bytes before JSON parsing, rejects undeclared or sensitive fields, validates the closed camelCase domain and exact Shanghai/Gregorian microsecond relationships, and emits only fixed secret-safe client errors. It owns no reactive or shared state.
- The setup-style Pinia store normalizes frozen symbol snapshots into ordered IDs and an ID map. Components receive readonly state and computed selectors; only `applySnapshot`, `applyEvent`, and `requestSnapshotRecovery` can mutate the store. A semantic connection object always exposes a code, Chinese label, and text marker so status never depends on color alone.
- Snapshots cannot regress the active sequence. An exact next event advances the cursor and records a frozen invalidation; duplicates and older events are rejected, while malformed events, sequence gaps, server recovery requests, and exhaustion of JavaScript's safe-integer sequence space create an explicit snapshot-recovery intent without consuming the cursor.
- T043 validates the closed committed event envelope and records recovery intent only. It creates no `WebSocket`, heartbeat, reconnect timer, backoff policy, replay request, or snapshot-fetch coordinator; all stream lifecycle behavior remains T044. Generated OpenAPI/TypeScript artifacts, later business views, T052 installed composition, and T024 decision semantics remain unchanged.

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

OpenAPI is committed as a canonical snapshot and used to generate TypeScript component and path types; `--check` rejects API or generated-file drift, and frontend contracts are not hand-copied.

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

Every committed event uses one strict versioned camelCase envelope:

```json
{
  "type": "symbol.health.updated",
  "sequence": 42,
  "eventId": "00000000-0000-0000-0000-000000000001",
  "aggregateId": "003043.SZ",
  "payload": {
    "entityId": "003043.SZ",
    "symbol": "003043.SZ",
    "revision": 4,
    "status": "STALE"
  },
  "occurredAt": "2026-08-24T10:30:00+08:00",
  "schemaVersion": 1
}
```

The payload is a bounded invalidation hint containing `entityId` plus only the applicable `symbol`, `revision` in `0..2^63-1`, uppercase `status`, or lowercase SHA-256 `resultHash`; clients refetch authoritative REST state instead of treating the event as a state replacement. The injected `MonitorReadService` that owns dashboard snapshot assembly must read its state and `monitor_sequence` in the same Unit of Work so its returned `sequence` is the exact high-water mark for that snapshot. T039 enforces that transport contract and the sequenced stream; constructing the default production read-service composition remains explicitly deferred to T052 and cannot be replaced by an independently sampled sequence.

Schema version 1 closes each non-null payload field set and its identity rules: snapshot uses `entityId`, `symbol`, and `resultHash`; symbol health uses `entityId`, `symbol`, `revision`, and `status`; both require `aggregateId == entityId == symbol`. Alert creation/acknowledgement use `entityId`, `symbol`, and `revision`; both require canonical UUID `aggregateId == entityId`, creation additionally requires `eventId == aggregateId` and revision `0`, and acknowledgement requires revision `1`. Extraction uses `entityId`, `revision`, and `status`; activation uses plan-version `entityId`, `symbol`, and positive `revision` with `aggregateId == symbol`; deactivation uses `entityId`, `symbol`, and positive `revision` with all three identities equal. Position uses `entityId`, `symbol`, and `OPEN`/`CLOSED` `status`; AI-provider uses `entityId` and `revision`; system health uses `entityId` and `status`; these entity-owned types require `aggregateId == entityId`. Missing required fields and any non-applicable non-null field are rejected before persistence.

`monitor_event` is the sole append-only replay source and `monitor_sequence` is the sole global high-water domain. State mutation and its event append share one transaction. Event UUID is the idempotency identity: the same ID and semantics returns the original sequence, while different semantics fail closed. The sequence never resets when retained rows are removed. The default replay window is seven days, each page is at most 1,000 events, and the server validates the complete `(after, high_water]` range before sending any page so a later gap cannot leak an earlier partial page.

`heartbeat` and `snapshot.required` are transport control frames, not committed business events and never occupy a durable sequence. Heartbeat is 20 seconds. A missing, duplicate, non-canonical, negative, or greater-than-`2^63-1` `after` cursor is rejected. A future cursor, sequence gap, corrupt high-water mark, or expired replay window sends `snapshot.required` with the durable high-water sequence and closes normally. Publication is an in-memory wake-up only after exact committed-event verification; reconnect and process restart always replay from SQLite. The client reconnects with capped exponential backoff and jitter. Disconnected or stale data is visibly labelled and never presented as live.

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

- The production command binds exactly to `127.0.0.1`; remote/LAN mode, host aliases, port forwarding, and public exposure are out of scope.
- SPA/API/WebSocket share one origin; production CORS is disabled and unexpected HTTP/WebSocket origins are rejected.
- No login or authentication is implemented for MVP. Documentation forbids port forwarding or public exposure.
- CSP, frame denial, content-type, referrer, and permissions headers are set.
- Raw request bodies are bounded at 4 MiB, existing field/import limits remain stricter, and YAML uses safe loading.
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
