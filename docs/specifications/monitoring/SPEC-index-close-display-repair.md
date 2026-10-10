# Design: index-close-display-repair

> Canonical English design. Chinese review copy: [SPEC-index-close-display-repair.zh-CN.md](SPEC-index-close-display-repair.zh-CN.md).
> Status: IMPLEMENTED — user authorized implementation on 2026-10-09; acceptance and local rollout evidence are recorded in the paired verification report.
> This is one focused repair of the existing monitor-index-trends capability, not a new monitoring subsystem.

## ICDR01 Objective, scope and assumptions

Keep validated index quotations visible across a later acquisition failure and a process restart; display the exchange session separately from data completeness; make the selected quote and chart describe the same committed data. The default selected index remains 上证指数 (`000001.SH`).

The user authorized implementation and acceptance against this design on 2026-10-09. Existing intraday frequency, provider permissions, endpoint selection, official daily reconciliation, plan evaluation and alert admission are preserved. A dedicated bounded retry for the final session bucket is included. No new dependency or provider permission is required.

References: [index-data](SPEC-index-data.md), [monitor-index-view](SPEC-monitor-index-view.md), [monitor-index-trends](SPEC-monitor-index-trends.md), [runtime-status](SPEC-runtime-status.md), [runtime-recovery](SPEC-runtime-recovery.md). The current index-data specification already forbids a failed result from overwriting a successful same-cutoff head. This design makes that rule durable. The display endpoint is an authorized extension that supersedes the earlier trends exclusion of a new public API. Existing DTOs and plan contracts remain effective.

## ICDR02 Reproduced failure and evidence limits

Local observations for `000001.SH` on 2026-10-09, all times `Asia/Shanghai`:

| Observation | Data cutoff | Result |
|---|---|---|
| 15:00:14 | 14:55 | `STALE`, close 3814.466 |
| 15:20:01 | 15:00 | `LIVE`, close 3813.791; complete final five-minute data was stored |
| 16:00:16 | null | `BLOCKED`, `PROVIDER_UNAVAILABLE`; empty acquisition result |
| 16:41 read | null / 14:55 | Dashboard headline empty; history returned 47 bars ending at 3814.466; runtime index scope reported `READY` |

The historical 15:20 successful snapshot still exists. The displayed history lost the final bar because its reader follows current heads, and the 15:00 head was moved to the empty failed snapshot. This is a reference-selection defect, not deletion of the successful immutable payload. The stored error proves acquisition failure; it does not establish the precise network or upstream cause. The 3813.791 value is a completed five-minute close, not a newly verified official daily close.

Code path: `runtime/market_indexes.py` preserves a successful same-cutoff value in memory, while `runtime/service.py` persists the incoming failed batch. `state/projections.py` advances the head by observation time. The dashboard and `web/persistent_market_index_history.py` read those durable heads. The component directly maps `BLOCKED` to 阻断 and has no exchange-session state.

## ICDR03 Required invariants

1. A transient acquisition failure cannot erase or replace a validated successful snapshot for the same identity and target. Restart must select the same effective data as the running process.
2. Retained data from an older target or trading date is never promoted to current data. A previous request set cannot satisfy a new plan's additional fact requirements.
3. A later successfully validated correction may replace a successful snapshot at the same target. Provider revisions are content identifiers, not chronological counters; compare acquisition order, not numeric revision size.
4. A display fallback never grants evaluation or delivery authority. Plan consumers keep the actual acquisition outcome and existing freshness, dependency and permission guards.
5. A failed acquisition and the retained data remain separately inspectable. A valid final quotation plus a failed later refresh is a legitimate state, not contradictory status.
6. REST reads perform no provider calls, repairs or business writes. Snapshot payloads, their hashes and historical decision evidence are immutable.

## ICDR04 Durable data and acquisition selection

Keep `market_index_snapshot` as the immutable acquisition payload store. Keep `market_index_snapshot_head` as the effective snapshot for its existing exact key `(mappingVersion, indexCode, decisionCutoff, requestSetHash)`. Add a bounded latest-attempt table, named `market_index_acquisition_state`, keyed by `(mappingVersion, indexCode)`, containing `attemptId`, `decisionCutoff`, `requestSetHash`, `observedAt`, `snapshotHash`, `health`, `issues`, and the committed `sequence`. Store closed sanitized codes only. Pending retry time is read from recovery state, not duplicated here. Bind acquisition admission to the existing source/configuration identity and runtime generation; do not store credentials in this table. A source change revokes old data's current eligibility even if its index and date still match.

