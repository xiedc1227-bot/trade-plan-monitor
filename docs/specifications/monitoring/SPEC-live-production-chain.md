# Spec: live-production-chain

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-live-production-chain.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Make the installed local Web application truthfully usable with the production monitoring runtime: typed normal projection unavailability, restart-safe persistent projections, certified stock and board-index acquisition, one-batch deadline evaluation, and a browser state machine that never infers domain readiness from a transport failure.

Module boundaries are maintained in `docs/architecture/CAPABILITY-MAP.md`. This contract owns persistent projections, provider admission and bounded acquisition; `SPEC-unified-plan.md` owns current plan operations and supersedes retired live families/commands.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live"
.\.venv\Scripts\python.exe -m pytest tests/contract/test_tushare_live.py -q -m "not live"
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run test:e2e
npm --prefix web run build
git diff --check
```

The live selector is separate and serial. It may run only with an injected one-shot secret and an operation-appropriate market window.

## Projection Availability Contract

`GET /api/v1/dashboard`, `GET /api/v1/symbols`, and `GET /api/v1/symbols/{symbol}` return HTTP `200` for normal projection lifecycle states. Existing successful `SymbolPage` and `SymbolDetailResponse` structures remain unchanged; `DashboardResponse` adds the nullable UUIDv4 `runtimeGeneration` used to bind transport liveness to the runtime instance that authored the snapshot. Each endpoint additionally permits the same strict `ProjectionUnavailableResponse`:

```json
{
  "availability": "UNAVAILABLE",
  "reason": "AWAITING_FIRST_EVALUATION",
  "observedAt": "2026-09-05T10:00:00.000000+08:00",
  "sequence": 42,
  "symbol": "003043.SZ"
}
```

`symbol` is absent for dashboard/collection scope and required for a symbol-detail scope. Valid reasons are `EMPTY_DATABASE`, `NO_ACTIVE_PLANS`, `NO_ACTIVE_PLAN`, and `AWAITING_FIRST_EVALUATION`; scope and reason must agree. The response has no fake count, row, decision, bar, market-index snapshot, or health fact. A syntactically valid unknown symbol remains `404 NOT_FOUND`. Storage/migration/corruption/composition failure remains the fixed `503 SERVICE_UNAVAILABLE` envelope.

The backend decides the reason from one consistent read boundary. A historical hash-only evaluation is not a complete result and therefore cannot make a projection available.

## Migration 0009 and Persistent Read Model

Migration `0009_live_monitor_projection` adds, without rewriting prior rows:

- `evaluation_result`: exact existing evaluation identity, immutable `result_hash`, canonical complete result JSON, evaluated/source times, and schema version;
- `symbol_decision_head`: one symbol head pointing to a complete evaluation result and its committed event sequence;
- `symbol_health_projection`: one complete current health projection per symbol with monotonic revision;
- `pending_official_close`: one recoverable unresolved official-close identity per symbol/date/plan/formula;
- `market_index_snapshot`: immutable canonical snapshot JSON and all existing content hashes/revision identities;
- `market_index_snapshot_head`: one current head per mapping/index/cutoff request domain.

Foreign keys and checks must prevent a head from naming a missing or cross-identity payload. Existing `evaluation_ledger` rows, event/alert IDs, global sequences, plan bytes, result hashes, backtest stores, and Schema v1 data are untouched. Downgrade must refuse before destructive DDL when any new table contains user data; recovery uses a verified database backup rather than reverse synthesis.

`PersistentMonitorReadService` assembles dashboard and symbol responses from persisted heads under one Unit of Work, including the same `monitor_sequence` high-water mark. Empty database, no active plans, no active plan for a requested symbol, and an active plan before a complete result return the typed unavailable response. It never manufactures a zero dashboard or recomputes a decision from a ledger hash.

## Atomic Evaluation Contract

For each intraday or official-close identity:

```text
provider fetch outside transaction
→ validate/normalize and persist market facts in a short transaction
→ build immutable context and evaluate outside transaction
→ one short transaction:
   claim + evaluation_result + decision head + episode/risk intents
   + pending-close transition + alert/outbox + audit + committed events
