# Spec: local-web (Local Web Application)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-local-web.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Provide the single local interface for monitoring up to 10 stocks, using file-configured AI to extract pasted natural-language plans, reviewing extracted rules, activating immutable versions, inspecting live evidence/charts, maintaining manual positions, reading textual reminders, and diagnosing system health.

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
    ├── market_indexes.py
    └── health.py
web/src/
├── api/
├── assets/
├── components/{common,dashboard,symbol,market-index,plans,ai,alerts,health}/
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
- The dashboard returns its committed JavaScript-safe `sequence`, nullable UUIDv4 `runtimeGeneration`, envelope `observedAt`, connection status, the six approved counts, and at most 10 isolated symbol summaries. It does not expose a redundant dashboard-level `dataAgeSeconds`. Each summary contains one authoritative deterministic decision projection with `symbol`, `resultHash`, exact plan identity, evaluation/market timestamps, per-symbol data age, price, zone, signal, position, episode/risk state, typed evidence, and next step. The adapter never evaluates a condition, changes priority, recalculates a decision hash, or reads a second quote stream. Cross-symbol identity, contradictory risk state, mismatched position lots/T+1 availability, and inconsistent ages fail closed.
- Bar responses preserve normalized integer-fen OHLC, shares, exact yuan amount, receipt time, and aggregate formula provenance. Event responses preserve symbol, sequence, stable event ID/type, timestamp, optional signal/result hash, and bounded server-authored plain text. All JSON field names are camelCase and all enum values are `UPPER_SNAKE`.
- Runtime health exposes only stable lifecycle/resource/capability states, retry/cooldown/poll times, ordered gaps, bounded executor counts, database/WAL/checkpoint/backup facts, and delivery counters. Symbol health exposes the exact data age/completeness/freshness/gap facts. `LIVE` requires fresh, complete data with a latest timestamp; disconnected, stale, gapped, blocked, or otherwise contradictory data cannot be labelled live or actionable. No response schema has a secret, authorization detail, raw provider body, or raw storage-error field.

### T037 Plan and AI Operation Boundary

- `create_app(plan_service=..., ai_service=...)` accepts explicit `PlanOperationService` and `AIOperationService` adapters without constructing either service or starting database, provider, task, or network work. Missing services fail closed with `SERVICE_UNAVAILABLE`. The application services own atomic idempotency claims/replay, optimistic-revision checks, persistence, and audit insertion; the HTTP layer passes a validated `Idempotency-Key` plus the server-generated `requestId` as one `MutationContext`.
- T037 implements `GET /plan-versions`, `GET /plan-versions/{id}`, `GET /plan-activation-states/{symbol}`, `GET /plan-extractions/{id}`, `GET /ai-providers`, `POST /plan-drafts`, `POST /plan-imports`, `POST /plan-extractions`, `POST /plan-activations`, `POST /plan-deactivations`, `POST /ai-providers`, `PATCH /ai-providers/{id}`, `POST /ai-provider-secrets`, and `POST /ai-provider-tests`. It does not implement T038 position/alert/diagnostic resources, WebSocket publication, Origin/security headers, static serving, or any T024 decision behavior.
- Plan-version collection items are bounded lightweight summaries containing exact plan/version/symbol/hash identity, `canActivate`, status, revision, and creation time; they omit the potentially large plan document, source, and issue arrays. `GET /plan-versions/{id}` exposes the complete version with one canonical bounded `planJson` document, preserved bounded `sourceText`, review issues, and deterministic validation issues. `GET /plan-activation-states/{symbol}` exposes the backend-authoritative nullable active `planVersionId`, monotonic activation-state `revision`, and change time; the inactive state remains queryable after deactivation. Service output is revalidated and must match the requested draft/import identity and provenance. `planJson` remains the canonical `plan-domain` JSON document; surrounding API fields remain camelCase. Empty pages remain valid when `offset` is beyond `total`.
- Draft saves accept `planJson`, `sourceText`, `reviewIssues`, `expectedRevision`, and an optional `basePlanVersionId`. When the base identity is present, the application service verifies that the submitted `plan_id` and `symbol` match the immutable base and allocates the next version for that `plan_id` inside the same serialized idempotent transaction; the browser never assigns that successor and no existing version is overwritten. Imports accept `format=JSON|YAML`, an explicit target `symbol`, a safe bounded `document`, and `expectedRevision`; backend parsing must prove that the document symbol matches the command before the revision can authorize persistence. Every plan version and returned revision is bounded by JavaScript's safe-integer maximum. Activation commands cap `expectedRevision` two below that maximum and deactivation commands cap it one below, so every increment remains exact and revision exhaustion can end only in an inactive state rather than stranding an active plan; unsafe documents and an exhausted successor sequence are rejected before commit without changing the domain schema or existing rows. Activation is a distinct command over an immutable `planVersionId`; deactivation is a distinct symbol command. An unresolved assumption, warning, missing-evidence item, material omission, or activation-blocking validation issue makes `canActivate=false`, and the application service must reject activation with a conflict.
- Plan extraction and AI-provider testing accept only a bounded submission command and return `202` with a typed `QUEUED` receipt. The route awaits only the service's durable submission boundary; it neither calls a provider nor creates/runs extraction work and it never activates a plan. Extraction status is closed over `QUEUED`, `RUNNING`, `SUCCEEDED`, `INVALID_OUTPUT`, `PROVIDER_ERROR`, and `CANCELLED`; successful results retain exactly one activation-blocking `AI_EVIDENCE_REVIEW_REQUIRED` and expose only canonical draft JSON, bounded evidence/issues, deterministic validation results, sanitized usage, hashes, and timestamps. Raw model/provider bodies and authorization material have no response field.
- AI-provider create/update uses the complete non-secret configuration. `PATCH` is a revision-guarded full replacement whose body `providerId` must match the path. The API revalidates it through the concrete `AIProviderConfig` class-local sanitized validator, including HTTPS/loopback URL policy and resource limits. Secret replacement accepts the existing class-local `SecretWrite` value but responses contain only `SecretStatus`-equivalent configured/source/fixed-mask/generation metadata. Service-returned configuration must match the submitted normalized configuration; extra secret or raw-provider fields fail closed.
- Every T037 state-changing endpoint requires an `Idempotency-Key` of 1–128 allowlisted characters and an `expectedRevision`. Duplicate in-flight intent maps to 409, the same key with a different request hash maps to 422, and completed identical intent replays its canonical response. Application services must perform those checks and their audit write atomically; the routers never reconstruct repository, validation, or decision-engine behavior.
- The production Web composition loads exactly one AI transport plus its primary model and up to nine `additional_models` from `config/app.yaml`, and starts exactly one persistent plan service when the FastAPI lifespan starts. The plan service opens and migrates `data/monitor.sqlite3` by default, persists plan documents, source text, review issues, activation state, audits, events, and idempotency responses, and serves as the default backtest plan snapshot reader. Its save, query, JSON/YAML import, activation, and deactivation results therefore survive independent Web process restarts. The AI lifecycle reads only the direct shared `ai.api_key`, constructs one provider client, and reuses immutable model bindings until shutdown. `GET /ai-runtime` returns the primary provider ID, display name, base URL, model, enabled/configured flags, input/output limits, fixed revision `0`, and optional bounded `alternativeProviders` summaries with the same secret-free fields. It has no secret value or Authorization field. The generic provider mutation routes remain an injected-adapter contract, but this configuration-driven production service returns `METHOD_NOT_ALLOWED` for create, update, secret replacement, and provider test. Configuration changes require editing `config/app.yaml` and restarting Web.

