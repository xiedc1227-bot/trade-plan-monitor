# Spec: local-web

## Current scope

The installed `trade-plan-monitor web` command binds to `127.0.0.1` and serves matching monitor-contract `2` assets, REST and WebSocket. [One Trade Plan Workflow](SPEC-unified-plan.md) owns Schema 5 extraction, review, activation and isolated whole-trade simulation. The API reads immutable startup AI configuration; there are no secret/configuration write or connection-test routes, real-fill registration routes, manual fundamental/event-risk write routes or separate daily-plan workspace.

## Routes and authority

`/`, `/stocks/:symbol`, `/plans`, `/plans/:id`, `/alerts` and `/system` provide monitoring, source review, reminders and diagnostics. `/backtests`, `/backtests/new`, `/backtests/data` and `/backtests/:runId` provide independent historical research. Vue renders generated backend contracts; it never calculates eligibility or mutates inventory from a reminder. Frozen plan versions remain readable research/audit inputs and cannot activate as current plans.

Normal missing projections are typed HTTP `200` unavailable responses; real storage/composition faults retain sanitized errors. Runtime progress, data eligibility and transport liveness are distinct. Monitor-version guards, per-plan scoped read-only status, completion-proof freshness, mismatch/reload behavior and strict v2 heartbeat parsing are governed by [runtime-status](SPEC-runtime-status.md). The current guard inventory is listed there; removed legacy command paths must not be restored.

State-changing services retain idempotency, optimistic revisions and exact source/review/activation binding. API configuration is read-only and loaded once from `config/app.yaml`; secrets are never included in responses, frontend state, exports, logs or errors. Explicit simulated trades revalidate quantity, T+1, CORE, capacity, quote and revision under the current symbol transaction. Research worker/provider work is never performed in a request handler.

## Generated contracts and builds

`openapi.json` and `web/src/api/generated.ts` are generated from `create_app` compatibility assembly. `openapi.runtime-status.json` and `web/src/api/generated-runtime-status.ts` describe the installed v2 assembly. Do not hand-copy or hand-edit generated schemas; current approved fingerprints are in `SPEC-unified-plan.md`, and path inventory is authoritative in the machine contracts.

```powershell
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

The normal build copies matching assets and `monitor-contract.json` to the Python package. `build:runtime-status-preview` remains isolated; `build:legacy-test` is for explicit compatibility fixtures. Manifest/protocol mismatch fails assembly. Ship matching backend/frontend versions together, as described in the [operations guide](../../operations/live-certification.md).

## Application and error boundary

- `create_app(...)` constructs only the FastAPI adapter. Import and construction do not load configuration, open SQLite, call providers, create tasks, or bind a network socket; no module-level application instance starts hidden work.
- One explicitly injected runtime factory is invoked only when the FastAPI lifespan starts. The lifespan owns exactly one runtime instance, awaits `start()`, accepts a valid `DEGRADED` read-only startup, makes the active instance available through dependency injection, and always awaits `stop()` before clearing it. Starting without a factory fails closed.
- Every request receives a newly generated 32-character lowercase-hex request ID. Caller-supplied IDs are ignored; the same validated value appears in the `X-Request-ID` header and the error body's `requestId`.
- `ApiError`, request-validation errors, HTTP errors, and unexpected exceptions map to the single `ErrorResponse` envelope. Public outer messages are selected from fixed error codes. Validation details are capped at 100 entries; each location is capped at 16 bounded parts, and only a sanitized code plus `Field required` or `Invalid value` is exposed. Rejected input, Pydantic context, exception cause, secret values, and raw provider/storage bodies are never serialized.
- Shared error schemas are strict, frozen, camelCase-compatible, and revalidate `model_copy(update=...)`.

## Origin, transport limits and static assets

- `create_app(bind_host="127.0.0.1", bind_port=8765, static_directory=...)` validates the listener identity without binding a socket. The only accepted host literal is `127.0.0.1`, ports are limited to `1..65535`, and the installed `web` CLI rejects wildcard, LAN, alias, and out-of-range values with an explicit public-exposure warning. The installed command uses production composition.
- When an HTTP or WebSocket `Origin` header is present, it must be the single exact configured `http://127.0.0.1:<port>` origin; duplicate, malformed, foreign, HTTPS, alias, or wrong-port values fail closed. HTTP rejection uses the fixed `FORBIDDEN` envelope and status 403, while WebSocket rejection occurs before acceptance with close code 1008. A missing `Origin` remains valid for non-browser loopback clients; production CORS is absent and any downstream `Access-Control-*` response header is removed.
- Every HTTP response receives the fixed CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and closed camera/geolocation/microphone/payment/USB `Permissions-Policy`. The shared error constructor also adds them to unexpected 500 responses that are created outside user middleware. Rejected origins, bodies, and exception details are never reflected.
- Raw HTTP request bodies are capped at exactly 4 MiB (`4194304` bytes) from both `Content-Length` and actual streamed chunks; the first excess byte returns the fixed 413 `PAYLOAD_TOO_LARGE` envelope. This transport budget accommodates the existing 200,000-character AI source limit even under worst-case JSON escaping. Existing plan JSON/YAML import and field-level text limits remain stricter and authoritative; safe YAML loading is unchanged.
- Static serving accepts only one explicitly injected, existing directory whose resolved local `index.html` is a regular file. Existing files are served without following escaping symlinks. Missing extensionless GET/HEAD paths and missing navigation paths that explicitly accept `text/html` fall back to `index.html`, including symbol routes such as `/stocks/003043.SZ`; missing asset-like paths use the fixed 404 envelope even when the distribution contains `404.html`. `/api/v1` and `/ws/v1` are excluded at static-route matching time, so static content cannot shadow or change the method semantics of API or WebSocket paths. Installed asset composition is owned by `create_production_app`; static serving itself performs no build discovery.

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