Internal provenance fields `sourceIdentity`, `effectiveSourceIdentity`, and `effectiveSnapshotHash` prove that the selected effective payload belongs to the current configuration/semantic source. Older records without proof remain visible as `CACHED`; current authority is never guessed. These fields do not extend public DTOs.

When a later acquisition reuses an already stored content revision, compare the actual acquisition time against the effective head's `updated_at`. Preserve the reused immutable snapshot's original `observed_at`; an intermediate out-of-order correction must not regress the head or latest attempt.

One pure selection policy is shared by persistence, runtime restoration and reads:

| Current effective head | Incoming result for the exact key | Effective head |
|---|---|---|
| Absent | Any validated snapshot envelope | Incoming result |
| `LIVE` | Acquisition failure, stale response or gapped response | Retain current; update latest attempt |
| `LIVE` | Later validated `LIVE` correction | Accept incoming correction |
| Non-live | Later validated `LIVE` result | Accept incoming result |
| Non-live | Later non-live result | Record latest outcome; retain accessible earlier display data separately |
| Any | Older or superseded acquisition | Do not regress effective head or latest-attempt state |

Persistence commits immutable payload, latest attempt, allowed effective-head change, recovery state and existing `market.index.updated` invalidation atomically. Publish after commit. The event payload remains an invalidation; clients re-read authoritative data. Emit an invalidation when the latest attempt changes even if the effective data head is retained. The attempted snapshot and the effective display snapshot must be explicit separate return values; do not replace a failed plan input with a retained display value.

For display, first seek usable data for the required target and current source identity. Otherwise select the most recent locally validated snapshot with displayable bars, within the chosen display trading date, and label it incomplete/cached. Never join different revisions into one selected card. Known identity, timestamp, formula or source-integrity failures require an unverified warning; retained data may be shown as cached but must not be labelled complete current evidence. A permission failure remains visible in acquisition diagnostics and retains existing plan restrictions.

Keep the existing raw snapshot health vocabulary. `LIVE` describes validation at its captured target; current display completeness is separately computed against the expected target and trading date. Existing index scopes describe target readiness, while acquisition diagnostics describe the latest fetch. Both derive from the same committed selection policy; neither layer invents readiness from the other.

## ICDR05 Consistent display read contract

One additive read-only endpoint: `GET /api/v1/market-indexes/overview`. It assembles the four cards and market turnover in one local read transaction. No caller-supplied dates, codes, pagination or provider options. Fixed order: `000001.SH`, `399001.SZ`, `399006.SZ`, `000688.SH`; the hidden `399107.SZ` remains turnover-only.

Reason: the existing dashboard summary and separately fetched history can observe different revisions. A new bounded display projection solves this without redefining existing `snapshotHash`, signed history cursors, plan DTOs or monitor contract `2`. Do not silently add fields to the strict existing DTOs. The new endpoint has its own `schemaVersion=1`, uses the existing local Origin/access guards, returns `Cache-Control: no-store`, and is a display resource rather than an execution preflight.

| Object | Exact fields / meaning |
|---|---|
| Envelope | `schemaVersion`, `observedAt`, `runtimeGeneration`, `sequence`, `marketSession`, `indexes`, `marketTurnover` |
| `marketSession` | `phase`, `calendarStatus`, `sessionDate`, `displayTradeDate`, `expectedBucketAt` |
| Each index | `indexCode`, `displayName`, `board`, `dataStatus`, `data`, `latestAcquisition` |
| `data` (nullable) | `snapshotHash`, `observedAt`, `completedBucketAt`, `sourceKind`, `closePoints`, `priorClosePoints`, `sessionChangeRatio`, `highPoints`, `lowPoints`, `amount`, `bars` |
| `latestAcquisition` (nullable) | `decisionCutoff`, `observedAt`, `health`, `issues`, `nextRetryAt` |