### T038 Position, Alert, and Diagnostic Boundary

`currentActionable` is true only while the same immutable plan version remains active and its activation policy authorizes the current Shanghai market date. Expired, disabled, or rotated alerts remain queryable historical evidence, but expose `currentActionable=false`, no position prefill, and an explicit historical label.

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

OpenAPI snapshot SHA-256: `5dac634614a5bfa5b16c74f14ebd07fe2d350cb1c36d952d0a23a949818d936a`

- The side-effect-free `create_app()` is the sole OpenAPI source. Its document contains exactly 42 approved REST paths: 27 live paths, including read-only `GET /ai-runtime`, `GET /market-indexes/{indexCode}/bars`, and `GET /plan-activation-states/{symbol}`, plus exactly 15 backtest paths, including reference-market coverage and frozen index-series reads. It documents every stable public error status with `ErrorResponse`; FastAPI's default `HTTPValidationError`/`ValidationError` schemas are excluded because runtime validation already uses the bounded secret-free envelope.
- `scripts/generate_frontend_types.py` serializes `openapi.json` as sorted, indented UTF-8 with LF line endings and one final newline. It derives TypeScript component schemas, path methods, grouped parameters, request bodies, response statuses, media types, references, unions, intersections, arrays, objects, enums, and literals from that same document; API fields are never copied by hand.
- `python scripts/generate_frontend_types.py --check` is read-only and fails when either committed generated file differs byte-for-byte. Generation fails closed on unsupported or dangling schema references, parameter locations, schema types, or invalid TypeScript identifiers rather than silently weakening a contract.
- `web/index.html` is the stable Vite application document with one `#app` root and one external module entry. It contains no inline script or style that would violate the T040 CSP. Vite now performs a document-based application build that emits `dist/index.html`; T042 still owns the first application shell, router, and component mount, while T052 still owns installed asset discovery and production composition.

### T042 Accessible Vue Application Shell Boundary

- `main.ts` mounts the root `App.vue` only when `#app` exists, installs the one application router for that production root, and preserves the typed unmounted-component factory used by tooling tests. Importing the module creates no API client, store, socket, timer, or domain state.
- The production router declares exactly ten paths. `/`, `/stocks/:symbol`, `/plans`, `/plans/:id`, `/alerts`, `/system`, and the four `/backtests...` paths are all lazy-loaded real monitoring, workbench, diagnostic, or research views. WEBF13 fixes the exact current route set and the history of the former placeholders below. The route layer contains no domain rules or mutable shared quote state.
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
GET /market-indexes/{indexCode}/bars
GET /plan-versions
GET /plan-versions/{id}
GET /plan-activation-states/{symbol}
GET /plan-extractions/{id}
GET /ai-runtime
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
- `market.index.updated`

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

Schema version 1 closes each non-null payload field set and its identity rules: snapshot uses `entityId`, `symbol`, and `resultHash`; symbol health uses `entityId`, `symbol`, `revision`, and `status`; both require `aggregateId == entityId == symbol`. Alert creation/acknowledgement use `entityId`, `symbol`, and `revision`; both require canonical UUID `aggregateId == entityId`, creation additionally requires `eventId == aggregateId` and revision `0`, and acknowledgement requires revision `1`. Extraction uses `entityId`, `revision`, and `status`; activation uses plan-version `entityId`, `symbol`, and positive `revision` with `aggregateId == symbol`; deactivation uses `entityId`, `symbol`, and positive `revision` with all three identities equal. Position uses `entityId`, `symbol`, and `OPEN`/`CLOSED` `status`; AI-provider uses `entityId` and `revision`; system health uses `entityId` and `status`; market-index invalidation uses exactly `entityId`, positive `revision`, and `status`. These entity-owned types require `aggregateId == entityId`. Missing required fields and any non-applicable non-null field are rejected before persistence.

`monitor_event` is the sole append-only replay source and `monitor_sequence` is the sole global high-water domain. State mutation and its event append share one transaction. Event UUID is the idempotency identity: the same ID and semantics returns the original sequence, while different semantics fail closed. The sequence never resets when retained rows are removed. The default replay window is 7 days, each page is at most 1,000 events, and the server validates the complete `(after, high_water]` range before sending any page so a later gap cannot leak an earlier partial page.

`heartbeat` and `snapshot.required` are transport control frames, not committed business events and never occupy a durable sequence. Heartbeat is 20 seconds and carries the exact nullable `runtimeGeneration` paired with its current lifecycle identity. A missing, duplicate, non-canonical, negative, or greater than JavaScript's safe-integer maximum (`2^53-1`) `after` cursor is rejected with close code `1008`. A future cursor, retained-range sequence gap, expired replay window, or non-representable durable high-water sends no unsafe number; an untrustworthy `monitor_sequence` fails closed with `1011`. Publication is an in-memory wake-up only after exact committed-event verification; reconnect and process restart replay from SQLite. The client reconnects with capped exponential backoff and jitter. Disconnected or stale data is visibly labelled and never presented as live.

