# ADR 0004: Use Authoritative Projection Availability and Atomic Live State

> Canonical agent-facing English version. The human-review Chinese version is `0004-use-authoritative-projection-availability-and-atomic-live-state.zh-CN.md`; both documents must remain semantically equivalent.

- Status: `Accepted`
- Date: `2026-09-05`
- Initiative: `live-production-chain`
- Modules: `projection-availability`, `live-state-store`, `live-market-runtime`, `live-index-runtime`, `web-availability`

## Context

The packaged Web application can be healthy while no authoritative dashboard or symbol decision projection exists. The temporary browser workaround treats a dashboard `503` as a cue to probe Health, but that makes Vue infer a normal domain state from transport failures. The current hash-only evaluation ledger also cannot reconstruct a complete decision after restart, and the production runtime intentionally stops before provider work because live stock and board-index timestamp contracts remain unverified.

## Decision

1. Normal projection absence is a typed HTTP `200` result owned by the backend. `DashboardResponse` and successful symbol response structures remain unchanged; their endpoints use an additive union with `ProjectionUnavailableResponse`.
2. `ProjectionUnavailableResponse` contains `availability=UNAVAILABLE`, an authoritative reason (`EMPTY_DATABASE`, `NO_ACTIVE_PLANS`, `NO_ACTIVE_PLAN`, or `AWAITING_FIRST_EVALUATION`), `observedAt`, and the committed `sequence`. It contains no fabricated counts, symbol summaries, decisions, bars, index snapshots, or health upgrade.
3. HTTP `503 SERVICE_UNAVAILABLE` is reserved for actual storage, migration, corruption, or composition failures. A missing first projection is never converted into 503.
4. Migration `0009` is additive. It stores complete canonical `evaluation_result`, `symbol_decision_head`, `symbol_health_projection`, `pending_official_close`, `market_index_snapshot`, and `market_index_snapshot_head` data without changing the existing `evaluation_ledger` identity or hash.
5. Historical hash-only ledger rows are never recomputed or given invented payloads. Until a new complete result commits, their projection is `AWAITING_FIRST_EVALUATION`.
6. Evaluation claim, complete result, decision head, episode/risk intent, committed monitor event, alert/outbox, and pending-close clearance share one short transaction. Provider calls and pure evaluation occur outside it. In-memory invalidation is published only after commit and is never the replay source.
7. Stock realtime and board-index realtime use separate provider contracts, certification records, and `SourceTimeLabel` values. An index failure affects only plans whose explicit condition paths require that index.
8. Vue opens WebSocket only after a validated authoritative snapshot. It renders `SNAPSHOT`, typed `UNAVAILABLE`, `STALE`, and true `DISCONNECTED` states without a Health fallback request.

## Alternatives Considered

### Keep the dashboard-503 Health probe

Rejected because transport errors cannot authoritatively distinguish an empty database, no active plan, first-evaluation delay, and a broken projection store.

### Return an empty successful dashboard

Rejected because zero counts and zero symbols would look like business facts even when no evaluated projection exists.

### Recompute old results from stored hashes

Rejected because the original input snapshot is unavailable and any reconstruction would create new semantics under an old identity.

### Store network responses and state changes in one long transaction

Rejected because network latency would hold database locks and a late failure could blur provider and commit boundaries.

## Consequences

- Web behavior becomes deterministic from one backend response and native console noise from expected 503s disappears.
- The successful dashboard payload stays compatible, but generated clients must accept the additive unavailable union.
- Migration and restart tests must prove identity/hash preservation and atomic rollback.
- Live readiness may remain unavailable until stock and index certifications succeed in valid market windows; the application must report that honestly.

## Configuration and Reversal

As revised by the user on 2026-09-07 for this personal tool, provider credentials may be stored directly in the Git-ignored `config/app.yaml` and read by the selected process. The former Windows credential-store and one-shot child-process boundary is removed. Reversal restores code and a verified pre-migration database backup; it does not rewrite Schema v1 rows or invent reverse data transformations.