Datetimes and decimal strings follow existing canonical contracts; nullable fields are explicit. `runtimeGeneration` follows the current owner's nullable UUID contract. `sequence` is the existing committed event sequence, not a new event stream. There are exactly four index entries even when all data is absent. `bars` uses the existing five-minute bar DTO and is capped at 48 for one display day. Maximum response is 512 KiB; enforce the bound and never truncate silently. A missing index returns its empty card without failing healthy siblings. Actual storage or integrity faults use the existing sanitized service-error envelope rather than a fabricated empty success.

All fields inside `data` come from the same immutable snapshot. Restrict bars to `displayTradeDate`; `completedBucketAt` equals the last returned bar and `closePoints` equals its close. High/low are extrema of returned bars; `amount` is null if any required returned-bar amount is missing. Prior close is the latest certified official daily close strictly before the display day. If unavailable, retain the point and bars but leave `priorClosePoints` and `sessionChangeRatio` null and mark unverified. Calculations use backend `Decimal`. Preserve the original data observation time; the read time belongs only to the envelope.

`dataStatus` is `CURRENT`, `INCOMPLETE`, `CACHED`, `EMPTY` or `UNVERIFIED`. `CURRENT` requires all expected session bars through `expectedBucketAt`, matching display date, verified source and prior close. `INCOMPLETE` identifies a missing tail or internal gap. `CACHED` identifies retained data without current session/source authority. `EMPTY` has no display data. `UNVERIFIED` exposes a calendar/source/integrity uncertainty. No status implies a trading action. Missing bars are never interpolated.

`marketTurnover` reuses the existing nullable turnover DTO and exact formulas. Compute it from aligned effective snapshots for the two approved benchmarks in the same read transaction; preserve existing cutoff, prior-session and amount-completeness checks. Do not sum unequal cutoffs or substitute Shenzhen Component for Shenzhen A-share.

Retain existing dashboard, history and symbol APIs. Repair their effective-head selection as well. Existing signed history traversal semantics remain intact. The overview switches to the new endpoint only as a coordinated backend/frontend release; an unsupported endpoint shows a version/update message rather than mixing legacy summary with new bars.

## ICDR06 Exchange session and UI behavior

The backend resolves `phase=PREOPEN|OPEN|BREAK|CLOSED|UNKNOWN` from the existing trusted trading calendar and Shanghai session rules. Calendar state is `KNOWN|UNKNOWN`. A known closed date uses `CLOSED`; a missing calendar uses `UNKNOWN`, never “closed” guessed from weekday or browser time. On a trading day, phase intervals are [09:30, 11:30) and [13:00, 15:00) for open, [11:30, 13:00) for break, 15:00 onward for closed, and before 09:30 for preopen. This phase transition does not exclude the existing 11:30 or 15:00 completed bar. The expected final target is 15:00 and remains 15:00 after the close, not 16:00 or 17:00. Full-day completeness requires 48 valid five-minute bars, excluding a 09:30 opening quote.

On an open day at or after 09:30, `displayTradeDate` is that day even if no data is ready. Before opening and on non-trading days, show the last certified trading day's data with its explicit date; do not call it today's data. `sessionDate` is the current Shanghai date. With unknown calendar, the latest stored data date may be shown as cached; `expectedBucketAt` is null and no current/complete claim is allowed. During open trading use the existing completed-bucket and 12-second grace rules; at the two closing boundaries expose the final target and an incomplete state until it arrives. Before the first completed bar the expected target is null and the card cannot claim completeness. When displaying a prior certified day, its target is that day's 15:00.

| Session / data | Main card text and behavior |
|---|---|
| `OPEN` + `CURRENT` | 实时; normal point and line |
| `OPEN` + `INCOMPLETE` | 数据待更新; retain point/line and explicit cutoff |
| `BREAK` + `CURRENT` | 午间休市; retain morning line |
| `BREAK` + `INCOMPLETE` | 午间休市 · 数据待补齐 |
| `CLOSED` + `CURRENT` | 已收市; completed point and line; data cutoff 15:00 for that trading day |
| `CLOSED` + `INCOMPLETE` | 已收市 · 数据待补齐; retain verified partial data |
| `PREOPEN` | 未开市; identify the displayed historical trading date |
| `EMPTY` | No invented point; show session text plus 暂无行情 |
| `CACHED` / `UNVERIFIED` | Show original date/cutoff plus 已缓存 / 数据待核验; never advertise current completeness |