The T044 browser lifecycle is owned by the `AppShell` mount through one `useMonitorStream` instance; no socket, timer, or mutable quote state is global. It first obtains `GET /api/v1/dashboard` with a 20-second Abort deadline, applies that authoritative snapshot atomically, and only then opens the same-origin `ws:`/`wss:` endpoint with `after=<snapshot.sequence>`. Ordered committed events are invalidation hints and trigger a fresh authoritative snapshot; gaps, malformed frames, cursor or runtime-generation mismatch, and `snapshot.required` do the same without presenting stale data as live. Socket establishment has a 20-second deadline. Because the server emits every 20 seconds, an open connection is considered silent only after two missed heartbeat intervals (40 seconds), avoiding an equal-deadline race. A heartbeat enters `LIVE` only when its cursor and `runtimeGeneration` exactly match the applied snapshot and the authoritative dashboard status is `CONNECTED`; otherwise the banner remains `STALE`. An actual reconnect and every false-to-true transport transition obtain a fresh REST snapshot before liveness can return, even when the server clock moves backward.

Historical note: WEBF13 temporarily interpreted an exact dashboard `503 SERVICE_UNAVAILABLE` through a bounded Health fallback. That workaround and its evidence are superseded by `SPEC-live-production-chain` and ADR 0004: normal projection absence is now a typed dashboard `200` response, Vue performs no Health fallback, and only a validated snapshot may open WebSocket.

Reconnect uses an exponential base of 1, 2, 4, 8, 16, then at most 30 seconds, caps that base before applying `0.8..1.2` jitter, and never schedules a delay above 30 seconds. Explicit recovery aborts the current snapshot, closes the active socket, clears all liveness/retry deadlines, and restarts from REST. Unmount performs the same cleanup without reconnecting. The shell exposes the readonly semantic state to its typed connection-banner slot and provides a default polite status containing both a text marker and label, so color is never the sole cue. This lifecycle contains no domain rule, API-field duplication, business view, persistent browser state, T052 resource discovery, or T024 decision behavior.

### T045 AI Plan Workbench Boundary

The T045 `PlanWorkbench` composes setup-style Vue components through typed props and emits only. `AIProviderSelector` presents the read-only primary `ConfiguredAIRuntimeView` and its `alternativeProviders`: display name, model, safe base URL, input limit, enabled state, and whether a key was loaded. It has no secret input, provider create/update control, connection-test control, or browser persistence. It tells the user to edit `config/app.yaml` and restart Web.

`PlanDraftingView` and `usePlanDrafting` own the same-origin API flow. Mounting loads `GET /api/v1/ai-runtime`; submission creates one idempotency key, sends `POST /api/v1/plan-extractions`, materializes its `QUEUED` receipt, then polls `GET /api/v1/plan-extractions/{operationId}` until a closed terminal status. Only one local submission/poll is active. Unmount aborts requests and timers. “Stop waiting” stops browser polling and explicitly says that an already accepted server task may continue; it does not claim server cancellation. Errors are fixed Chinese text and never include raw provider, key, or transport details.

`SourceTextEditor` owns one local plain-text model. Its limit comes from the selected runtime configuration, uses Python-compatible Unicode code-point counting, stops at the first rejected code point, and atomically rejects an over-limit edit instead of truncating it. `ExtractionEvidence` renders only validated evidence, assumptions, warnings, omissions, validation issues, usage, and bounded status through escaped Vue text interpolation. A successful canonical draft remains review-only until the user explicitly chooses `进入结构化审核`; that handoff has no persistence or activation side effect and is discarded when the source snapshot becomes stale. No extraction response can save or activate a plan by itself. T046 retains structured editing, backend validation, persistence, diff, and activation.

### T046 Structured Plan Editing and Activation Boundary

The T046 `PlansView` composes route-local version selection, `StructuredPlanEditor`, and `ActivationDiffDialog` through generated command/view contracts only. It loads bounded lightweight version summaries and fetches only the selected and required active-version details. Nine section editors preserve unknown top-level plan content, produce a human-readable preview without evaluating conditions, and emit revision-guarded draft/import/export intents. JSON/YAML parsing, canonicalization, deterministic validation, successor-version allocation, trading rules, persistence, and transport remain backend or later-composition responsibilities. Active versions are never mutated through props; an edit emits a new-draft command bound to `basePlanVersionId`, and dirty local content survives revision conflicts, repeated selection, and paginated version removal until the user explicitly reloads or discards it.

`ExtractedPlanReview` reuses `StructuredPlanEditor` only after the explicit handoff. It maps the bounded extraction issues to `DraftReviewIssue` identities, preserves the exact submitted source text, and emits a root `PlanDraftCommand` without `basePlanVersionId` only when the user explicitly saves. Before `POST /plan-drafts`, `usePlans` obtains the target symbol's authoritative activation revision; browser parsing of the already-canonical draft is limited to the routing identity needed for that read. The backend reparses and validates the complete plan, persists review state, and returns the sole authoritative `canActivate`. Saving never creates an activation command, and a saved version remains inactive until the separate diff and confirmation flow succeeds.

Import documents and final compact draft/export documents are capped at 256 KiB UTF-8 with bounded single-pass checks and atomic rejection. Import commands carry a user-selected or backend-sourced target `symbol`; the browser does not parse the document to infer it and submits only after obtaining that symbol's authoritative activation revision. The pretty-printed local editing buffer has an independent 4 MiB safety cap so valid compact plans are not rejected only because indentation expands them. Server and imported text is rendered only as escaped content; no raw text enters `v-html`, logging, URLs, persistent browser state, or mutable shared state. A network error, invalid response, or any 5xx outcome retains the exact semantic intent and idempotency key for retry because the mutation may already have committed; a deterministic 4xx rejection is shown with fixed safe copy and clears that key.

