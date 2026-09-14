# R16 selective publication-lag retry plan

Canonical English; `R16-plan.zh-CN.md` is the equivalent Chinese review copy. R16 follows the read-only R15 index diagnosis. The actual R14 run exhausted the `rt_idx_min_daily=25` endpoint allowance; raw provider responses and exact per-request timing were not retained. This plan does not authorize another real run.

## Scope and boundary

- Fix only the next-minute retry for a just-completed five-minute index cutoff: reacquire indexes whose same-cutoff snapshot has only `MISSING_FIVE_MINUTE_BAR` or `STALE_DATA` issues. Reuse the other same-cutoff snapshots in that retry batch without invoking the provider for them.
- Keep ordinary `prepare` acquisitions and the coordinator's revision-sensitive cache behavior unchanged, including every new cutoff, new plan fact/history requirements, content revisions, and a new trading day. Preserve completed-bar and observation fences, plan-owned condition evaluation, stock deadlines, and index-failure isolation.
- Exercise production scheduling, evaluation persistence, and the real Tushare adapter with a controlled offline SDK and physical-call counter. All generated market frames are `SIMULATED`; no real AI, market, Webhook, broker, order, or database service is called. Do not run R14 `--execute`, read or expose secrets, raise its 60-market or endpoint sub-caps, alter `_session_claimed`, or create an automation.
- Preserve the 16 protected files recorded in `remediation/evidence/R14-preparation/protected-before.json`. Commit only R16-owned files; retain pre-existing user changes.

## Acceptance checklist

- [x] A same-cutoff batch with four `LIVE` and one `STALE` makes exactly one physical retry; that index can become `LIVE`, while the four original snapshot objects remain. All-`LIVE` makes no retry and one cutoff cannot claim twice.
- [x] Provider failure alone is not retried. A mixed `BLOCKED`/`STALE` batch retries only eligible stale indexes; a failed retry remains visibly unhealthy and cannot satisfy an index condition.
- [x] A new cutoff or trading day acquires all indexes normally. New plan fact/history requirements use normal acquisition even when a prior snapshot is `LIVE`; normal provider content-revision changes remain visible.
- [x] An offline production scheduler → evaluation → persistence scenario uses the real Tushare index adapter and controlled SDK counting at a mixed publication boundary. It reports exact physical calls and checks the unchanged bounded allowance, including the all-stale case that selective retry alone cannot make fit.
- [x] A stock plan without an index leaf retains its existing evaluation behavior when an optional display index fails; no index health is falsely reported as `LIVE`.
- [x] Focused index/runtime/R14 wiring tests and applicable Ruff checks pass with unique system-temporary pytest bases. The bilingual R16 handoff records commands, counts, remaining budget limitation, and that R14-A/C7 real acceptance is still not passed.
