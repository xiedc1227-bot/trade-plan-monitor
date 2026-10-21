# Bounded monitor evidence sharing specification

Status: authorized 2026-10-21. Baseline `4c71bcc`. Design: [proposal](PROPOSAL-monitor-evidence-sharing.md). [Chinese copy](SPEC-monitor-evidence-sharing.zh-CN.md). Tasks: [implementation](../../../tasks/monitor-evidence-sharing.md).

## MSH-S01. Scope and order

Preserve existing proposal/evidence and all edits. First measure real HTTP/heartbeat overlap, then implement bounded in-flight index evidence validation sharing. Do not share full responses, health observations, eligibility, authority, or completed validation results. No API/schema change, provider command, real evidence cleanup, changed retention, timeout increase, or extra CPU pool. Local service restart with unchanged configuration is permitted only after checking no active backtest jobs and physical drain. Do not commit/push without a new request.

## MSH-S02. Interfaces and ownership

`ProjectionRepository.list_latest_market_index_snapshots` retains standalone streaming behavior and accepts an explicitly injected monitor-owned validator. Extract immutable complete raw head/payload values and one pure validation/ranking function reusing existing typed/canonical/hash/provider/head checks. `RuntimeStatusReadService` owns the sharing registry and whole physical read lifetime. `MonitorWebComposition.stop` closes admission and drains reads before runtime database disposal. Sessions/ORM entities never cross caller/thread boundaries.

Compatibility: after successful physical shutdown only, the captured facade may still serve `get_health` through a new short-lived read scope which accepts only `STOPPED` authority, performs fresh complete validation and drains in `finally`. The original read owner remains closed; dashboard admission is not reopened. Shutdown failure cannot enable this diagnostic scope.

Automatic runtime cleanup uses the same read-drain fence at the actual WAL checkpoint and database-close callbacks. Per-generation storage pauses reject new reads across both operations and remain held after a timeout/error; successful close releases only that generation's pause. A storage resume cannot reopen permanent composition shutdown or another generation's pause.

## MSH-S03. Independent read contract

Every caller keeps its own authority-before capture on the owner loop, observed time, fresh owned explicit-BEGIN snapshot, plan/inventory/risk/calendar/proof evaluation, activation-identity reread and all authority-after comparisons. Maximum two attempts per caller. Unknown authority remains unavailable. Existing 90-second expiry, date/target boundaries, progress state, health-age validation, command preflight and each WebSocket's delivered cursor/cadence/replay stay unchanged.

## MSH-S04. Joining and evidence completeness

Read every requested historical candidate in deterministic head-key order using left join and 128-row fetch batches. Share only when every literal raw field/type, JSON byte, missing-payload marker, scope and total candidate count matches an in-progress immutable input. Digest equality alone is never enough. Preserve verification of unselected historical evidence and the original verified `snapshot_rank`. A completed/error future cannot serve a new caller, even before registry cleanup. Completion during comparison requires fresh verification. Mismatch/budget fallback validates the entire caller snapshot, including any consumed prefix; use a fresh scan in the same transaction when needed. No cache fallback.

Use scalar SQL columns rather than session-bound entities for raw comparison. Before starting CPU validation, finish comparisons already waiting for input collection, within the original request deadline and admission bounds. This input-confirmation phase never holds a completed proof open. Requests arriving during validation retain the same completion fence; no digest is used as a shortcut.

## MSH-S05. Bounds, cancellation and shutdown

Limits: 1 active physical index validator; at most 1 queued distinct-content owner; at most 8 owned monitor reads, including cancelled observers whose physical work remains; 64 MiB retained raw input across flights, accounting object overhead. Comparisons stream without full copies per follower. Budget pressure falls back to bounded streaming verification or existing `SERVICE_UNAVAILABLE`. No unbounded queue or renewed waiting deadline. Followers never acquire their leader's physical validation permit. Cancelling an observer cannot cancel another reader, remove a flight or release bytes before physical completion. All exceptions are observed. Reject new reads, revoke actionable authority, drain full assembly/identity work and sessions, then permit database disposal. A shutdown timeout retains ownership and reports failure.

## MSH-S06. Measurement contract

Capture logical read source/start/end and physical assembly/index verification start/end/candidate counts, CPU, joins/misses and owned work, without evidence bodies or credentials. Report production HTTP/heartbeat overlap separately from controlled experiments. For real overlap, define denominator and window; include single-tab, multi-tab and result concurrent journeys. Live publication makes cross-run literal equality unsuitable: use a frozen read-only copy for controlled comparison, explicit fixture authority and clock, and label those limits. At least 10 alternating baseline/candidate rounds for 2/8 monitor reads plus one result: CPU median target at least 25% lower; single-monitor wall regression at most 10%. Report failures if targets are missed; do not weaken checks. Also measure service/loop responsiveness, waiting and memory. No p95 claim from this sample.

## MSH-S07. Safety acceptance

Prove complete output/hash/error/rank equivalence before sharing. Cover tamper after a valid read, same size/time, noncanonical JSON, changed domain/hash/formula/provider/head identity, missing/deleted/unselected evidence, forced digest collision and completion races. Cover independent authority/config/generation/activation changes, STALLED/STOPPING, unreadable owner, inventory/risk/calendar/proof changes, 90-second/date/target/clock boundaries, same/different scopes, cancellation of leader/follower/all observers, backpressure/byte budget and held-worker shutdown. Existing result audit/event-set/pin/retention and monitor protocol/heartbeat tests remain required. Browser verification must assert no business writes/page errors and preserve results and monitor re-entry behavior.

## MSH-S08. Delivery

Record paired verification and portable before/after observations, actual overlap, measured limits and test results. Run focused/full relevant backend tests, changed Python lint, frontend unit/type/build and browser journeys. Preserve all real historical evidence; destructive fixtures use isolated storage. User authorization to implement overrides generic skill approval pauses.