Activation is fail-closed on unresolved material review items, activation-blocking validation items, dirty edits, busy state, missing plan state, cross-symbol identity, missing active-version content, or revision drift. The before/after dialog uses a real modal boundary with initial focus, native focus containment, Escape/cancel handling, and focus restoration. Every candidate/current hash, document, status, symbol, revision, and expected active-state revision change invalidates confirmation; a parent authoritative-state mismatch closes the dialog and cannot silently reopen it. Activation and deactivation remain separate explicit commands. The T041 artifacts are regenerated from this accepted backend contract; T047+ business views, unrelated API/store composition, T052 installed composition, and T024 decision semantics remain unchanged.

### WEBF04 Backtest Plan-Version Selection and Freeze Boundary

`/backtests/new` lists only the backend-authoritative `canActivate=true` plan-version page through `useBacktestPlanVersions` and `BacktestPlanVersionSelector`. The browser displays immutable summary identity, keeps pagination on the server, and submits only the exact user-selected `planVersionId`; it does not infer eligibility, require the version to be active, cache `planJson`, or auto-submit. The backend revalidates the selected version and persists its canonical snapshot and hash into the durable backtest job input before returning the accepted receipt. Subsequent plan saves create other immutable versions and cannot change that job, an older result, or an existing hash. Same-key replay reuses the persisted binding without reading live plan state again. This slice changes no Schema v1 document, historical result, or established hash formula, and uses the already generated OpenAPI plan-page and run-command contracts without adding a parallel API.

### T047 Multi-Stock Dashboard Boundary

Across the Web UI, every user-visible offset-aware datetime uses `YYYY-MM-DD HH:mm:ss`. This presentation rule applies to status strips, tables, timelines, chart axes, chart tooltips, and accessible chart text. It preserves the authoritative source wall-clock fields without host/browser timezone conversion. API and URL values, ordering/filtering inputs, and machine-readable `<time datetime>` attributes retain their original offset-aware ISO 8601 values; date-only values and compact intraday axes retain `YYYY-MM-DD` and `HH:mm` respectively.

The T047 `DashboardView` composes a labelled toolbar, an accessible native watchlist table, condition-count presentation, and a typed actionable-rail slot from readonly normalized `SymbolSummaryView` snapshots. It displays at most the store-enforced ten symbols with authoritative price, zone, satisfied/total condition counts, signal, position quantities, risk distance, exact market timestamp, data health, connection, and age. Search is bounded to 128 Unicode code points before display matching; filtering and sorting operate only on copied display arrays, keep nullable values last, and never mutate input snapshots.

Vue does not evaluate the condition DSL, indicators, zones, signal precedence, risk state, freshness, or server counts. A row is display-live only when it is connected, has `LIVE` health, and is fresh; every other valid health combination remains explicitly visible under the stale/degraded filter and cannot alter or hide a healthy peer. Loading and bounded escaped errors may coexist with cached rows, while an unavailable zero-row snapshot is not misreported as an empty business watchlist. Native links and labelled controls remain keyboard-accessible, and semantic text accompanies all color states. API/WebSocket/Pinia route composition, charts and evidence (`T048`), installed composition (`T052`), the T041 generated contract, and T024 decision semantics remain unchanged.

### T048 Stock-Detail Chart and Evidence Boundary

T048 composes `SymbolDetailView`, `PriceChart`, `EpisodeTimeline`, and `useChartSeries` strictly from readonly `SymbolDetailResponse`, `BarView`, and `SymbolEventView` inputs. The composable copies and orders backend OHLC, flattens the authoritative evidence hierarchy, maps only allowlisted server-authored price/indicator facts, retains alerts even when no chart coordinate exists, and publishes one shallow immutable series. It does not evaluate indicators, conditions, zones, signal precedence, risk, freshness, or any trading rule.

Indicator points use only sibling `DATE` or `DATETIME` evidence facts in the same evidence node. A `DATE` may anchor only to the last bar on that exact date; a missing date, source timestamp, or same-day bar leaves `time` and/or `plotTime` unavailable, while a non-finite or underflowing chart number prevents drawing without dropping the table fact. Exact backend Decimal text remains unchanged in the accessible alternative and is never replaced by rounded ECharts display data. `episodeLowFen` remains a horizontal value with unknown occurrence time because the public contract supplies no low timestamp. Vue text interpolation keeps event/error/evidence text inert, stale or degraded state retains visible facts with an explicit warning, and `PriceChart` alone owns ECharts initialization, resize handling, zoom emits, disposal, and non-HTML tooltips. API/store/router composition, manual position commands (`T049`), later business views, installed composition (`T052`), generated contracts, and T024 decision semantics remain unchanged.

### T050 Textual Alert Center Boundary

`AlertsView` owns only route-local query intent, authoritative page replacement, bounded live-invalidation deduplication, and one injected idempotent acknowledgement operation. `AlertTable` owns labelled filters, native pagination, safe server-authored text, complete matched/satisfied/unmet/blocker evidence expansion, event identity, chart-time links, and the explicit acknowledgement-not-fill wording. `AlertRail` reports synchronization state without copying alert entities or treating a WebSocket invalidation as reminder content.

Every successful list result must echo the requested pagination and filters, contain unique event IDs and sequences, and contain only rows matching symbol, signal, acknowledgement, and inclusive creation-time filters. A committed `alert.created` or `alert.acknowledged` invalidation is marked synchronized only after a newer authoritative page succeeds; failures remain retryable, and both pending and remembered identities are bounded. Stale list generations cannot replace newer query or acknowledgement state.

Acknowledgement reserves bounded capacity before transport, sends exactly one revision-bound idempotent command, never inserts its receipt into the displayed page, and always reconciles through an authoritative read. Valid, invalid, conflict, and uncertain outcomes retain fixed secret-safe messages until any later authoritative page proves acknowledged, unacknowledged, or still unknown. A persistent polite status and focus fallback survive filtered-row removal. No acknowledgement invokes a position operation or changes displayed position facts. API-client/store/router production composition, system health (`T051`), installed assets (`T052`), generated contracts, and T024 decision semantics remain unchanged.

### T051 System Health and Accessibility Boundary

`SystemView` is a thin readonly composition surface over an optional generated `RuntimeHealthResponse`. It distinguishes loading, unavailable, failed, and cached-safe states without rendering raw transport/provider errors, and emits only explicit refresh or symbol-selection intent. `MarketStatusStrip` presents backend-authored lifecycle, observation, completed-minute/evaluation timestamps with paired ages, polling, retry, and cooldown facts. `HealthMatrix` presents provider capabilities/latency, bounded gaps, executor utilization, database/WAL/checkpoint/backup, and delivery state. Every provider/resource state has its own text, shape, and `data-status`; stable diagnostic codes are allowlisted for display and every other value is masked.