A later fetch failure appears as a secondary “最近更新失败，保留已取得行情” message and in system diagnostics. Do not replace a complete closed-session card with a red 阻断 badge. Transport disconnection is a separate cached presentation overlay and does not change the backend session or certify data. A five-minute close remains identified as such; it is not relabelled as an official daily settlement value.

`MarketIndexDataStrip.vue` keeps selector state, with 上证指数 selected on first mount. `MarketIndexTrendCard.vue` renders one complete index item. `MarketIndexSparkline.vue` remains a renderer and breaks the line at missing expected intraday bars; the normal lunch interval is not a data gap. A focused composable owns overview reads, cancellation and atomic response replacement. Never update the headline while retaining another revision's line. During a failed refresh retain the whole prior envelope with a cached indication. Use existing monitor invalidations/sequence changes and session-boundary observations for refresh, with one request in flight and coalescing; no new browser provider polling. Abort and generation guards discard old responses. Native selectors, keyboard navigation, reduced motion and 320/768/1024/1440 layouts remain required.

## ICDR07 Final-bucket publication retry

Current next-minute lag recovery relies on a market minute. There is no 15:01 market minute, so the 15:00 lag can survive until 15:20. Add a dedicated scheduled final-bucket recovery, independent of the existence of a subsequent trading minute. Apply it to 11:30 and 15:00 so the same boundary defect is not retained at lunch.

Fixed policy: eligible missing-tail snapshots receive at most 3 supplemental acquisitions at target +72 seconds, +132 seconds and +252 seconds. Window closes at target +5 minutes. These deadlines align the first supplement with the usual next-minute +12-second attempt. Index acquisition is still shared and rate/admission controlled. Deduplicate with ordinary lag retries, transient recovery and official-close work: at most one acquisition per index/target in flight. Permission, quota and integrity faults cannot bypass their existing gates through this path.

Persist target, reason, attempt count, next due time and expiry under the existing recovery repository using an explicit recovery kind. Keep ordinary transient recovery's 30/60/120-second policy separate. All supplemental physical starts for the same final target share the limit of 3, even when the failure reason changes; changing reason must not reset the budget. Controller admission/cooldown deferral consumes no attempt until the request starts, and still cannot extend expiry. Stop on complete target data, expiry, a newer target, or superseding source/generation. Resume only compatible unexpired work after restart; clock reversal follows existing runtime safeguards. Do not replay completed plan evaluations or alerts.

Exhausted final-target records with `attempts=3` remain until target +5 minutes, including targets that started as `TRANSIENT`, so later publication lag cannot reopen the budget. Existing pending DTOs read only `attempts<3`. Recovery records retain `sourceIdentity`; mismatched sources are not restored. Downgrade refuses to discard `FINAL_BUCKET` or `attempts>2` records.

If the process resumes late, execute at most one currently eligible overdue attempt and schedule any remaining attempt no sooner than 60 seconds after it completes and before expiry; never issue a catch-up burst. After the window, keep explicit incomplete display and existing 15:20/16:00/17:00 reconciliation. This proposal does not stop official daily refreshes and does not change normal intraday frequency.

## ICDR08 Existing-data recovery and rollout

Introduce additive schema changes through the existing Alembic workflow; the revision is `0025_index_close_display`. New latest-attempt and recovery-kind storage is bounded by existing supported index identities and pending targets. No manual SQL against the running user database is part of this design deliverable.

Before rollout, stop the owner through its normal drain path and take a consistent SQLite backup including committed WAL state. Run an idempotent local repair inside the approved migration/startup workflow: for each affected current display date and exact head key, inspect retained immutable snapshots, validate hashes/identity/source, and restore a later-failure-overwritten `LIVE` head from the newest successful capture for that same key. Preserve the latest failed attempt separately. Never delete failed payloads or alter decision references. Do not cross request sets, mapping versions or trading dates. Corrupt candidates fail the repair rather than silently become current.

For the reproduced incident this recovers the 15:20 snapshot with cutoff 15:00 and value 3813.791; the history source then returns 48 bars. Backfill latest-attempt metadata from the committed acquisition event order and associated snapshots; if reliable linkage is absent, leave metadata explicitly unknown instead of inventing a timestamp. Record repair counts in sanitized diagnostics. A second run performs no duplicate repair or event emission.