→ commit
→ publish exact committed invalidation event
```

Duplicate identity publishes nothing. Rollback changes no head, risk/episode state, outbox, event sequence, or pending-close state and publishes nothing. Publication failure does not undo committed state; replay remains database-backed.

## Production Provider and Runtime Contract

- `TushareClient` and the stock provider use only a certified stock profile. `rt_min(freq="1MIN")` receives one comma-separated request containing all active symbols, capped at ten, exactly once per deadline. Evaluation uses those returned/persisted bars and cannot perform a second quote request.
- The deadline coordinator captures one immutable plan, symbol, and activation-revision set. `SymbolService` must use that exact symbol tuple without independently re-reading the active set; later activations wait for the next deadline, while deactivation/rotation is rejected by the final revision fence.
- `RequestController` enforces global physical-start pacing, bounded admission, a complete 15-second admission timeout followed by a separate complete 15-second provider timeout, classified cooldown/backoff, and deadline priority. Closing the controller wakes every queued waiter with `CLOSED` before any callable starts. Database work never runs in a provider worker and provider/network work never runs inside a database transaction.
- After each index provider fetch, the coordinator advances to a real whole-second boundary before producing persistable success or error evidence, then rereads the injected clock and rejects any future observation. This post-fetch boundary applies equally to successful and failed calls; it does not backdate evidence or weaken future-time validation.
- A symbol with a durable `pending_official_close` cannot be deactivated or rotated to another plan. The plan writer lock and pending check share the same transaction, so startup recovery always retains an active immutable owner for that pending identity.
- Startup independently validates capabilities, refreshes calendar/limits/reference history, groups durable pending closes by pending trade date so symbols with the same required board share the batch's revision-aware index snapshot, performs serial current-day recovery, and then starts the deadline supervisor. A failed stage remains visible and recoverable; no owned task is orphaned.
- `RuntimeEvaluationService` groups due symbols and index requirements, constructs immutable inputs, evaluates each complete five-minute identity once, and commits through the atomic boundary above.
- After an owned realtime deadline completes, `GAP_REPAIR` may consume only same-day gaps from persisted symbol-health snapshots. It runs as a serial owned await, creates no detached task, and yields whenever deadline work is running/queued or at most `31.25` seconds remain before the next realtime deadline. Repaired bars are persisted for later evaluation; the completed identity is not evaluated a second time.
- The deadline coordinator prioritizes the next market deadline over recovery/background work. Runtime shutdown stops controller admission immediately on entering `STOPPING`, gives owned work its bounded finish/cancel window, and only then joins the executor. A recoverable supervisor reports failure, applies bounded restart policy, and cannot silently die while health remains `LIVE`.
- Only an unexpected post-start run-loop return or exception observed while runtime health was `RUNNING` is restartable. Each attempt creates a fresh runtime, with at most three restarts per Web-composition lifetime after exact delays of `1`, `2`, and `4` seconds. Process restart resets the budget.
- During restart backoff and after exhaustion, health is `DEGRADED`, `read_only=true`, and `nextPollAt=null`. Stop/cancellation, startup/configuration/migration failure, or cleanup failure is terminal and is never retried. Every delay/runtime task is composition-owned, cancellable, and joined; service bindings change only after failed-runtime cleanup succeeds.
- The board-index provider is independent from the stock provider and has its own certified `idx_mins` historical, `rt_idx_min_daily` current-day, and `index_daily` endpoints/profile and `SourceTimeLabel`. Current live scope contains `000001.SH`, `399001.SZ`, `399006.SZ`, and `000688.SH`. The known `899050.BJ` identity remains `DEFERRED`; certification calls none of those endpoints for it, and provider acquisition rejects it before request control. One index failure creates blocked evidence only for explicit plan paths that require that index; unrelated indices and plans without index conditions continue.
- Within one deadline's immutable due-plan batch, each required index endpoint is called at most once and every dependent plan consumes the same revision-aware `snapshot_hash`. Replay of an already committed evaluation identity performs zero provider requests. A 15:00 intraday evaluation and `OFFICIAL_CLOSE` remain distinct evaluation kinds, so each may perform its own endpoint call even though both cutoffs are 15:00 and their observed/provider revisions may differ. If a later capture has the same provider revision and identical canonical market content, persistence reuses the existing snapshot/hash while advancing only capture-time head metadata; any canonical-content mismatch fails with an identity conflict. Revision sequences such as `r1` → `r2` → `r1` resolve back to the exact persisted canonical snapshot for each revision, and every plan result binds that persisted snapshot/hash. Snapshot fields, hash formulas, and uniqueness constraints are not weakened.

The production stock path remains dependency-blocked until a fresh stock capability record is `READY` and selects a verified `SourceTimeLabel`. The historical T058 visible-block result is not that record. Startup may read and validate the unified ignored `config/app.yaml`; before the evidence gate passes, production composition uses the live request-control limits but must stay `DEGRADED`, construct no credentialed provider client, make no provider request, and must not construct an actionable deadline coordinator. The current stock record satisfies the evidence gate through 2026-09-16 14:48:40.405317 Asia/Shanghai with all five capabilities `READY` and `SourceTimeLabel=END`; installed production must still validate and consume it before becoming actionable.

The board-index gate is evaluated per required in-scope index rather than upgraded from a surface-wide label. The current independent profile is valid through 2026-09-16 13:10:41.07832 Asia/Shanghai with `SourceTimeLabel=END`; `000001.SH`, `399001.SZ`, `399006.SZ`, and `000688.SH` are `READY`, while `899050.BJ` is `DEFERRED` without a provider call. The historical profile retains its observed `899050.BJ=ERROR`, but BSE 50 is outside the current trading scope. Bringing BSE stocks into scope requires a new specification and live certification before production admission.

## Live Harness and Evidence Contract

Ordinary tests make zero external requests. The live harness runs in the selected process and reads `tushare.token` directly from the ignored local `config/app.yaml`. `ai.api_key` follows the same direct-configuration convention. These fields are the only credential source; environment variables and separate credential files are not read.

Real calls are serial, single-concurrency, start at least `1.25` seconds apart, time out after `15` seconds, and have no automatic retry. The first `429` stops all later calls. Stock and index observations use separate reports, authorization contexts, capability sets, and timestamp labels. Realtime-minute label semantics may be certified only after `trade_cal` proves that the observation date is open and the current window can expose completed minutes. Outside that window the outcome is `NOT_RUN_MARKET_WINDOW`, not a guessed mapping. DeepSeek and all other providers are forbidden.

## Vue Component and State Map

| Component/composable | Responsibility | Contract |
|---|---|---|
| `useMonitorStream` | Own snapshot fetch, retry, socket, and liveness | no Health fallback; socket only for a validated snapshot |
| `AppShell` | Render non-color-only connection state | readonly semantic state |
| `DashboardRouteView` | Compose snapshot or typed unavailable presentation | no empty-state inference |
| `SymbolRouteView` | Compose detail or typed unavailable presentation | no decision reconstruction |
| `PriceChart` | Lazy ECharts rendering and accessible table | async chart chunk only on chart routes |

The browser state machine distinguishes `SNAPSHOT`, `UNAVAILABLE`, `STALE`, and `DISCONNECTED`. `SNAPSHOT` means a validated authoritative response is present; liveness may refine its visible connection label but cannot fabricate data. `UNAVAILABLE` is only the typed HTTP `200` variant and never opens WebSocket. `STALE` requires a previously validated cached snapshot. `DISCONNECTED` is reserved for transport/timeout/invalid-response failure without usable cached state. A backend-certified official-close `RISK_BREACH` remains authoritative when its decision health is `STALE`: its 15:00 official bar, matching breach date, complete required data, risk state, next step, and satisfied `OFFICIAL_CLOSE_BELOW_LEVEL` evidence must agree. The browser displays that stored decision and its `STALE` health together; it neither drops the risk signal nor relabels the data `LIVE`. Every other actionable decision still requires `LIVE` health. Public REST and WebSocket sequences are capped at JavaScript's safe-integer maximum. A heartbeat can establish liveness only when both its exact sequence and `runtimeGeneration` match the applied authoritative snapshot; a supervisor replacement or process restart therefore forces REST recovery even if its clock moves backward.

Playwright uses the installed Google Chrome channel (`channel: "chrome"`), one worker, no retry, and deterministic same-origin fakes unless running the separately composed local production journey. The installed journey allocates a test-owned loopback port, accepts readiness only after the owned launcher identifies its Uvicorn process, retains both process identities until confirmed exit, and bounds every graceful/forced cleanup tool. Every acceptance case requires zero console errors, zero console warnings, and zero `requestfailed`. Firefox is not a gate. Non-chart routes must not request the chart chunk.

## Testing Strategy

- RED-first unit and integration tests for typed availability, empty/no-plan/first-evaluation states, 503 fault distinction, migration preservation, rollback, restart reconstruction, one-batch deadlines, no second fetch, isolated index failure, and supervisor recovery.
- Migration tests start from every supported prior revision, preserve exact protected rows/hashes, and reject unsafe downgrade.
- OpenAPI snapshot and generated TypeScript must change together and remain byte-current.
- Vue/Vitest covers every state transition and proves removal of the Health fallback. Chrome covers console/request cleanliness, no unavailable-state WebSocket, route behavior, and chunk isolation.
- Configuration tests prove direct Tushare and AI credentials are the only accepted source.

## Boundaries

- Always: backend is authoritative for availability, complete results, health, and plan/index dependency.
- Always: keep provider I/O outside database transactions and publication after commit.
- Always: preserve historical identities, hashes, Schema v1, backtests, DeepSeek, and prior Web work.
- Ask first: add another provider, change formula/mapping versions, place orders, expose a non-loopback listener, or reinterpret historical ledger rows.
- Never: manufacture an empty snapshot, infer readiness from Health in Vue, share stock/index timestamp evidence, retry live certification automatically, or call DeepSeek from the Tushare certification runner.

## Success Criteria

- Empty/no-plan/first-evaluation states return typed `200`; true storage/composition faults return `503`.
- A complete committed evaluation survives restart and produces the same authoritative dashboard/symbol projection and high-water sequence.
- One deadline starts at most one ten-symbol realtime batch and no evaluation performs another fetch.
- Persisted same-day gaps may be repaired only when more than `31.25` seconds remain before the next realtime deadline and must never delay that deadline.
- Failure of one board index affects only its explicit dependent plan paths.
- A certified official-close `RISK_BREACH` survives restart and remains visible with truthful `STALE` health; no other actionable decision bypasses the `LIVE` requirement.
- Vue opens no socket for typed unavailable state and Chrome acceptance is clean.
- ECharts code is absent from non-chart route requests.
- All required offline gates pass; live evidence is recorded only when its secret and market-window preconditions are satisfied.