The slice performs no API call, Pinia write, router composition, provider/rule evaluation, freshness calculation, or secret handling. Native controls, labelled tables and scroll regions, persistent visible focus, polite status, reduced motion, and layouts at 320/768/1024/1440 pixels are verified in unit tests plus a real Chromium/axe WCAG 2.1 A/AA gate. Installed asset discovery remains T052; the full browser journey remains T055; generated contracts and T024 decision semantics remain unchanged.

### T052 Installed Production Startup and Asset Boundary

- The installed `trade-plan-monitor` console entry resolves to `trade_plan_monitor.cli:console_main`. CLI import and parser construction remain side-effect-free; the `web` branch lazily creates one production application context and imports/runs Uvicorn only after exact loopback host and bounded port parsing succeeds.
- Vite keeps `web/index.html` as its document input and continues to emit `web/dist/index.html`. A build-only plugin replaces the ignored `src/trade_plan_monitor/web/dist` staging directory with that same completed distribution; setuptools packages only its `index.html` and local `assets/*`. Neither generated directory is tracked.
- Production discovery uses `importlib.resources` against `trade_plan_monitor.web/dist` for the whole server lifetime. It never searches the current working directory, a repository root, `web/dist`, or another source-tree fallback. A missing directory, `index.html`, `assets/`, or concrete asset fails before Uvicorn with only `WEB_ASSETS_UNAVAILABLE` and the fixed text `Installed Web assets are unavailable.`; paths, resource exceptions, context, and causes are not exposed.
- `create_production_app(...)` composes the discovered distribution through the existing `create_app(...)`, so the frozen 42 REST paths (27 live plus 15 backtest paths), `/ws/v1/monitor`, Origin/body/security-header policy, and SPA exclusion/fallback semantics remain governed by one application. The asset context remains open until the server runner exits, then FastAPI lifespan performs its owned shutdown and extracted resources are released.
- T052 owns packaged startup, asset lifetime, the configuration-driven AI lifecycle, and the persistent plan lifecycle. Startup order is monitoring runtime, AI, plan, then backtest; shutdown is the exact reverse. The monitoring-runtime wiring is defined by WEBF05 below; T052 does not create or substitute a generic `_ReadOnlyPackagedLifecycle`. Unless an explicit plan service is injected, plan startup opens and migrates `data/monitor.sqlite3`, rejects an existing backtest/market database before plan DDL, injects the same service into all plan routes, and supplies that same instance to the default backtest composition. Plan shutdown disposes the owned engine only after backtest shutdown. AI startup loads `config/app.yaml` once and uses only its direct `ai.api_key`. Invalid YAML fails startup; a missing or empty credential starts with `configured=false`, so the page cannot submit extraction. Explicitly injected test/application services remain authoritative. No CDN, remote runtime asset, alternate listener, or development-directory fallback is added.

### WEBF05 Real Production Monitoring Composition Boundary

- `create_production_app(...)` uses a lazy `create_monitor_composition_factory(config_path, database_path)` when no explicit runtime/application services are supplied. The factory is invoked only inside FastAPI lifespan; it opens and migrates the same monitor SQLite used by the production plan lifecycle, constructs the real `RuntimeLifecycleService`, exposes its backend-authoritative `RuntimeHealthSnapshot`, and owns the database-backed `CommittedMonitorEventStream`. Explicitly injected runtime and application services remain authoritative and suppress the default composition.
- The default composition loads and validates the unified ignored `config/app.yaml`, then checks the approved live evidence before constructing a credentialed provider client or making a provider request. A fresh profile is necessary but does not itself make production actionable: the composition must validate and consume it, bind the corresponding provider and scheduler, and preserve every per-index failure. Until those checks pass, it reports `DEGRADED` with `readOnly=true` and `nextPollAt=null`, and creates no scheduler run task. The current stock profile is fully `READY` with `SourceTimeLabel=END`; the independently renewed index profile has the four visible indexes plus hidden turnover benchmark `399107.SZ` fully `READY` with `SourceTimeLabel=END`. The known `899050.BJ` identity is `DEFERRED` and cannot reach request control. This is an honest runtime-health result, not a synthetic successful snapshot or a generic placeholder; failures remain visible through the backend health contract.
- A real composition does not invent missing authoritative projections. ADR 0004 supersedes the former generic `SERVICE_UNAVAILABLE` behavior for dashboard and symbol lifecycle absence with the strict typed HTTP `200` unavailable union; genuine failures and any still-uncomposed live-index read remain fail-closed. The WebSocket event stream is backed by committed database events rather than fabricated rows. Position availability is defined separately by WEBF09 and alert-center availability by WEBF10. No Vue-side rule, freshness, eligibility, or health decision may upgrade these responses.
- This boundary changes no Schema v1 data, historical backtest result, established hash, OpenAPI path, generated TypeScript contract, or T024 decision semantics. Invalid configuration, storage, composition, expired-profile, or required-index errors are not silently converted into a healthy response; an unmet live prerequisite produces the bounded `DEGRADED` state or an isolated dependent-path failure according to the production-chain contract.

### WEBF06 Monitoring Overview Route Boundary