The payload is a bounded invalidation hint containing `entityId` plus only the applicable `symbol`, `revision` in `0..2^63-1`, uppercase `status`, or lowercase SHA-256 `resultHash`; clients refetch authoritative REST state instead of treating the event as a state replacement. The injected `MonitorReadService` that owns dashboard snapshot assembly must read its state and `monitor_sequence` in the same Unit of Work so its returned `sequence` is the exact high-water mark for that snapshot.

Schema version 1 closes each non-null payload field set and its identity rules: snapshot uses `entityId`, `symbol`, and `resultHash`; symbol health uses `entityId`, `symbol`, `revision`, and `status`; both require `aggregateId == entityId == symbol`. Alert creation/acknowledgement use `entityId`, `symbol`, and `revision`; both require canonical UUID `aggregateId == entityId`, creation additionally requires `eventId == aggregateId` and revision `0`, and acknowledgement requires revision `1`. Extraction uses `entityId`, `revision`, and `status`; activation uses plan-version `entityId`, `symbol`, and positive `revision` with `aggregateId == symbol`; deactivation uses `entityId`, `symbol`, and positive `revision` with all three identities equal. Position uses `entityId`, `symbol`, and `OPEN`/`CLOSED` `status`; AI-provider uses `entityId` and `revision`; system health uses `entityId` and `status`; market-index invalidation uses exactly `entityId`, positive `revision`, and `status`. These entity-owned types require `aggregateId == entityId`. Missing required fields and any non-applicable non-null field are rejected before persistence.

`monitor_event` is the sole append-only replay source and `monitor_sequence` is the sole global high-water domain. State mutation and its event append share one transaction. Event UUID is the idempotency identity: the same ID and semantics returns the original sequence, while different semantics fail closed. The sequence never resets when retained rows are removed. The default replay window is 7 days, each page is at most 1,000 events, and the server validates the complete `(after, high_water]` range before sending any page so a later gap cannot leak an earlier partial page.

`heartbeat` and `snapshot.required` are transport control frames, not committed business events and never occupy a durable sequence. Heartbeat is 20 seconds and carries the exact nullable `runtimeGeneration` paired with its current lifecycle identity. A missing, duplicate, non-canonical, negative, or greater than JavaScript's safe-integer maximum (`2^53-1`) `after` cursor is rejected with close code `1008`. A future cursor, retained-range sequence gap, expired replay window, or non-representable durable high-water sends no unsafe number; an untrustworthy `monitor_sequence` fails closed with `1011`. Publication is an in-memory wake-up only after exact committed-event verification; reconnect and process restart replay from SQLite. The client reconnects with capped exponential backoff and jitter. Disconnected or stale data is visibly labelled and never presented as live.

## Browser lifecycle and acceptance

Load and atomically apply one authoritative REST dashboard snapshot before opening its sequence-bound socket. Monitor contract `2` owns the exact heartbeat/status shape: a heartbeat proves transport only, never coordinator progress or a current decision. Malformed frames, sequence gaps, generation replacement and `snapshot.required` restart from REST. Unmount/recovery cancels owned reads, sockets and timers; stale responses cannot overwrite a newer generation. Cached/disconnected data remains labelled and read-only. Version mismatch enters terminal `RELOAD_REQUIRED` and prevents guarded commands.

Use Composition API, typed generated DTOs, accessible semantic controls, keyboard/focus feedback and text labels alongside colors. Show loading, unavailable, partial, cached and error states truthfully. The current shell/visual direction is in `SPEC-interface-design.md`; backtest boundaries are in `SPEC-backtest-api.md` and `SPEC-backtest-web.md` under `../backtesting/`.

Verification must exercise formal APIs, production composition, current extraction/review/activation, isolated simulation, acknowledgement with zero inventory change, restart and old/new protocol mismatch using temporary databases and deterministic providers. The [latest local acceptance](../../verification/2026-10-03-unified-plan.md) records executed coverage and limits. Live provider acceptance, user-database migration and deployment are separate operations.