Apply backend selection and migration before serving the updated frontend. Publish a normal invalidation when recovered data becomes visible, load a matching frontend build and verify the live read. Rollback uses the stopped-owner backup or a compatible prior reader; never run an older writer against the new recovery-kind schema without a tested downgrade. Acceptance must cover reopen/restart, not only one fresh browser load.

## ICDR09 Acceptance and regression matrix

| ID | Scenario | Required result |
|---|---|---|
| A01 | Successful 15:00 data, then 16:00 transient failure | Point, change and all 48 bars retained; closed state; latest failure separately visible |
| A02 | Restart after A01 | Same effective hash/data and latest-attempt result before/after restart |
| A03 | New target fails while older target is successful | Older data is visibly incomplete/cached; it cannot satisfy new plan evidence |
| A04 | Newer valid correction at the same target has a smaller numeric provider revision | New correction accepted; headline and line update atomically |
| A05 | 15:00 or 11:30 missing tail | Supplemental retry runs without a next market minute; only lagging indexes requested |
| A06 | Restart, cooldown, slow in-flight work, reason change, expiry | No duplicate or burst; limit 3 and 5-minute expiry hold across restart; no plan replay |
| A07 | 15:00 reached but only 47 bars, or an internal gap exists | 已收市 · 数据待补齐; no fabricated final point or complete turnover |
| A08 | Non-trading date, preopen, unknown calendar, midnight rollover | Correct phase and explicit display date; no false current-day/closed assertion |
| A09 | Permission revoked or identity/integrity failure after valid data | Retained facts are labelled appropriately; diagnostics and plan restrictions survive |
| A10 | Snapshot changes while browser refresh is in flight | Whole coherent envelope retained/replaced; stale response discarded; healthy sibling cards usable |
| A11 | Historical poisoned head and repeated repair | Full line restored from valid stored payload; immutable hashes/decisions unchanged; repair idempotent |
| A12 | Empty data, missing prior close, missing amount, transport loss | Honest placeholders/partial facts; no invented ratio, total or real-time claim |
| A13 | Existing monitoring, signed history, official daily and turnover contracts | No incompatible DTO change, signed-cursor regression, authority promotion or altered formula |

Deterministic fake clocks and fake providers must reproduce the observed success/failure sequence before implementation. Existing in-memory-only coverage is insufficient: test the actual persistence transaction, reopened repository, REST response and component together. Browser coverage verifies the point and the chart endpoint value, not just the badge text.

## ICDR10 Code locations, commands and completion boundary

Expected ownership: selection and acquisition metadata in `runtime/market_indexes.py`, `runtime/service.py`, `state/projections.py` and `state/models.py`; additive migration under `state/migrations/versions/`; final-bucket deadlines in `runtime/scheduler.py` and `runtime/production.py`; projection/session assembly in the Web read-service layer; new overview route alongside `web/routers/market_indexes.py`; readonly frontend client/types, composable and the existing market-index components. Use Python 4-space indentation, typed small pure selection functions, canonical `Decimal`, and Vue Composition API with typed props and events. Avoid putting selection rules in Vue templates.

Run from the project root, using the existing virtual environment. These are regression commands; executed results and full directory runs are recorded in the paired verification report:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_market_index_runtime.py tests/integration/test_market_index_snapshots.py tests/integration/test_live_projection_repository.py tests/integration/test_persistent_market_index_history.py tests/integration/test_market_index_web.py tests/unit/test_monitor_runtime.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_status_projection.py tests/integration/test_runtime_status_official_close.py tests/integration/test_runtime_status_websocket.py tests/unit/test_market_turnover.py -q
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e -- dashboard.spec.ts
```

Add focused acceptance tests for the new overview contract, migration and final-bucket recovery to these commands when implemented. The backend release also runs its full offline suite; no live provider requests are needed for regression proof. The paired source specifications and generated contracts must be updated together at implementation, including the deliberate overview API extension. Do not weaken existing assertions to accommodate a contradiction.

Implementation and acceptance remain limited to ICDR01. The task record is `tasks/index-close-display-repair-plan.md` and its Chinese copy; it does not replace other active work. Acceptance evidence, backup, migration and actual service results are recorded in the [verification report](../../verification/2026-10-09-index-close-display-repair.md).