- `/` lazily loads `DashboardRouteView`, a thin composition surface over the existing `monitor` Pinia store and `DashboardView`. The store is populated only by the authoritative `GET /api/v1/dashboard` snapshot lifecycle; the route never calls a provider, evaluates a condition, maps a board, calculates freshness, or writes a decision.
- The route passes the immutable backend `connectionStatus`, counts, symbol summaries, shared `marketIndexes`, nullable backend-calculated `marketTurnover`, and each symbol's plan-specific `referenceMarket.conditionProgress` directly to presentation components. Envelope `observedAt` remains the trend-query boundary but is not presentation copy. The app shell is the sole global real-time transport-status presentation, so the overview renders no duplicate standalone connection strip; it still passes `connectionStatus` to index components for local live/cached/blocked health. Index health uses text, symbol, state color, and a one-shot new-snapshot pulse with reduced-motion support. The UI therefore keeps shared board-index facts separate from per-plan outcomes and does not imply a universal market conclusion. Turnover uses `000001.SH + 399107.SZ`, while its linear full-day estimate is explicitly labelled and never enters a plan decision.
- The route preserves a backend-certified official-close `RISK_BREACH` together with its truthful `STALE` decision health. Only the backend may admit this narrow actionable exception after validating the matching 15:00 official bar, breach date, complete required data, risk state, next step, and satisfied `OFFICIAL_CLOSE_BELOW_LEVEL` evidence. Vue neither suppresses the signal nor relabels it `LIVE`; every other actionable decision remains invalid unless its health is `LIVE`.
- Until an authoritative snapshot exists, the route presents the existing loading state rather than an empty watchlist. Selecting a rendered stock emits only a router navigation intent to `/stocks/:symbol`; it performs no monitoring mutation and does not synthesize a detail response.
- This boundary adds no REST path, schema migration, Schema v1 data change, historical backtest result change, or decision hash change. It adds only the nullable, backward-compatible `marketTurnover` OpenAPI field and corresponding generated TypeScript type. It does not reveal tokens or perform a real supplier request.

### WEBF09 Stock Position-Lot Production Boundary

- The default monitor composition injects one `PersistentPositionOperationService` over the same SQLite unit-of-work factory as the runtime. It implements the existing T038 `GET /api/v1/position-lots`, `POST /api/v1/position-lots`, and `POST /api/v1/position-lot-closures` contracts; no REST path, field, OpenAPI snapshot, or generated TypeScript contract changes.
- The backend is the sole authority for position policy. Reads return a bounded, stable page of open and exhausted lots and derive `sellableQuantity` only from the stored exchange calendar. A known closed session authoritatively projects zero sellable quantity and rejects reductions, while a missing calendar row fails with `SERVICE_UNAVAILABLE` instead of fabricating zero. Creation resolves the symbol's active immutable plan and enforces its lot size and maximum quantity. Reduction enforces the stored open trading day, T+1, remaining quantity, board lot, and optimistic revision. Idempotency claim/completion, lot mutation, audit log, and committed event are one transaction.
- `/stocks/:symbol` loads the authoritative lot page for the backend detail snapshot's exact observed trade date through a strict generated-type adapter. Vue owns only input-shape checks, explicit confirmation, request/revision binding, stale-generation protection, safe error text, focus restoration, and receipt-to-page reconciliation. A mutation-owned refresh invalidates an older pending route read. An uncertain retry of the same semantic command retains its idempotency key until authoritative reconciliation or a deterministic rejection; editing the command creates a new intent. Vue never decides maximum-position, remaining-quantity, sellability, trading-calendar, or T+1 eligibility; even a displayed `sellableQuantity=0` or a page at the plan maximum does not suppress submission to the backend.
- This slice performs no token read or supplier request and changes no Schema v1 row, migration, historical backtest result, established hash, decision priority, or alert acknowledgement behavior. Missing or inconsistent plans/calendars fail closed through the backend error boundary.

### WEBF10 Alert-Center Production Boundary

- The default monitor composition injects one `PersistentAlertOperationService` over the same SQLite unit-of-work factory as the runtime. It implements the existing T038 `GET /api/v1/alerts` and `POST /api/v1/alert-acknowledgements` contracts. The diagnostic operation remains explicitly unavailable until its own production authority exists; connecting alert reads cannot silently enable evaluation work.
- `GET /api/v1/alerts` returns a stable bounded page in committed alert-sequence order and applies only the optional symbol, actionable signal type, acknowledgement state, and paired inclusive Shanghai-time filters. Persistence rows are reconstructed as complete canonical `AlertEvent` values before projection. The service derives only identity-matched non-submitting position prefills for signals that already carry a backend-authored buy or closure intent; it never queries or mutates position lots.
- Acknowledgement locks and revalidates the durable revision, advances only `0` to `1`, and accepts revision `1` only as the already-acknowledged no-op. The idempotency claim/completion, acknowledgement timestamp, alert audit, and committed `alert.acknowledged` event share one transaction. A stale revision conflicts, a missing alert is not found, and identical completed intent replays its canonical result without another acknowledgement event.
- `/alerts` is a real lazy route. `AlertsRouteView` performs the initial authoritative read, injects the strict alert API operations, and forwards only the latest validated monitor event as an invalidation hint. `AlertsView` continues to replace content only from a validated authoritative page; the strict adapter verifies filter echoes, membership, identities, timestamps, revisions, evidence budgets, and signal/severity/next-step/prefill relationships. Server message text is rendered as escaped text, and acknowledgement always performs an authoritative reread. No alert path submits a fill or calls a position endpoint.
- This slice adds no REST path or field, so the 42-path OpenAPI snapshot and generated TypeScript contract remain byte-for-byte consistent after regeneration checks. It changes no Schema v1 data or migration, historical backtest result, established hash, decision rule, or supplier boundary, and it reads no token or performs any supplier request.

### WEBF11 Cursor-Resumable Monitor Stream Boundary

- WEBF11 reuses the existing T039 committed monitor-event ledger, T043 transport contract, and T044 `useMonitorStream` lifecycle; it does not create a parallel event log, cursor, snapshot assembler, or browser state authority. The server remains the sole business authority and the existing SQLite `monitor_event`/`monitor_sequence` pair remains the replay source and global high-water domain.
- Initial start, actual reconnect, false-to-true transport transition, and explicit recovery obtain a backend-authoritative dashboard snapshot and atomically apply it before opening `/ws/v1/monitor?after=<snapshot.sequence>`. SQLite replay remains the source. An event sequence gap, heartbeat cursor/runtime-generation mismatch, malformed frame, or `snapshot.required` aborts the current stream and repeats that REST snapshot flow; server-side future/expired/range-gap detection is reported through `snapshot.required`. Invalid `after` is rejected with close code `1008`, while an untrustworthy or JavaScript-unsafe durable high-water mark fails closed with `1011`; neither is treated as browser-recoverable data. Every resumed socket uses the applied authoritative safe `sequence`, never a browser-invented cursor. The server validates the complete replay range before sending a page, so a partial page cannot mask a later gap.
- Liveness is strict: only a heartbeat whose cursor and `runtimeGeneration` exactly match the applied authoritative snapshot, and whose authoritative dashboard status is `CONNECTED`, may reset the liveness deadline and enter `LIVE`. Duplicate, stale, out-of-order, malformed, generation-mismatched, or cursor-mismatched frames do not reset liveness and cannot conceal a two-interval timeout; disconnected or stale data remains visibly labelled.
- The additive `0008_market_index_monitor_event` migration follows the existing monitor-event migration chain. It prechecks `event_type`, copies all seven existing columns, and verifies row count before replacing the original with the approved `market.index.updated` CHECK value. If any existing index event row is present, downgrade is refused before DDL; all existing rows, global sequences, and event identities remain unchanged, and frozen `0006_monitor_event` is never rewritten.
- WEBF11 added no REST path or field: its OpenAPI snapshot remained exactly 42 paths and generated TypeScript was unchanged at that historical boundary. ADR 0004 later added typed monitoring-response unions without adding a path; missing authoritative dashboard projections now return that typed HTTP `200` response. WEBF11 never fabricates a snapshot. Schema v1 data, historical backtest results, established hashes, decision rules, token handling, and supplier-request boundaries remain unchanged. Strategy-event-cursor resume during backtest replay remains separately deferred.

### WEBF12 Shared Index and Current-Plan Presentation Boundary

- The dashboard presents the backend-authoritative shared index snapshot once in the “参考板块指数：共用数据” strip, while each watchlist row presents only that symbol's current-plan `conditionProgress`. Multiple plans may therefore share the same index facts without merging or implying their outcomes.
- The symbol route reuses the detail response's backend `referenceMarket` identity to query the existing market-index bars endpoint for the selected stock-history range with `interval=FIVE_MINUTE`. Vue owns only request lifecycle, cancellation, and stale-generation protection; it does not map symbols, join facts, calculate indicators, or derive a condition outcome.
- Symbol detail keeps shared reference facts and history in a “参考指数数据” section, and current-plan identity, condition progress, and exact `indexConditionEvidence.planPath` outcomes in a separate “计划指数条件” section. Plan identity, snapshot/cutoff, health, loading, failure, and cached context remain visible; a plan with no index conditions remains explicitly “计划未使用”. Stock and index histories remain separate and each history has an accessible textual table alternative.
- Strict transport validation rejects malformed reference/evidence identity, ordering, and progress data before rendering. WEBF12 changes no REST path or field, OpenAPI snapshot, generated TypeScript, Schema v1 data, historical backtest result, or established hash; it reads no token and performs no real DeepSeek, Tushare, or other provider request.

### WEBF13 Real Production Routes and New-Backtest Journey Boundary

- The former placeholder routes `/`, `/stocks/:symbol`, `/plans/:id`, `/alerts`, and `/system` now each resolve to a real lazy SFC route view. Together with the existing `/plans` route and the four ordered backtest routes (`/backtests`, `/backtests/new`, `/backtests/data`, and `/backtests/:runId`), the production router has exactly 10 routes. The static backtest children remain before the dynamic `:runId` route.
- The browser journey for one new backtest is exact: choose the backend-listed immutable plan version and verified dataset, submit one explicit idempotent command, navigate to `/backtests/:runId?jobId=<jobId>`, poll the matching durable job, remove `jobId` with canonical replacement only after `COMPLETED`, and then read the materialized result. A failed or cancelled job retains its job identity for diagnostics and does not fabricate a result.
- The backend remains the sole authority for plan eligibility and snapshots, dataset coverage, run identity, job state, completion, and materialized result availability. Vue owns only generated-contract validation, bounded request/retry lifecycle, URL navigation, display, and accessibility; it does not infer eligibility, progress completion, or result content.
- Historical WEBF13 availability-banner evidence used a temporary Health fallback. `SPEC-live-production-chain` and ADR 0004 supersede it with backend-owned typed projection availability; WEBF13 does not claim current availability acceptance.
- WEBF13 changes no REST path, OpenAPI field, generated TypeScript type, schema, hash, provider boundary, token handling, or historical result. Its verification report records only evidence actually run; it does not rewrite historical acceptance artifacts.

### Approved Backtest Extension Boundary

The six-module backtest direction and this boundary were approved on 2026-08-26. The user also confirmed [`backtest-api`](../backtesting/SPEC-backtest-api.md) and approved [`backtest-web`](../backtesting/SPEC-backtest-web.md). On 2026-08-26, the user confirmed the corrected `planVersionId`, money projection, result/job consistency, versioned-compatibility, and unified China-time clauses. The following values govern the current generated contract and the separately gated remaining router work:

- the current frozen contract is exactly 42 REST paths: 27 live paths, including read-only AI runtime configuration, board-index history, and authoritative plan activation state, plus exactly 15 backtest resource paths, with the OpenAPI snapshot, hash, generated TypeScript, and runtime guards updated together;
- the production router has exactly ten paths, all connected to real or lazy-loaded views; the two static backtest child routes remain before the dynamic route;
- WEBF10 connects the final historical `/alerts` placeholder to its business view without adding a route;
- all 15 backtest paths, four routes, generated types, runtime guards, URL datetime/date filters, and machine-readable Web values inherit the accepted canonical `Asia/Shanghai` contract: datetime input uses `+08:00` with 0–6 fractional-second digits, date input uses canonical `YYYY-MM-DD`, output/storage remains fixed-six-digit where datetime applies, and `Z`, offsetless, overprecision, other-offset, or invalid calendar values are rejected;
- the first release uses bounded REST polling for durable jobs and adds no backtest WebSocket event;
- `create_production_app(...)` uses the WEBF05 lazy real monitoring composition: when live prerequisites are missing, expired, invalid, or not yet consumed by the installed composition, backend health is honestly `DEGRADED`/read-only and dashboard/symbol reads without authoritative projections return ADR 0004's typed unavailable response. A failed index cannot be upgraded from the readiness of other indexes and affects only its dependent paths. Genuine composition/storage faults remain `SERVICE_UNAVAILABLE`. Its default persistent plan service is available for plan save/query/import/activation/deactivation and backtest plan snapshots. Registering any other router protocol alone is not a usable product composition.

## Information Architecture

### `/` — Monitoring Overview

- One app-shell real-time transport status, with no duplicate overview connection strip; per-symbol connection and age remain available where diagnostically relevant.
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
- Expired or rotated reminders remain visible as historical evidence and are explicitly marked as currently non-actionable.
- Acknowledgement language explicitly states that it is not a fill.

### `/system` — System Health

- Tushare capabilities, latency, cooldown, next poll, gaps, executor, database/WAL, backup, and delivery health.
- AI configuration is not edited on this page. The `/plans` view shows the safe read-only runtime summary; project files remain authoritative.

### `/backtests`, `/backtests/new`, `/backtests/data`, and `/backtests/:runId` — Backtest Research

- Browse bounded completed-run summaries and open one immutable result.
- Select one reviewed plan version, one symbol, one frozen dataset, explicit cash/lot inputs, and execution assumptions before submission.
- Inspect historical coverage, submit authorized synchronization or offline verification, and follow one durable job without blocking an HTTP request.
- Review exact metrics, assumptions, daily equity with a full table alternative, paginated fills/details, exports, pin state, progress, cancellation, expiration, and failure states.
- Keep historical research separate from live monitoring, alerts, notification delivery, broker operations, and `T058` evidence.

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
| `PositionLots` | Local lot forms, T+1 display, and explicit confirmation | authoritative page/prefill/operation gateway | confirmed add/close command |
| `PlanWorkbench` | Orchestrate extraction and evidence review | draft/extraction | extraction/review intents |
| `SourceTextEditor` | Plain-text plan input | source text | update text |
| `AIProviderSelector` | Show/select file-configured provider | safe runtime summary | select |
| `ExtractionEvidence` | Evidence, uncertainty, omissions | extraction result | resolve issue |
| `ExtractedPlanReview` | Explicitly bridge an AI result into structured review | extraction/source/resolved issues | root draft save intent |
| `StructuredPlanEditor` | Sectioned typed draft editing | plan draft/issues | update draft |
| `ActivationDiffDialog` | Confirm immutable version switch | before/after/issues | confirm/cancel |
| `HealthMatrix` | Provider/symbol health | health rows | select symbol |

The `monitor` Pinia store owns normalized snapshot/event state with readonly views and explicit `applySnapshot`, `applyEvent`, and recovery actions. Route-local plan and position forms remain local. `useMonitorStream`, `useSymbolFilters`, `useChartSeries`, and `usePositions` contain lifecycle or derived logic. ECharts instances and large immutable series use shallow refs. Components use typed props/emits and never mutate shared records directly.

`SymbolDetailView` is only the composition surface for T049. `PositionLots` owns native labelled controls, reminder-owned prefill fields, confirmation-dialog state, and focus restoration. `usePositions` accepts maybe-reactive symbol/date/page/limit/prefill inputs plus an injected plain-function operation gateway; it exposes shallow-readonly authoritative state and explicit mutation methods. A reminder may prefill a form but cannot submit, acknowledgement cannot create or reduce a lot, and each new semantic command is bound to the reviewed lot revision and a new idempotency key. An uncertain identical retry reuses that key until authoritative reconciliation or deterministic rejection. Creation/closure receipts and the subsequent authoritative page must agree before success is reported. Conflict refreshes use the original mutation context, generation guards prevent older responses from replacing newer pages, and incomplete pagination cannot be used to infer any position-policy limit. The browser may enforce only input shape, positive 100-share quantities, confirmation, and response identity; it never blocks a command based on maximum position, remaining quantity, backend `sellableQuantity`, the trading calendar, or T+1 eligibility. T050 alert views, installed-asset discovery, and T024 decision behavior remain outside this boundary; WEBF09 supplies the production API/router composition.

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
- Playwright end-to-end flows: start with a fake provider in project test configuration, paste a plan, extract, explicitly enter structured review, resolve a warning, save, separately confirm backend-approved activation, replay market data, receive one alert, acknowledge it, and verify no position change.
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
- Web uses the AI provider loaded from project configuration, shows no editing control, and never receives the secret value or its file/key reference.
- The plan cannot activate while material omissions or validation errors remain.
- One deterministic buy event appears as one textual reminder with evidence and disclaimer.
- UI meets keyboard, contrast, responsive, reduced-motion, and non-color-only requirements.
- No normal startup path listens beyond loopback.

## Open Questions

None blocking. OS-level browser notifications and named chat platforms remain future opt-in channels.

## Review Status

WEBF11 was authorized for implementation and offline verification in this session. It reuses T039/T043/T044 cursor recovery and adds only the safe `0008_market_index_monitor_event` migration boundary; it does not claim backtest strategy-event-cursor resume. WEBF12 was authorized for implementation and offline verification in this session; it completes the dashboard/detail shared-index and current-plan presentation boundary without changing the REST/OpenAPI/generated-TypeScript contract. WEBF13 records the current real-route and new-backtest journey boundary without changing the frozen contract; its paired offline acceptance evidence passed on 2026-09-04.

The base `local-web` specification and completed `T035`–`T056` implementation history remain previously approved. On 2026-08-26, the user approved the `Backtest Extension Boundary` and `backtest-web`, confirmed `backtest-api`, and then confirmed the unified `Asia/Shanghai`/`+08:00` time contract plus the remaining API/engine/results/jobs consistency corrections. The aggregate detailed-specification gate is closed. Section 15 of the bilingual implementation plan and the generated `BT009`–`BT050` task list were separately approved. The board-index extension was approved and authorized for offline implementation on 2026-09-02. WEBF06 connects the root monitoring overview to the backend-authoritative dashboard snapshot and shared index projection; the later turnover extension adds only its nullable `marketTurnover` field. WEBF09 composes the existing position API and the real stock-detail route while keeping every T+1 and position-policy decision in the backend. WEBF10 composes the existing alert API and the real `/alerts` route while keeping filter membership, canonical reminders, and acknowledgement revisions in the backend. The current OpenAPI contract contains exactly 42 paths, including 27 live paths and 15 backtest paths; the production router contains exactly ten paths and all are connected to real views. Commit, push, dependency installation, and network access remain separately authorized actions.
